"""Ken Burns (pan and zoom) video template."""

from pathlib import Path

from .base_template import BaseVideoTemplate, VideoSpec


class KenBurnsTemplate(BaseVideoTemplate):
    name = "kenburns"
    description = "Pan and zoom (Ken Burns) effect with fade transitions"

    def build_ffmpeg_command(self, spec: VideoSpec, temp_dir: Path) -> list[str]:
        w, h = spec.resolution
        inputs = []
        filter_parts = []
        transition_duration = 0.5

        for i, (img_path, duration) in enumerate(zip(spec.images, spec.segment_durations)):
            inputs.extend(["-loop", "1", "-t", f"{duration + transition_duration:.3f}", "-i", str(img_path)])
            frames = int((duration + transition_duration) * spec.fps)
            filter_parts.append(
                f"[{i}:v]scale={w * 2}:{h * 2},zoompan=z='min(zoom+0.0015,1.5)'"
                f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                f":d={frames}:s={w}x{h}:fps={spec.fps}[v{i}]"
            )

        if len(spec.images) > 1:
            cumulative = spec.segment_durations[0]
            filter_parts.append(
                f"[v0][v1]xfade=transition=fade:duration={transition_duration}"
                f":offset={cumulative - transition_duration:.3f}[xf0]"
            )
            for i in range(2, len(spec.images)):
                cumulative += spec.segment_durations[i - 1]
                prev = f"xf{i - 2}"
                curr = f"xf{i - 1}" if i < len(spec.images) - 1 else "vout"
                filter_parts.append(
                    f"[{prev}][v{i}]xfade=transition=fade:duration={transition_duration}"
                    f":offset={cumulative - transition_duration:.3f}[{curr}]"
                )
            final_label = "vout" if len(spec.images) > 2 else "xf0"
        else:
            final_label = "v0"

        if spec.subtitle_path:
            safe_path = str(spec.subtitle_path).replace("\\", "/").replace(":", "\\\\:")
            s = spec.subtitle_style
            fs = s.get("font_size", 18)
            pc = s.get("primary_colour", "&H00FFFFFF")
            oc = s.get("outline_colour", "&H00000000")
            ow = s.get("outline_width", 1)
            mv = s.get("margin_v", 30)
            filter_parts.append(
                f"[{final_label}]subtitles='{safe_path}':force_style="
                f"'FontSize={fs},PrimaryColour={pc},OutlineColour={oc},Outline={ow},MarginV={mv}'[final]"
            )
            final_label = "final"

        filter_complex = ";".join(filter_parts)

        args = [
            "ffmpeg", "-y",
            *inputs,
            "-i", str(spec.audio_path),
            "-filter_complex", filter_complex,
            "-map", f"[{final_label}]",
            "-map", f"{len(spec.images)}:a",
            "-c:v", spec.video_codec,
            "-crf", str(spec.crf),
            "-preset", "medium",
            "-c:a", spec.audio_codec,
            "-shortest",
            "-pix_fmt", "yuv420p",
            str(spec.output_path),
        ]
        return args
