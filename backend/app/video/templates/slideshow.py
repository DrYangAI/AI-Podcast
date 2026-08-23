"""Slideshow video template."""

from pathlib import Path

from ..subtitle_renderer import SUBTITLE_SIDE_MARGIN
from .base_template import BaseVideoTemplate, VideoSpec


class SlideshowTemplate(BaseVideoTemplate):
    name = "slideshow"
    description = "Simple slideshow: one image per segment"

    def build_ffmpeg_command(self, spec: VideoSpec, temp_dir: Path) -> list[str]:
        # Create concat file
        concat_path = temp_dir / "concat.txt"
        concat_lines = []
        for img_path, duration in zip(spec.images, spec.segment_durations):
            concat_lines.append(f"file '{img_path.name}'")
            concat_lines.append(f"duration {duration:.3f}")
        if spec.images:
            concat_lines.append(f"file '{spec.images[-1].name}'")
        concat_path.write_text("\n".join(concat_lines), encoding="utf-8")

        w, h = spec.resolution
        vf_filters = [
            f"scale={w}:{h}:force_original_aspect_ratio=decrease",
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black",
            "setsar=1",
        ]

        if spec.subtitle_path:
            safe_path = str(spec.subtitle_path).replace("\\", "/").replace(":", "\\\\:")
            s = spec.subtitle_style
            fs = s.get("font_size", 18)
            pc = s.get("primary_colour", "&H00FFFFFF")
            oc = s.get("outline_colour", "&H00000000")
            ow = s.get("outline_width", 1)
            mv = s.get("margin_v", 30)
            rw, rh = spec.resolution
            vf_filters.append(
                f"subtitles='{safe_path}':force_style="
                f"'FontSize={fs},PrimaryColour={pc},OutlineColour={oc},Outline={ow},MarginV={mv},"
                # 和竖屏一致:留出左右边距并开启智能折行,字号调大时
                # 太长的句子在画面内折行,而不是横着顶出去被裁掉
                f"WrapStyle=0,MarginL={SUBTITLE_SIDE_MARGIN},MarginR={SUBTITLE_SIDE_MARGIN},"
                f"PlayResX={rw},PlayResY={rh}'"
            )

        args = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_path),
            "-i", str(spec.audio_path),
            "-vf", ",".join(vf_filters),
            "-c:v", spec.video_codec,
            "-crf", str(spec.crf),
            "-preset", "medium",
            "-c:a", spec.audio_codec,
            "-t", f"{spec.audio_duration:.3f}",
            "-pix_fmt", "yuv420p",
            str(spec.output_path),
        ]
        return args
