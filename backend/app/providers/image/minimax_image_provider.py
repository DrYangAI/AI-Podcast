"""MiniMax 图片生成 Provider — 海螺 AI 文生图 API."""

import base64
import uuid
from pathlib import Path

import httpx

from ..base import ProviderMetadata, ProviderType
from ..registry import ProviderRegistry
from .base import ImageProvider, ImageGenerationRequest, ImageGenerationResponse


@ProviderRegistry.register
class MiniMaxImageProvider(ImageProvider):
    """
    MiniMax 海螺 AI 图片生成模型。

    使用方法:
    - api_key: 填写 MiniMax API Key
    - model_id: 选择模型
    """
    metadata = ProviderMetadata(
        key="minimax_image",
        name="MiniMax 海螺 (文生图)",
        provider_type=ProviderType.IMAGE,
        description="MiniMax 海螺 AI 文生图模型",
        supported_models=[
            "image-01",
        ],
        default_api_base="https://api.minimax.chat/v1",
        requires_api_key=True,
    )

    async def generate(self, request: ImageGenerationRequest,
                       output_dir: Path = Path("")) -> ImageGenerationResponse:
        base_url = self.api_base_url or self.metadata.default_api_base
        url = f"{base_url}/images/generations"
        model = self.model_id or self.metadata.supported_models[0]

        size = f"{request.width}x{request.height}"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "prompt": request.prompt,
            "n": request.num_images,
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        output_dir.mkdir(parents=True, exist_ok=True)
        file_paths = []
        revised_prompts = []

        for item in data.get("data", []):
            file_name = f"{uuid.uuid4().hex}.png"
            file_path = output_dir / file_name

            if item.get("b64_json"):
                file_path.write_bytes(base64.b64decode(item["b64_json"]))
            elif item.get("url"):
                async with httpx.AsyncClient() as dl_client:
                    img_resp = await dl_client.get(item["url"])
                    file_path.write_bytes(img_resp.content)

            file_paths.append(file_path)

        return ImageGenerationResponse(
            file_paths=file_paths,
            revised_prompts=revised_prompts,
            model_used=model,
        )

    async def validate_connection(self) -> bool:
        try:
            base_url = self.api_base_url or self.metadata.default_api_base
            headers = {"Authorization": f"Bearer {self.api_key}"}
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{base_url}/models", headers=headers)
                return resp.status_code == 200
        except Exception:
            return False
