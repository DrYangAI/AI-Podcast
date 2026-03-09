"""阿里云 CosyVoice TTS Provider — DashScope 语音合成.

CosyVoice 是阿里云的高质量语音合成模型。
支持 OpenAI-compatible API 格式。
"""

import asyncio
import base64
import json
import logging
import uuid
from pathlib import Path

import httpx

from ..base import ProviderMetadata, ProviderType
from ..registry import ProviderRegistry
from .base import TTSProvider, TTSRequest, TTSResponse

logger = logging.getLogger(__name__)


@ProviderRegistry.register
class AliyunCosyVoiceProvider(TTSProvider):
    """
    阿里云通义语音合成 (CosyVoice)。
    支持 OpenAI-compatible API 格式。

    使用方法:
    - api_key: 填写阿里云 DashScope API Key
    - model_id: 选择模型，如 cosyvoice-v2, cosyvoice-v1
    - voice_id: 选择音色，如 longxiaochun, longhua 等
    - config 中可以指定 endpoint_id (推理接入点 ID)
    """
    metadata = ProviderMetadata(
        key="aliyun_cosyvoice",
        name="通义语音 (CosyVoice)",
        provider_type=ProviderType.TTS,
        description="阿里云通义语音合成 CosyVoice",
        supported_models=[
            "cosyvoice-v2",
            "cosyvoice-v1",
        ],
        default_api_base="https://dashscope.aliyuncs.com/api/v1",
        requires_api_key=True,
    )

    async def synthesize(self, request: TTSRequest,
                         output_path: Path = Path("")) -> TTSResponse:
        model = self.model_id or self.metadata.supported_models[0]
        # 如果配置了 endpoint_id，使用它替代模型名
        endpoint_id = self.config.get("endpoint_id", "") if self.config else ""
        if endpoint_id:
            model = endpoint_id
        voice = request.voice_id or (self.config.get("voice", "longxiaochun") if self.config else "longxiaochun")

        # 首先尝试使用兼容模式的 OpenAI 格式端点
        url = "https://dashscope.aliyuncs.com/compatible-mode/v1/audio/speech"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "input": request.text,
            "voice": voice,
            "response_format": request.output_format or "mp3",
        }
        if request.speed:
            payload["speed"] = request.speed

        logger.info(f"CosyVoice TTS 请求: model={model}, voice={voice}, url={url}")

        audio_bytes = None
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                logger.info(f"CosyVoice 响应状态: {resp.status_code}")
                if resp.status_code == 404:
                    # 兼容模式端点 404，尝试直接 API 端点
                    logger.info("兼容模式端点 404，尝试直接 API 端点")
                    url = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/generation"
                    payload_direct = {
                        "model": model,
                        "input": {"text": request.text},
                        "parameters": {
                            "voice": voice,
                            "format": request.output_format or "mp3",
                            "sample_rate": 24000,
                        }
                    }
                    resp = await client.post(url, headers=headers, json=payload_direct)
                    logger.info(f"直接 API 响应状态: {resp.status_code}")
                    if resp.status_code != 200:
                        logger.error(f"直接 API 错误响应: {resp.text}")
                    resp.raise_for_status()
                    # 直接 API 返回 JSON，包含 base64 编码的音频
                    data = resp.json()
                    audio_data = data.get("output", {}).get("audio", {})
                    if audio_data.get("data"):
                        audio_bytes = base64.b64decode(audio_data["data"])
                    elif audio_data.get("url"):
                        # 如果返回的是 URL，下载音频
                        audio_url = audio_data["url"]
                        dl_resp = await client.get(audio_url)
                        audio_bytes = dl_resp.content
                    else:
                        raise ValueError(f"无法从响应中获取音频数据: {data}")
                else:
                    resp.raise_for_status()
                    audio_bytes = resp.content
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP 错误: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"请求错误: {str(e)}")
            raise

        if not output_path or output_path == Path(""):
            output_path = Path(f"{uuid.uuid4().hex}.{request.output_format or 'mp3'}")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(audio_bytes)

        duration = await self._get_audio_duration(output_path)

        return TTSResponse(
            file_path=output_path,
            duration=duration,
            sample_rate=22050,
            model_used=model,
        )

    async def list_voices(self) -> list[dict]:
        return [
            {"id": "longxiaochun", "name": "龙小淳 (温柔女声)", "gender": "female", "language": "zh-CN"},
            {"id": "longhua", "name": "龙华 (标准男声)", "gender": "male", "language": "zh-CN"},
            {"id": "longxiaoxia", "name": "龙小夏 (活泼女声)", "gender": "female", "language": "zh-CN"},
            {"id": "longshu", "name": "龙叔 (磁性男声)", "gender": "male", "language": "zh-CN"},
            {"id": "longwan", "name": "龙婉 (知性女声)", "gender": "female", "language": "zh-CN"},
            {"id": "longyue", "name": "龙悦 (甜美女声)", "gender": "female", "language": "zh-CN"},
            {"id": "longfei", "name": "龙飞 (激昂男声)", "gender": "male", "language": "zh-CN"},
        ]

    async def validate_connection(self) -> bool:
        try:
            base_url = self.api_base_url or self.metadata.default_api_base
            headers = {"Authorization": f"Bearer {self.api_key}"}
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{base_url}/models", headers=headers)
                return resp.status_code == 200
        except Exception:
            return False

    @staticmethod
    async def _get_audio_duration(file_path: Path) -> float:
        try:
            process = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "csv=p=0", str(file_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await process.communicate()
            return float(stdout.decode().strip())
        except Exception:
            return 0.0
