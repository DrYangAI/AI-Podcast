"""Image generation provider interface."""

from dataclasses import dataclass, field
from pathlib import Path

from ..base import BaseProvider


@dataclass
class ImageGenerationRequest:
    prompt: str
    negative_prompt: str = ""
    width: int = 1024
    height: int = 1024
    style: str = "natural"
    quality: str = "standard"
    num_images: int = 1


@dataclass
class ImageGenerationResponse:
    file_paths: list[Path] = field(default_factory=list)
    revised_prompts: list[str] = field(default_factory=list)
    model_used: str = ""
    raw_response: dict | None = None


class ImageProvider(BaseProvider):
    """Interface for image generation providers."""

    async def generate(self, request: ImageGenerationRequest,
                       output_dir: Path = Path("")) -> ImageGenerationResponse:
        """Generate image(s) and save to output_dir."""
        raise NotImplementedError

    async def generate_for_segment(self, segment_text: str, image_prompt: str,
                                    aspect_ratio: str,
                                    output_dir: Path = Path(""),
                                    width: int | None = None,
                                    height: int | None = None,
                                    quality: str = "standard",
                                    style: str = "natural",
                                    negative_prompt: str = "") -> ImageGenerationResponse:
        """Generate an image for a content segment."""
        if not width or not height:
            width, height = self._aspect_to_dimensions(aspect_ratio)
        return await self.generate(
            ImageGenerationRequest(
                prompt=image_prompt,
                width=width,
                height=height,
                quality=quality,
                style=style,
                negative_prompt=negative_prompt,
            ),
            output_dir=output_dir,
        )

    @staticmethod
    def _aspect_to_dimensions(aspect_ratio: str) -> tuple[int, int]:
        # 火山引擎 Seedream 要求最小 3686400 像素
        # 计算: 1920x1920=3,686,400, 2560x1440=3,686,400, 1440x2560=3,686,400
        mapping = {
            "16:9": (2560, 1440),  # 3,686,400 像素
            "9:16": (1440, 2560),  # 3,686,400 像素
            "1:1": (1920, 1920),   # 3,686,400 像素
        }
        return mapping.get(aspect_ratio, (1920, 1920))
