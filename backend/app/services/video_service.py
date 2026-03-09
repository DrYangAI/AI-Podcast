"""Video composition service."""

import logging
import re
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from ..database import async_session_factory
from ..models import Project, Segment, ImageAsset, AudioAsset, VideoOutput
from ..config import get_settings
from ..video.composer import VideoComposer

logger = logging.getLogger(__name__)


class VideoService:
    """Handles video composition from images + audio."""

    async def compose_video(self, project_id: str):
        """Compose the final video for a project."""
        settings = get_settings()

        async with async_session_factory() as db:
            project = await db.get(Project, project_id)
            if not project:
                raise ValueError(f"Project {project_id} not found")

            # Get segments
            result = await db.execute(
                select(Segment)
                .where(Segment.project_id == project_id)
                .order_by(Segment.segment_order)
            )
            segments = list(result.scalars().all())
            if not segments:
                raise ValueError("No segments found")

            # Get images
            result = await db.execute(
                select(ImageAsset)
                .where(ImageAsset.project_id == project_id, ImageAsset.status == "completed")
            )
            images = {img.segment_id: img for img in result.scalars().all()}

            # Get audio
            result = await db.execute(select(AudioAsset).where(AudioAsset.project_id == project_id))
            audio = result.scalar_one_or_none()
            if not audio or audio.status != "completed":
                raise ValueError("No completed audio found")

            # Collect image paths in segment order
            image_paths = []
            segment_texts = []
            for segment in segments:
                img = images.get(segment.id)
                if img and img.file_path:
                    image_paths.append(Path(img.file_path))
                    segment_texts.append(segment.content)

            if not image_paths:
                raise ValueError("No images available for video composition")

            # Build output path
            output_dir = Path(settings.storage.output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)

            file_name = self._build_filename(project, settings.output.naming_rule)
            output_path = output_dir / f"{file_name}.{settings.output.default_format}"

            # Compose video
            composer = VideoComposer()
            await composer.compose(
                image_paths=image_paths,
                audio_path=Path(audio.file_path),
                segments=segment_texts,
                output_path=output_path,
                aspect_ratio=project.aspect_ratio,
                template_name=project.video_template,
                subtitle_config={
                    "enabled": getattr(project, "subtitle_enabled", True),
                    "font_size": getattr(project, "subtitle_font_size", 18),
                    "font_color": getattr(project, "subtitle_font_color", "#FFFFFF"),
                    "outline_width": getattr(project, "subtitle_outline_width", 1),
                    "margin_bottom": getattr(project, "subtitle_margin_bottom", 30),
                    "max_chars_per_line": settings.subtitles.max_chars_per_line,
                    "max_lines": settings.subtitles.max_lines,
                },
                video_quality={
                    "crf": settings.output.video_quality.crf,
                    "preset": settings.output.video_quality.preset,
                    "codec": settings.output.video_quality.codec,
                    "audio_codec": settings.output.video_quality.audio_codec,
                    "fps": settings.output.video_quality.fps,
                },
            )

            # Get file size
            file_size = output_path.stat().st_size if output_path.exists() else 0
            w, h = VideoComposer().image_processor.get_resolution(project.aspect_ratio)

            # Save video output record
            video = VideoOutput(
                project_id=project_id,
                file_path=str(output_path),
                file_name=output_path.name,
                aspect_ratio=project.aspect_ratio,
                template_used=project.video_template,
                duration=audio.duration,
                resolution=f"{w}x{h}",
                file_size=file_size,
                has_subtitles=getattr(project, "subtitle_enabled", True),
                status="completed",
            )
            db.add(video)
            await db.commit()
            return video

    def _build_filename(self, project: Project, naming_rule: str) -> str:
        """Build output filename from naming rule template."""
        now = datetime.now()
        replacements = {
            "{date}": now.strftime("%Y%m%d"),
            "{timestamp}": now.strftime("%Y%m%d_%H%M%S"),
            "{topic}": self._sanitize_filename(project.topic[:30]),
            "{aspect_ratio}": project.aspect_ratio.replace(":", "x"),
            "{template}": project.video_template,
            "{id}": project.id[:8],
        }
        result = naming_rule
        for key, value in replacements.items():
            result = result.replace(key, value)
        return result

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """Remove characters not safe for filenames."""
        return re.sub(r'[<>:"/\\|?*\s]+', '_', name).strip('_')
