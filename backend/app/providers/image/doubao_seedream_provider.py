"""豆包 Seedream 图片生成 Provider — 火山引擎视觉智能 API.

Seedream (doubao-seedream-5-0-260128) 是字节跳动的高质量文生图模型。
通过火山引擎 Visual API 调用。
"""

import base64
import json
import logging
import uuid
from pathlib import Path

import httpx

from ..base import ProviderMetadata, ProviderType
from ..registry import ProviderRegistry
from .base import ImageProvider, ImageGenerationRequest, ImageGenerationResponse

logger = logging.getLogger(__name__)


@ProviderRegistry.register
class DoubaoSeedreamProvider(ImageProvider):
    """
    豆包 Seedream 图片生成模型。

    使用方法:
    - api_key: 填写火山引擎 API Key
    - model_id: 模型名，如 doubao-seedream-5-0-260128
    - config 中可以指定 endpoint_id (推理接入点 ID)

    火山引擎 ARK 的图片生成接口:
    POST https://ark.cn-beijing.volces.com/api/v3/images/generations
    兼容 OpenAI images API 格式。
    """
    metadata = ProviderMetadata(
        key="doubao_seedream",
        name="豆包 Seedream (文生图)",
        provider_type=ProviderType.IMAGE,
        description="字节跳动豆包 Seedream 高质量文生图模型",
        supported_models=[
            "doubao-seedream-5-0-260128",
            "doubao-seedream-3-0-t2i-250115",
        ],
        default_api_base="https://ark.cn-beijing.volces.com/api/v3",
        requires_api_key=True,
    )

    async def generate(self, request: ImageGenerationRequest,
                       output_dir: Path = Path("")) -> ImageGenerationResponse:
        base_url = self.api_base_url or self.metadata.default_api_base
        url = f"{base_url}/images/generations"

        model = self.model_id or self.metadata.supported_models[0]
        # 如果配置了 endpoint_id，使用它替代模型名
        endpoint_id = self.config.get("endpoint_id", "") if self.config else ""
        if endpoint_id:
            model = endpoint_id

        # 火山引擎 Seedream 支持的尺寸
        size = f"{request.width}x{request.height}"

        logger.info(f"豆包 Seedream 生成图片: model={model}, size={size}, prompt={request.prompt[:50]}...")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "prompt": request.prompt,
            "size": size,
            "n": request.num_images,
            "response_format": "b64_json",
        }
        if request.negative_prompt:
            payload["negative_prompt"] = request.negative_prompt

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                logger.info(f"Response status: {resp.status_code}")
                if resp.status_code != 200:
                    logger.error(f"API Error: {resp.text}")
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP错误: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"请求错误: {str(e)}")
            raise

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
            if item.get("revised_prompt"):
                revised_prompts.append(item["revised_prompt"])

        return ImageGenerationResponse(
            file_paths=file_paths,
            revised_prompts=revised_prompts,
            model_used=model,
        )

    async def validate_connection(self) -> bool:
        try:
            base_url = self.api_base_url or self.metadata.default_api_base
            url = f"{base_url}/models"
            headers = {"Authorization": f"Bearer {self.api_key}"}
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, headers=headers)
                return resp.status_code == 200
        except Exception:
            return False
