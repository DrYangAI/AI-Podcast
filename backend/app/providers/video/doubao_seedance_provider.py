"""豆包 Seedance 视频生成 Provider — 火山引擎 ARK API.

Seedance (doubao-seedance-2-0-260128) 是字节跳动的图生视频/文生视频模型。
支持图片+文字描述 → 短视频 的能力。

注意: 视频生成是异步任务，需要轮询获取结果。
"""

import asyncio
import uuid
from pathlib import Path

import httpx

from ..base import ProviderMetadata, ProviderType
from ..registry import ProviderRegistry
from .base import VideoProvider, VideoGenerationRequest, VideoGenerationResponse


@ProviderRegistry.register
class DoubaoSeedanceProvider(VideoProvider):
    """
    豆包 Seedance 视频生成模型。

    使用方法:
    - api_key: 填写火山引擎 ARK API Key
    - model_id: 模型名或推理接入点 ID，如 doubao-seedance-2-0-260128
    - config 中可指定:
        - endpoint_id: 推理接入点 ID
        - poll_interval: 轮询间隔秒数 (默认 5)
        - max_wait: 最大等待秒数 (默认 300)
    """
    metadata = ProviderMetadata(
        key="doubao_seedance",
        name="豆包 Seedance (视频生成)",
        provider_type=ProviderType.VIDEO,
        description="字节跳动豆包 Seedance 图生视频/文生视频模型",
        supported_models=[
            "doubao-seedance-2-0-260128",
            "doubao-seaweed-241128",
        ],
        default_api_base="https://ark.cn-beijing.volces.com/api/v3",
        requires_api_key=True,
    )

    async def generate(self, request: VideoGenerationRequest,
                       output_path: Path = Path("")) -> VideoGenerationResponse:
        """
        异步提交视频生成任务，轮询等待完成后下载视频文件。

        ARK 视频生成流程:
        1. POST /content/videos/generations  → 提交任务，获取 task_id
        2. GET  /content/videos/generations/{task_id}  → 轮询状态
        3. 状态为 succeeded 后下载视频文件
        """
        base_url = self.api_base_url or self.metadata.default_api_base

        model = self.config.get("endpoint_id", "") or self.model_id or self.metadata.supported_models[0]
        poll_interval = self.config.get("poll_interval", 5)
        max_wait = self.config.get("max_wait", 300)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # 构建请求体
        payload: dict = {
            "model": model,
            "content": [],
        }

        # 文字描述
        if request.prompt:
            payload["content"].append({
                "type": "text",
                "text": request.prompt,
            })

        # 参考图片 (图生视频)
        if request.image_path and request.image_path != Path(""):
            import base64
            image_data = request.image_path.read_bytes()
            b64_str = base64.b64encode(image_data).decode()
            suffix = request.image_path.suffix.lstrip(".")
            mime = f"image/{suffix}" if suffix in ("png", "jpeg", "jpg", "webp") else "image/png"
            payload["content"].append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime};base64,{b64_str}",
                },
            })

        # 提交任务
        submit_url = f"{base_url}/content/videos/generations"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(submit_url, headers=headers, json=payload)
            resp.raise_for_status()
            result = resp.json()

        task_id = result.get("id", "")
        if not task_id:
            raise RuntimeError(f"Failed to submit video generation task: {result}")

        # 轮询等待
        elapsed = 0
        video_url = ""
        status_url = f"{base_url}/content/videos/generations/{task_id}"

        while elapsed < max_wait:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(status_url, headers=headers)
                resp.raise_for_status()
                status_data = resp.json()

            task_status = status_data.get("status", "")
            if task_status == "succeeded":
                # 提取视频 URL
                for item in status_data.get("data", []):
                    if item.get("url"):
                        video_url = item["url"]
                        break
                break
            elif task_status in ("failed", "cancelled"):
                error = status_data.get("error", {}).get("message", "Unknown error")
                raise RuntimeError(f"Video generation failed: {error}")

        if not video_url:
            raise RuntimeError(f"Video generation timed out after {max_wait}s (task_id={task_id})")

        # 下载视频
        if not output_path or output_path == Path(""):
            output_path = Path(f"{uuid.uuid4().hex}.mp4")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.get(video_url)
            resp.raise_for_status()
            output_path.write_bytes(resp.content)

        return VideoGenerationResponse(
            file_path=output_path,
            duration=request.duration,
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
