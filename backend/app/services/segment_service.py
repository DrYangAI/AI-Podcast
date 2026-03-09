"""Content splitting service."""

import logging

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import async_session_factory
from ..models import Article, Segment

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

            # Delete existing segments
            await db.execute(
                delete(Segment).where(Segment.project_id == project_id)
            )

            # Split by paragraphs
            paragraphs = self._split_by_paragraph(article.content)

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

    def _split_by_paragraph(self, content: str) -> list[str]:
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
        return [p for p in paragraphs if len(p) > 10]
