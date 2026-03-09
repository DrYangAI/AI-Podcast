"""Base class for video composition templates."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class VideoSpec:
    images: list[Path] = field(default_factory=list)
    audio_path: Path = Path("")
    subtitle_path: Path | None = None
    output_path: Path = Path("")
    aspect_ratio: str = "16:9"
    resolution: tuple[int, int] = (1920, 1080)
    segment_durations: list[float] = field(default_factory=list)
    fps: int = 30
    audio_codec: str = "aac"
    video_codec: str = "libx264"
    crf: int = 23
    subtitle_style: dict = field(default_factory=dict)


class BaseVideoTemplate(ABC):
    name: str
    description: str

    @abstractmethod
    def build_ffmpeg_command(self, spec: VideoSpec, temp_dir: Path) -> list[str]:
        ...

    @staticmethod
    def get_resolution(aspect_ratio: str) -> tuple[int, int]:
        mapping = {
            "16:9": (1920, 1080),
            "9:16": (1080, 1920),
            "1:1": (1080, 1080),
        }
        return mapping.get(aspect_ratio, (1920, 1080))
