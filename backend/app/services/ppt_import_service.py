"""PPT import service — turn an uploaded PPT into a ready-to-narrate project.

Each slide becomes a Segment whose picture is the rendered slide (ImageAsset)
and whose narration (`script_text`) is the slide's speaker notes, verbatim. This
pre-populates the outputs of article_generation → script_generation so the
unchanged tts_audio → video_composition pipeline can run next.
"""

import logging
from datetime import datetime
from pathlib import Path

from PIL import Image
from sqlalchemy import delete, select

from ..config import get_settings
from ..database import async_session_factory
from ..models import Article, ImageAsset, PipelineStep, Project, Script, Segment
from ..utils.ppt_importer import DEFAULT_SILENT_SLIDE_SECONDS, import_pptx

logger = logging.getLogger(__name__)

# Pipeline steps whose outputs PPT import fully supplies.
_PREFILLED_STEPS = (
    "article_generation",
    "content_splitting",
    "image_generation",
    "script_generation",
)


class PPTImportService:
    """Imports a PPT into an existing project, replacing its article/segments."""

    async def import_ppt(self, project_id: str, pptx_bytes: bytes, filename: str) -> int:
        """Render slides + notes and populate the project. Returns slide count."""
        settings = get_settings()
        title = Path(filename or "presentation").stem or "presentation"

        # 1. Write the upload to a temp file and render slides to PNGs.
        temp_dir = Path(settings.storage.temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)
        ext = (filename.rsplit(".", 1)[-1] if filename and "." in filename else "pptx").lower()
        tmp_pptx = temp_dir / f"ppt_import_{project_id}.{ext}"
        tmp_pptx.write_bytes(pptx_bytes)

        # Mark the prefilled steps "in_progress" up front so the UI shows the
        # import is working (rendering a large deck can take a couple of minutes)
        # instead of looking idle and tempting the user to run the pipeline early.
        await self._set_prefilled_steps(project_id, "in_progress")

        images_dir = Path(settings.storage.base_dir) / "images" / project_id
        try:
            slides = await import_pptx(tmp_pptx, images_dir)
        finally:
            tmp_pptx.unlink(missing_ok=True)

        if not slides:
            raise ValueError("The presentation contains no slides.")

        notes_joined = "\n\n".join(note for _, note in slides if note)
        base_parent = Path(settings.storage.base_dir).parent

        async with async_session_factory() as db:
            project = await db.get(Project, project_id)
            if not project:
                raise ValueError(f"Project {project_id} not found")

            # 2. Replace the article (one per project) with the slide notes.
            result = await db.execute(select(Article).where(Article.project_id == project_id))
            article = result.scalar_one_or_none()
            if article:
                article.title = title
                article.content = notes_joined
                article.is_manual = True
            else:
                article = Article(
                    project_id=project_id,
                    title=title,
                    content=notes_joined,
                    is_manual=True,
                )
                db.add(article)
                await db.flush()

            # 2b. Create/replace the project Script (one per project). tts_audio
            # requires a Script row to exist; the per-segment narration still comes
            # from each Segment.script_text below, but this row must be present.
            result = await db.execute(select(Script).where(Script.project_id == project_id))
            script = result.scalar_one_or_none()
            if script:
                script.content = notes_joined
                script.is_manual = True
            else:
                db.add(Script(project_id=project_id, content=notes_joined, is_manual=True))
                await db.flush()

            # 3. Replace segments (cascades old images), one per slide.
            await db.execute(delete(Segment).where(Segment.project_id == project_id))
            await db.flush()

            for i, (png_path, note) in enumerate(slides):
                rel_path = str(png_path.relative_to(base_parent))
                width = height = None
                try:
                    with Image.open(png_path) as im:
                        width, height = im.size
                except Exception:
                    logger.debug("Could not read dimensions for %s", png_path)

                segment = Segment(
                    article_id=article.id,
                    project_id=project_id,
                    segment_order=i,
                    content=note,
                    script_text=note,
                    # Empty-note slide: give it a still-frame duration so the
                    # downstream per-segment audio/video path stays aligned.
                    duration_hint=None if note else DEFAULT_SILENT_SLIDE_SECONDS,
                )
                db.add(segment)
                await db.flush()

                db.add(
                    ImageAsset(
                        segment_id=segment.id,
                        project_id=project_id,
                        file_path=rel_path,
                        prompt_used=None,
                        provider_id=None,
                        width=width,
                        height=height,
                        is_manual=True,
                        status="completed",
                    )
                )

            # 4. Mark the supplied steps completed and tag the project source.
            now = datetime.utcnow()
            step_result = await db.execute(
                select(PipelineStep).where(
                    PipelineStep.project_id == project_id,
                    PipelineStep.step_name.in_(_PREFILLED_STEPS),
                )
            )
            for step in step_result.scalars().all():
                step.status = "completed"
                step.started_at = step.started_at or now
                step.completed_at = now
                step.error_message = None

            project.source_type = "ppt"
            project.status = "draft"

            await db.commit()
            logger.info("PPT import complete for %s: %d slides", project_id, len(slides))
            return len(slides)

    @staticmethod
    async def _set_prefilled_steps(project_id: str, status: str, error_message: str | None = None) -> None:
        """Set the status of the four PPT-prefilled pipeline steps."""
        now = datetime.utcnow()
        async with async_session_factory() as db:
            result = await db.execute(
                select(PipelineStep).where(
                    PipelineStep.project_id == project_id,
                    PipelineStep.step_name.in_(_PREFILLED_STEPS),
                )
            )
            for step in result.scalars().all():
                step.status = status
                if status == "in_progress":
                    step.started_at = step.started_at or now
                    step.error_message = None
                elif status == "failed":
                    step.error_message = error_message
                    step.completed_at = now
            await db.commit()
