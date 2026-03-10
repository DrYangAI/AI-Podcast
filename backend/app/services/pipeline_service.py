"""Pipeline orchestration service."""

import json
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import async_session_factory
from ..models import Project, PipelineStep, Article, Segment, ImageAsset, Script, AudioAsset, VideoOutput, ProviderConfig
from ..providers.base import ProviderType
from ..providers.registry import ProviderRegistry
from .article_service import ArticleService
from .segment_service import SegmentService
from .image_service import ImageService
from .script_service import ScriptService
from .audio_service import AudioService
from .video_service import VideoService
from .portrait_service import PortraitCompositeService

logger = logging.getLogger(__name__)


class PipelineService:
    """Orchestrates the 8-step content-to-video pipeline."""

    STEP_HANDLERS = {
        "article_generation": "_run_article_generation",
        "content_splitting": "_run_content_splitting",
        "image_generation": "_run_image_generation",
        "script_generation": "_run_script_generation",
        "tts_audio": "_run_tts_audio",
        "video_composition": "_run_video_composition",
        "portrait_composite": "_run_portrait_composite",
    }

    async def run_pipeline(self, project_id: str, from_step: str | None = None,
                            provider_overrides: dict[str, str] | None = None):
        """Run the full pipeline or from a specific step."""
        async with async_session_factory() as db:
            # 确保旧项目有 portrait_composite 步骤
            await self._ensure_portrait_step(db, project_id)

            steps = await self._get_steps(db, project_id)
            if not steps:
                logger.error(f"No steps found for project {project_id}")
                return

            start_order = 0
            if from_step:
                for step in steps:
                    if step.step_name == from_step:
                        start_order = step.step_order
                        break

            # Update project status
            project = await db.get(Project, project_id)
            if project:
                project.status = "processing"
                await db.commit()

            for step in steps:
                if step.step_order < start_order:
                    continue
                if step.step_name == "topic_input":
                    continue

                # 竖屏合成步骤：检查是否启用
                if step.step_name == "portrait_composite":
                    async with async_session_factory() as db_check:
                        proj = await db_check.get(Project, project_id)
                        if proj and not getattr(proj, "portrait_composite_enabled", False):
                            # 禁用时跳过此步骤
                            step_ref = await self._get_step(db_check, project_id, "portrait_composite")
                            if step_ref:
                                step_ref.status = "skipped"
                                await db_check.commit()
                            continue

                try:
                    await self.run_step(project_id, step.step_name, provider_overrides)
                except Exception as e:
                    logger.error(f"Pipeline failed at step {step.step_name}: {e}")
                    async with async_session_factory() as db2:
                        project = await db2.get(Project, project_id)
                        if project:
                            project.status = "failed"
                            await db2.commit()
                    return

            # Mark project as completed
            async with async_session_factory() as db:
                project = await db.get(Project, project_id)
                if project:
                    project.status = "completed"
                    await db.commit()

    async def run_step(self, project_id: str, step_name: str,
                        provider_overrides: dict[str, str] | None = None):
        """Run a single pipeline step."""
        handler_name = self.STEP_HANDLERS.get(step_name)
        if not handler_name:
            return

        # 单独运行 portrait_composite 时也要检查是否启用
        if step_name == "portrait_composite":
            async with async_session_factory() as db:
                project = await db.get(Project, project_id)
                if project and not getattr(project, "portrait_composite_enabled", False):
                    raise ValueError("竖屏合成已禁用，请先在设置中启用")

        async with async_session_factory() as db:
            step = await self._get_step(db, project_id, step_name)
            if not step:
                raise ValueError(f"Step {step_name} not found")

            step.status = "in_progress"
            step.started_at = datetime.utcnow()
            step.error_message = None
            await db.commit()

        try:
            handler = getattr(self, handler_name)
            await handler(project_id, provider_overrides)

            async with async_session_factory() as db:
                step = await self._get_step(db, project_id, step_name)
                step.status = "completed"
                step.completed_at = datetime.utcnow()
                await db.commit()

        except Exception as e:
            logger.error(f"Step {step_name} failed: {e}", exc_info=True)
            async with async_session_factory() as db:
                step = await self._get_step(db, project_id, step_name)
                step.status = "failed"
                step.error_message = str(e)
                step.completed_at = datetime.utcnow()
                await db.commit()
            raise

    async def _run_article_generation(self, project_id: str,
                                       provider_overrides: dict[str, str] | None = None):
        service = ArticleService()
        await service.generate_article(project_id, provider_overrides)

    async def _run_content_splitting(self, project_id: str,
                                      provider_overrides: dict[str, str] | None = None):
        service = SegmentService()
        await service.split_article(project_id)

    async def _run_image_generation(self, project_id: str,
                                     provider_overrides: dict[str, str] | None = None):
        service = ImageService()
        await service.generate_images(project_id, provider_overrides)

    async def _run_script_generation(self, project_id: str,
                                      provider_overrides: dict[str, str] | None = None):
        service = ScriptService()
        await service.generate_script(project_id, provider_overrides)

    async def _run_tts_audio(self, project_id: str,
                              provider_overrides: dict[str, str] | None = None):
        service = AudioService()
        await service.generate_tts(project_id, provider_overrides)

    async def _run_video_composition(self, project_id: str,
                                      provider_overrides: dict[str, str] | None = None):
        service = VideoService()
        await service.compose_video(project_id)

    async def _run_portrait_composite(self, project_id: str,
                                       provider_overrides: dict[str, str] | None = None):
        service = PortraitCompositeService()
        await service.compose_portrait(project_id)

    async def _ensure_portrait_step(self, db: AsyncSession, project_id: str):
        """确保旧项目也有 portrait_composite 步骤（向后兼容）。"""
        steps = await self._get_steps(db, project_id)
        step_names = {s.step_name for s in steps}
        if "portrait_composite" not in step_names:
            new_step = PipelineStep(
                project_id=project_id,
                step_name="portrait_composite",
                step_order=7,
                status="pending",
            )
            db.add(new_step)
            await db.commit()

    async def _get_steps(self, db: AsyncSession, project_id: str) -> list[PipelineStep]:
        result = await db.execute(
            select(PipelineStep)
            .where(PipelineStep.project_id == project_id)
            .order_by(PipelineStep.step_order)
        )
        return list(result.scalars().all())

    async def _get_step(self, db: AsyncSession, project_id: str, step_name: str) -> PipelineStep:
        result = await db.execute(
            select(PipelineStep)
            .where(PipelineStep.project_id == project_id, PipelineStep.step_name == step_name)
        )
        return result.scalar_one_or_none()
