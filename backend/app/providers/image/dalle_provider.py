"""DALL-E image generation provider."""

import base64
import uuid
from pathlib import Path

import httpx
import openai

from ..base import ProviderMetadata, ProviderType
from ..registry import ProviderRegistry
from .base import ImageProvider, ImageGenerationRequest, ImageGenerationResponse


@ProviderRegistry.register
class DalleProvider(ImageProvider):
    metadata = ProviderMetadata(
        key="dalle",
        name="DALL-E (OpenAI)",
        provider_type=ProviderType.IMAGE,
        description="OpenAI DALL-E models for image generation",
        supported_models=["dall-e-3", "dall-e-2"],
        default_api_base="https://api.openai.com/v1",
        requires_api_key=True,
    )

    async def generate(self, request: ImageGenerationRequest,
                       output_dir: Path = Path("")) -> ImageGenerationResponse:
        client = openai.AsyncOpenAI(api_key=self.api_key, base_url=self.api_base_url or None)

        size = self._get_dalle_size(request.width, request.height)

        response = await client.images.generate(
            model=self.model_id or "dall-e-3",
            prompt=request.prompt,
            n=1,
            size=size,
            quality=request.quality,
            style=request.style if request.style != "natural" else "natural",
        )

        file_paths = []
        revised_prompts = []
        output_dir.mkdir(parents=True, exist_ok=True)

        for img_data in response.data:
            file_name = f"{uuid.uuid4().hex}.png"
            file_path = output_dir / file_name

            if img_data.url:
                async with httpx.AsyncClient() as http_client:
                    img_response = await http_client.get(img_data.url)
                    file_path.write_bytes(img_response.content)
            elif img_data.b64_json:
                file_path.write_bytes(base64.b64decode(img_data.b64_json))

            file_paths.append(file_path)
            if img_data.revised_prompt:
                revised_prompts.append(img_data.revised_prompt)

        return ImageGenerationResponse(
            file_paths=file_paths,
            revised_prompts=revised_prompts,
            model_used=self.model_id or "dall-e-3",
        )

    async def validate_connection(self) -> bool:
        try:
            client = openai.AsyncOpenAI(api_key=self.api_key, base_url=self.api_base_url or None)
            await client.models.list()
            return True
        except Exception:
            return False

    @staticmethod
    def _get_dalle_size(width: int, height: int) -> str:
        if width > height:
            return "1792x1024"
        elif height > width:
            return "1024x1792"
        else:
            return "1024x1024"
