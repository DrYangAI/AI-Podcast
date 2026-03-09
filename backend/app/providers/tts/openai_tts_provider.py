"""OpenAI TTS provider."""

import asyncio
import uuid
from pathlib import Path

import openai

from ..base import ProviderMetadata, ProviderType
from ..registry import ProviderRegistry
from .base import TTSProvider, TTSRequest, TTSResponse


@ProviderRegistry.register
class OpenAITTSProvider(TTSProvider):
    metadata = ProviderMetadata(
        key="openai_tts",
        name="TTS (OpenAI)",
        provider_type=ProviderType.TTS,
        description="OpenAI text-to-speech models",
        supported_models=["tts-1", "tts-1-hd"],
        default_api_base="https://api.openai.com/v1",
        requires_api_key=True,
    )

    async def synthesize(self, request: TTSRequest,
                         output_path: Path = Path("")) -> TTSResponse:
        client = openai.AsyncOpenAI(api_key=self.api_key, base_url=self.api_base_url or None)

        voice = request.voice_id or self.config.get("voice", "alloy")

        response = await client.audio.speech.create(
            model=self.model_id or "tts-1",
            voice=voice,
            input=request.text,
            speed=request.speed,
            response_format=request.output_format,
        )

        if not output_path or output_path == Path(""):
            output_path = Path(f"{uuid.uuid4().hex}.{request.output_format}")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(response.content)

        duration = await self._get_audio_duration(output_path)

        return TTSResponse(
            file_path=output_path,
            duration=duration,
            sample_rate=24000,
            model_used=self.model_id or "tts-1",
        )

    async def list_voices(self) -> list[dict]:
        return [
            {"id": "alloy", "name": "Alloy", "gender": "neutral", "language": "multi"},
            {"id": "echo", "name": "Echo", "gender": "male", "language": "multi"},
            {"id": "fable", "name": "Fable", "gender": "neutral", "language": "multi"},
            {"id": "onyx", "name": "Onyx", "gender": "male", "language": "multi"},
            {"id": "nova", "name": "Nova", "gender": "female", "language": "multi"},
            {"id": "shimmer", "name": "Shimmer", "gender": "female", "language": "multi"},
        ]

    async def validate_connection(self) -> bool:
        try:
            client = openai.AsyncOpenAI(api_key=self.api_key, base_url=self.api_base_url or None)
            await client.models.list()
            return True
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
