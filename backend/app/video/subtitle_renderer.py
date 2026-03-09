"""SRT subtitle file generation."""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class SubtitleEntry:
    index: int
    start_time: float
    end_time: float
    text: str


class SubtitleRenderer:
    """Generate SRT files from script segments and timing data."""

    def generate_srt(self, segments: list[str], durations: list[float],
                     output_path: Path,
                     max_chars_per_line: int = 20,
                     max_lines: int = 2) -> Path:
        entries = []
        current_time = 0.0
        index = 1

        for segment_text, duration in zip(segments, durations):
            lines = self._split_text(segment_text, max_chars_per_line, max_lines)
            sub_duration = duration / max(len(lines), 1)

            for line_group in lines:
                entries.append(SubtitleEntry(
                    index=index,
                    start_time=current_time,
                    end_time=current_time + sub_duration,
                    text=line_group,
                ))
                current_time += sub_duration
                index += 1

        srt_content = self._format_srt(entries)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(srt_content, encoding="utf-8")
        return output_path

    def _split_text(self, text: str, max_chars: int, max_lines: int) -> list[str]:
        text = text.strip()
        if not text:
            return [""]

        chunks = []
        while text:
            part_len = max_chars * max_lines
            if len(text) <= part_len:
                lines = []
                while text:
                    lines.append(text[:max_chars])
                    text = text[max_chars:]
                chunks.append("\n".join(lines))
                break
            else:
                part = text[:part_len]
                lines = [part[i:i + max_chars] for i in range(0, len(part), max_chars)]
                chunks.append("\n".join(lines))
                text = text[part_len:]

        return chunks if chunks else [""]

    @staticmethod
    def _format_srt(entries: list[SubtitleEntry]) -> str:
        lines = []
        for entry in entries:
            start = SubtitleRenderer._seconds_to_srt_time(entry.start_time)
            end = SubtitleRenderer._seconds_to_srt_time(entry.end_time)
            lines.append(f"{entry.index}")
            lines.append(f"{start} --> {end}")
            lines.append(entry.text)
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _seconds_to_srt_time(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
