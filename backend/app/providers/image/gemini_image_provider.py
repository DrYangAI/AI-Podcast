"""Google Gemini image generation provider (native Gemini API)."""

import base64
import logging
import uuid
from pathlib import Path

import httpx

from ..base import ProviderMetadata, ProviderType
from ..registry import ProviderRegistry
from .base import ImageProvider, ImageGenerationRequest, ImageGenerationResponse

logger = logging.getLogger(__name__)


@ProviderRegistry.register
class GeminiImageProvider(ImageProvider):
    metadata = ProviderMetadata(
        key="gemini_image",
        name="Google Gemini Image",
        provider_type=ProviderType.IMAGE,
        description="Google Gemini 图片生成，支持多种宽高比和中文文字渲染",
        supported_models=[
            "gemini-3-pro-image-preview",
            "gemini-3.1-flash-image-preview",
            "gemini-2.5-flash-image",
        ],
        default_api_base="https://generativelanguage.googleapis.com/v1beta",
        requires_api_key=True,
    )

    MAX_RETRIES = 3

    async def generate(self, request: ImageGenerationRequest,
                       output_dir: Path = Path("")) -> ImageGenerationResponse:
        model = self.model_id or self.metadata.supported_models[0]
        api_base = self.api_base_url or self.metadata.default_api_base
        url = f"{api_base}/models/{model}:generateContent"

        aspect_ratio = self._dimensions_to_aspect(request.width, request.height)

        # Build prompt: main prompt + negative prompt
        prompt = request.prompt
        if request.negative_prompt:
            prompt += f"\n\nAvoid the following: {request.negative_prompt}"

        body = {
            "contents": [{"parts": [{"text": f"Generate an image: {prompt}"}]}],
            "generationConfig": {
                "responseModalities": ["IMAGE", "TEXT"],
                "imageConfig": {
                    "aspectRatio": aspect_ratio,
                },
            },
        }

        output_dir.mkdir(parents=True, exist_ok=True)
        last_error = None

        for attempt in range(self.MAX_RETRIES):
            try:
                file_paths, text_parts = await self._call_gemini(url, body, output_dir)
                if file_paths:
                    return ImageGenerationResponse(
                        file_paths=file_paths,
                        revised_prompts=[],
                        model_used=model,
                    )
                # No image returned, will retry
                last_error = f"Gemini returned text instead of image: {'; '.join(text_parts)[:200]}"
                logger.warning("Attempt %d/%d: %s", attempt + 1, self.MAX_RETRIES, last_error)
            except ValueError:
                raise  # Safety filter, don't retry
            except Exception as e:
                last_error = str(e)
                logger.warning("Attempt %d/%d failed: %s", attempt + 1, self.MAX_RETRIES, e)

            if attempt < self.MAX_RETRIES - 1:
                import asyncio
                await asyncio.sleep(2 * (attempt + 1))

        raise ValueError(last_error or "Gemini image generation failed after retries")

    async def _call_gemini(self, url: str, body: dict, output_dir: Path) -> tuple[list[Path], list[str]]:
        """Call Gemini API and return (file_paths, text_parts)."""
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                url,
                json=body,
                headers={"x-goog-api-key": self.api_key},
            )
            response.raise_for_status()
            data = response.json()

        candidates = data.get("candidates", [])
        if not candidates:
            logger.error("Gemini returned no candidates. Full response: %s", data)
            raise ValueError("Gemini image generation returned no candidates")

        candidate = candidates[0]
        finish_reason = candidate.get("finishReason", "")
        if finish_reason == "SAFETY":
            safety_ratings = candidate.get("safetyRatings", [])
            logger.warning("Gemini blocked by safety filter: %s", safety_ratings)
            raise ValueError(
                "Image blocked by Gemini safety filter (finishReason=SAFETY). "
                "Try rephrasing the prompt."
            )

        parts = candidate.get("content", {}).get("parts", [])
        file_paths = []
        text_parts = []
        for part in parts:
            inline_data = part.get("inlineData") or part.get("inline_data")
            if inline_data and inline_data.get("data"):
                mime_type = inline_data.get("mimeType") or inline_data.get("mime_type", "image/png")
                ext = "png" if "png" in mime_type else "jpg"
                file_name = f"{uuid.uuid4().hex}.{ext}"
                file_path = output_dir / file_name
                file_path.write_bytes(base64.b64decode(inline_data["data"]))
                file_paths.append(file_path)
            elif part.get("text"):
                text_parts.append(part["text"])

        return file_paths, text_parts

    async def validate_connection(self) -> bool:
        """Test connectivity by listing models."""
        api_base = self.api_base_url or self.metadata.default_api_base
        url = f"{api_base}/models"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(
                    url,
                    headers={"x-goog-api-key": self.api_key},
                    params={"pageSize": 1},
                )
                response.raise_for_status()
                return True
        except Exception as e:
            self._last_error = str(e)
            return False

    @staticmethod
    def _dimensions_to_aspect(width: int, height: int) -> str:
        """Convert pixel dimensions to Gemini aspect ratio string."""
        ratio = width / height if height else 1.0
        if ratio > 1.9:
            return "21:9"
        elif ratio > 1.5:
            return "16:9"
        elif ratio > 1.2:
            return "4:3"
        elif ratio > 0.85:
            return "1:1"
        elif ratio > 0.7:
            return "3:4"
        elif ratio > 0.55:
            return "9:16"
        else:
            return "9:21"
