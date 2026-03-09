"""MiniMax TTS Provider — 海螺 AI 语音合成.

MiniMax 提供高质量中文语音合成，支持多种音色。
API 格式兼容 OpenAI audio/speech 格式。
"""

import asyncio
import uuid
from pathlib import Path

import httpx

from ..base import ProviderMetadata, ProviderType
from ..registry import ProviderRegistry
from .base import TTSProvider, TTSRequest, TTSResponse


@ProviderRegistry.register
class MiniMaxTTSProvider(TTSProvider):
    """
    MiniMax 海螺 AI 语音合成。

    使用方法:
    - api_key: 填写 MiniMax API Key
    - model_id: 选择模型，如 speech-02-hd, speech-02-turbo
    - voice_id: 选择音色 ID（可通过 list_voices 查看）
    """
    metadata = ProviderMetadata(
        key="minimax_tts",
        name="MiniMax 海螺 (语音合成)",
        provider_type=ProviderType.TTS,
        description="MiniMax 海螺 AI 高质量语音合成",
        supported_models=[
            "speech-02-hd",
            "speech-02-turbo",
            "speech-02",
            "speech-01-turbo",
            "speech-01-hd",
        ],
        default_api_base="https://api.minimax.chat/v1",
        requires_api_key=True,
    )

    async def synthesize(self, request: TTSRequest,
                         output_path: Path = Path("")) -> TTSResponse:
        base_url = self.api_base_url or self.metadata.default_api_base
        url = f"{base_url}/audio/speech"
        model = self.model_id or self.metadata.supported_models[0]
        voice = request.voice_id or self.config.get("voice", "Calm_Woman")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "input": request.text,
            "voice": voice,
            "speed": request.speed,
            "response_format": request.output_format or "mp3",
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            audio_bytes = resp.content

        if not output_path or output_path == Path(""):
            output_path = Path(f"{uuid.uuid4().hex}.{request.output_format or 'mp3'}")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(audio_bytes)

        duration = await self._get_audio_duration(output_path)

        return TTSResponse(
            file_path=output_path,
            duration=duration,
            sample_rate=24000,
            model_used=model,
        )

    async def list_voices(self) -> list[dict]:
        return [
            {"id": "Calm_Woman", "name": "沉稳女声", "gender": "female", "language": "zh-CN"},
            {"id": "Gentle_Woman", "name": "温柔女声", "gender": "female", "language": "zh-CN"},
            {"id": "Mature_Man", "name": "成熟男声", "gender": "male", "language": "zh-CN"},
            {"id": "Deep_Voice_Man", "name": "浑厚男声", "gender": "male", "language": "zh-CN"},
            {"id": "Lively_Girl", "name": "活泼女声", "gender": "female", "language": "zh-CN"},
            {"id": "Warm_Boy", "name": "温暖男声", "gender": "male", "language": "zh-CN"},
            {"id": "News_Woman", "name": "新闻女声", "gender": "female", "language": "zh-CN"},
            {"id": "News_Man", "name": "新闻男声", "gender": "male", "language": "zh-CN"},
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
