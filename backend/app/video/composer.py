"""Main video composition engine."""

import shutil
import uuid
from pathlib import Path

from .ffmpeg_builder import FFmpegBuilder
from .image_processor import ImageProcessor
from .subtitle_renderer import SubtitleRenderer
from .templates.base_template import VideoSpec
from .templates.slideshow import SlideshowTemplate
from .templates.kenburns import KenBurnsTemplate


TEMPLATES = {
    "slideshow": SlideshowTemplate(),
    "kenburns": KenBurnsTemplate(),
}


def _hex_color_to_ass(hex_color: str) -> str:
    """Convert #RRGGBB to FFmpeg ASS format &H00BBGGRR."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return "&H00FFFFFF"
    r, g, b = hex_color[0:2], hex_color[2:4], hex_color[4:6]
    return f"&H00{b}{g}{r}".upper()


def calculate_segment_durations(segments: list[str], total_audio_duration: float) -> list[float]:
    """Distribute audio duration across segments proportional to text length."""
    total_chars = sum(len(s) for s in segments)
    if total_chars == 0:
        return [total_audio_duration / max(len(segments), 1)] * len(segments)
    return [(len(s) / total_chars) * total_audio_duration for s in segments]


class VideoComposer:
    def __init__(self):
        self.ffmpeg = FFmpegBuilder()
        self.image_processor = ImageProcessor()
        self.subtitle_renderer = SubtitleRenderer()

    async def compose(
        self,
        image_paths: list[Path],
        audio_path: Path,
        segments: list[str],
        output_path: Path,
        aspect_ratio: str = "16:9",
        template_name: str = "slideshow",
        subtitle_config: dict | None = None,
        video_quality: dict | None = None,
        external_srt_path: Path | None = None,
        progress_callback=None,
    ) -> Path:
        template = TEMPLATES.get(template_name, TEMPLATES["slideshow"])
        w, h = template.get_resolution(aspect_ratio)

        temp_dir = output_path.parent / f"temp_{uuid.uuid4().hex[:8]}"
        temp_dir.mkdir(parents=True, exist_ok=True)

        try:
            # 1. Preprocess images to target resolution
            processed_images = []
            for i, img_path in enumerate(image_paths):
                processed_path = temp_dir / f"img_{i:03d}.png"
                self.image_processor.prepare_for_video(img_path, w, h, processed_path)
                processed_images.append(processed_path)

            # 2. Get audio duration
            audio_duration = await self.ffmpeg.get_duration(audio_path)
            if audio_duration <= 0:
                raise ValueError("Could not determine audio duration")

            # 3. Calculate segment durations
            durations = calculate_segment_durations(segments, audio_duration)

            # 4. Generate subtitles
            subtitle_path = None
            cfg = subtitle_config or {}
            if cfg.get("enabled", True):
                if external_srt_path and external_srt_path.exists():
                    # Use ASR-generated SRT with precise timing
                    subtitle_path = external_srt_path
                else:
                    # Fallback: proportional timing
                    subtitle_path = temp_dir / "subtitles.srt"
                    self.subtitle_renderer.generate_srt(
                        segments=segments,
                        durations=durations,
                        output_path=subtitle_path,
                        max_chars_per_line=cfg.get("max_chars_per_line", 20),
                        max_lines=cfg.get("max_lines", 2),
                    )

            # 5. Build subtitle style for FFmpeg ASS format
            font_color = cfg.get("font_color", "#FFFFFF")
            outline_color = "#000000"  # always black outline for readability
            subtitle_style = {
                "font_size": cfg.get("font_size", 18),
                "primary_colour": _hex_color_to_ass(font_color),
                "outline_colour": _hex_color_to_ass(outline_color),
                "outline_width": cfg.get("outline_width", 1),
                "margin_v": cfg.get("margin_bottom", 30),
            }

            # 6. Build video spec
            quality = video_quality or {}
            spec = VideoSpec(
                images=processed_images,
                audio_path=audio_path,
                subtitle_path=subtitle_path,
                output_path=output_path,
                aspect_ratio=aspect_ratio,
                resolution=(w, h),
                segment_durations=durations,
                fps=quality.get("fps", 30),
                video_codec=quality.get("codec", "libx264"),
                audio_codec=quality.get("audio_codec", "aac"),
                crf=quality.get("crf", 23),
                subtitle_style=subtitle_style,
            )

            # 7. Execute FFmpeg
            command = template.build_ffmpeg_command(spec, temp_dir)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            returncode, stdout, stderr = await self.ffmpeg.execute(command, progress_callback)
            if returncode != 0:
                raise RuntimeError(f"FFmpeg failed (code {returncode}): {stderr[-500:]}")

            return output_path

        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
