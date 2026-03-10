"""Video composition service."""

import logging
import re
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from ..database import async_session_factory
from ..models import Project, Segment, Script, ImageAsset, AudioAsset, VideoOutput
from ..config import get_settings
from ..video.composer import VideoComposer, calculate_segment_durations
from ..video.subtitle_renderer import SubtitleRenderer
from .audio_service import clean_script_for_tts

logger = logging.getLogger(__name__)


def _split_script_to_paragraphs(script, num_segments: int) -> list[str] | None:
    """Split the Script content into paragraphs matching the number of segments.

    The script (口播稿) is what TTS actually speaks, so using it for subtitles
    ensures subtitles match the narration audio.
    """
    if not script or not script.content:
        return None

    cleaned = clean_script_for_tts(script.content)
    # Split by double newlines (paragraph breaks)
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', cleaned) if p.strip()]

    if not paragraphs:
        return None

    # If paragraph count matches segment count, perfect 1:1 mapping
    if len(paragraphs) == num_segments:
        return paragraphs

    # If more paragraphs than segments, merge extras into last paragraph
    if len(paragraphs) > num_segments:
        merged = paragraphs[:num_segments - 1]
        merged.append('\n'.join(paragraphs[num_segments - 1:]))
        return merged

    # If fewer paragraphs than segments, try splitting long paragraphs by single newline
    lines = [line.strip() for line in cleaned.split('\n') if line.strip()]
    if len(lines) == num_segments:
        return lines

    # If still not matching, distribute lines across segments proportionally
    if len(lines) > num_segments:
        merged = lines[:num_segments - 1]
        merged.append('\n'.join(lines[num_segments - 1:]))
        return merged

    # Fewer lines than segments: pad with empty strings is bad,
    # fall back to original paragraphs (better than nothing)
    return paragraphs


class VideoService:
    """Handles video composition from images + audio."""

    async def compose_video(self, project_id: str):
        """Compose the final video for a project."""
        settings = get_settings()

        async with async_session_factory() as db:
            project = await db.get(Project, project_id)
            if not project:
                raise ValueError(f"Project {project_id} not found")

            # 当竖屏合成启用时，步骤 7 强制使用 16:9 + 无字幕
            portrait_enabled = getattr(project, "portrait_composite_enabled", False)
            effective_aspect_ratio = project.aspect_ratio
            effective_subtitle_enabled = getattr(project, "subtitle_enabled", True)

            if portrait_enabled:
                effective_aspect_ratio = "16:9"
                effective_subtitle_enabled = False

            # Get segments
            result = await db.execute(
                select(Segment)
                .where(Segment.project_id == project_id)
                .order_by(Segment.segment_order)
            )
            segments = list(result.scalars().all())
            if not segments:
                raise ValueError("No segments found")

            # Get script (口播稿) for subtitle text — matches TTS audio
            result = await db.execute(select(Script).where(Script.project_id == project_id))
            script = result.scalar_one_or_none()

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

            # Build subtitle texts from script (口播稿) so subtitles match narration
            script_paragraphs = _split_script_to_paragraphs(script, len(segments)) if script else None

            # Collect image paths in segment order
            image_paths = []
            segment_texts = []
            for i, segment in enumerate(segments):
                img = images.get(segment.id)
                if img and img.file_path:
                    image_paths.append(Path(img.file_path))
                    # Use script paragraph if available, otherwise fall back to segment
                    if script_paragraphs and i < len(script_paragraphs):
                        segment_texts.append(script_paragraphs[i])
                    else:
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
                aspect_ratio=effective_aspect_ratio,
                template_name=project.video_template,
                subtitle_config={
                    "enabled": effective_subtitle_enabled,
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
            w, h = composer.image_processor.get_resolution(effective_aspect_ratio)

            # 当竖屏合成启用时，独立生成 SRT 字幕文件供步骤 8 使用
            subtitle_file_path = None
            if portrait_enabled and audio.duration:
                srt_dir = Path(settings.storage.base_dir) / "subtitles" / project_id
                srt_dir.mkdir(parents=True, exist_ok=True)
                srt_path = srt_dir / "portrait_subtitles.srt"

                durations = calculate_segment_durations(segment_texts, audio.duration)
                renderer = SubtitleRenderer()
                renderer.generate_srt(
                    segments=segment_texts,
                    durations=durations,
                    output_path=srt_path,
                    max_chars_per_line=settings.subtitles.max_chars_per_line,
                    max_lines=settings.subtitles.max_lines,
                )
                subtitle_file_path = str(srt_path)

            # Save video output record
            video = VideoOutput(
                project_id=project_id,
                file_path=str(output_path),
                file_name=output_path.name,
                aspect_ratio=effective_aspect_ratio,
                template_used=project.video_template,
                duration=audio.duration,
                resolution=f"{w}x{h}",
                file_size=file_size,
                has_subtitles=effective_subtitle_enabled,
                subtitle_file=subtitle_file_path,
                video_type="standard",
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
