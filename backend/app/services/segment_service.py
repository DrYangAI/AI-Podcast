"""Content splitting service."""

import json
import logging

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import async_session_factory
from ..models import Article, Segment, Project

logger = logging.getLogger(__name__)


class SegmentService:
    """Handles splitting articles into segments/paragraphs."""

    async def split_article(self, project_id: str):
        """Split the project's article into segments by paragraph."""
        async with async_session_factory() as db:
            result = await db.execute(select(Article).where(Article.project_id == project_id))
            article = result.scalar_one_or_none()
            if not article:
                raise ValueError(f"No article found for project {project_id}")

            # Resolve content_splitting config for min_paragraph_length
            min_length = 10  # default
            try:
                from ..services.prompt_template_service import PromptTemplateService
                project = await db.get(Project, project_id)
                template = await PromptTemplateService.get_by_step(db, "content_splitting")
                if template and template.extra_config:
                    extra = json.loads(template.extra_config)
                    min_length = extra.get("min_paragraph_length", 10)

                # Check project overrides
                if project and project.metadata_json:
                    metadata = json.loads(project.metadata_json)
                    overrides = metadata.get("prompt_overrides", {}).get("content_splitting", {})
                    if "extra_config" in overrides:
                        min_length = overrides["extra_config"].get("min_paragraph_length", min_length)
            except Exception:
                logger.debug("Failed to resolve content_splitting config, using default min_length=%d", min_length)

            # Delete existing segments
            await db.execute(
                delete(Segment).where(Segment.project_id == project_id)
            )

            # Split by paragraphs
            paragraphs = self._split_by_paragraph(article.content, min_length=min_length)

            segments = []
            for i, para in enumerate(paragraphs):
                segment = Segment(
                    article_id=article.id,
                    project_id=project_id,
                    segment_order=i,
                    content=para,
                )
                db.add(segment)
                segments.append(segment)

            await db.commit()
            return segments

    def _split_by_paragraph(self, content: str, min_length: int = 10) -> list[str]:
        """Split content into paragraphs, filtering empty ones."""
        lines = content.split("\n")
        paragraphs = []
        current = []

        for line in lines:
            stripped = line.strip()
            if stripped:
                current.append(stripped)
            elif current:
                paragraphs.append("\n".join(current))
                current = []

        if current:
            paragraphs.append("\n".join(current))

        # Filter out very short paragraphs (likely headers or separators)
        return [p for p in paragraphs if len(p) > min_length]
