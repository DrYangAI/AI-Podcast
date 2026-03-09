"""Video generation provider interface (placeholder for future image-to-video models)."""

from dataclasses import dataclass
from pathlib import Path

from ..base import BaseProvider


@dataclass
class VideoGenerationRequest:
    image_path: Path = Path("")
    prompt: str = ""
    duration: float = 5.0
    fps: int = 30


@dataclass
class VideoGenerationResponse:
    file_path: Path = Path("")
    duration: float = 0.0
    model_used: str = ""


class VideoProvider(BaseProvider):
    """Interface for image-to-video providers (future)."""

    async def generate(self, request: VideoGenerationRequest,
                       output_path: Path = Path("")) -> VideoGenerationResponse:
        """Generate video from image."""
        raise NotImplementedError
