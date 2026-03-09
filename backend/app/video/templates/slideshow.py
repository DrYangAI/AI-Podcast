"""Slideshow video template."""

from pathlib import Path

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
            vf_filters.append(
                f"subtitles='{safe_path}':force_style="
                f"'FontSize={fs},PrimaryColour={pc},OutlineColour={oc},Outline={ow},MarginV={mv}'"
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
            "-shortest",
            "-pix_fmt", "yuv420p",
            str(spec.output_path),
        ]
        return args
