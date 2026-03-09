"""智谱 CogVideoX 视频生成 Provider.

智谱 CogVideoX 支持文生视频和图生视频，使用异步任务模式。
"""

import asyncio
import uuid
from pathlib import Path

import httpx

from ..base import ProviderMetadata, ProviderType
from ..registry import ProviderRegistry
from .base import VideoProvider, VideoGenerationRequest, VideoGenerationResponse


@ProviderRegistry.register
class ZhipuCogVideoProvider(VideoProvider):
    """
    智谱 CogVideoX 视频生成模型。

    使用方法:
    - api_key: 填写智谱 API Key
    - model_id: 选择模型，如 cogvideox-2
    - config 中可指定:
        - poll_interval: 轮询间隔秒数 (默认 10)
        - max_wait: 最大等待秒数 (默认 600)
    """
    metadata = ProviderMetadata(
        key="zhipu_cogvideo",
        name="智谱 CogVideoX (视频生成)",
        provider_type=ProviderType.VIDEO,
        description="智谱 AI CogVideoX 视频生成模型",
        supported_models=[
            "cogvideox-2",
            "cogvideox",
        ],
        default_api_base="https://open.bigmodel.cn/api/paas/v4",
        requires_api_key=True,
    )

    async def generate(self, request: VideoGenerationRequest,
                       output_path: Path = Path("")) -> VideoGenerationResponse:
        base_url = self.api_base_url or self.metadata.default_api_base
        model = self.model_id or self.metadata.supported_models[0]
        poll_interval = self.config.get("poll_interval", 10)
        max_wait = self.config.get("max_wait", 600)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload: dict = {
            "model": model,
            "prompt": request.prompt or "Generate a video",
        }

        # 图生视频: 附带参考图片 URL
        if request.image_path and request.image_path != Path(""):
            import base64
            image_data = request.image_path.read_bytes()
            b64_str = base64.b64encode(image_data).decode()
            suffix = request.image_path.suffix.lstrip(".")
            mime = f"image/{suffix}" if suffix in ("png", "jpeg", "jpg", "webp") else "image/png"
            payload["image_url"] = f"data:{mime};base64,{b64_str}"

        # 提交异步任务
        submit_url = f"{base_url}/videos/generations"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(submit_url, headers=headers, json=payload)
            resp.raise_for_status()
            result = resp.json()

        task_id = result.get("id", "")
        if not task_id:
            raise RuntimeError(f"Failed to submit CogVideoX task: {result}")

        # 轮询任务状态
        elapsed = 0
        video_url = ""
        status_url = f"{base_url}/async-result/{task_id}"

        while elapsed < max_wait:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(status_url, headers=headers)
                resp.raise_for_status()
                status_data = resp.json()

            task_status = status_data.get("task_status", "")
            if task_status == "SUCCESS":
                video_results = status_data.get("video_result", [])
                if video_results:
                    video_url = video_results[0].get("url", "")
                break
            elif task_status == "FAIL":
                raise RuntimeError(f"CogVideoX task failed: {status_data}")

        if not video_url:
            raise RuntimeError(f"CogVideoX timed out after {max_wait}s (task_id={task_id})")

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
