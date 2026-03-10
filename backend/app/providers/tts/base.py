"""Text-to-speech provider interface."""

from dataclasses import dataclass, field
from pathlib import Path

from ..base import BaseProvider


@dataclass
class TTSRequest:
    text: str
    voice_id: str = ""
    speed: float = 1.0
    pitch: float = 1.0
    output_format: str = "mp3"
    language: str = "zh-CN"
    # When True, provider should use ICL resource_id instead of standard resource
    use_icl: bool = False


@dataclass
class TTSResponse:
    file_path: Path = field(default_factory=lambda: Path(""))
    duration: float = 0.0
    sample_rate: int = 0
    model_used: str = ""


class TTSProvider(BaseProvider):
    """Interface for text-to-speech providers."""

    async def synthesize(self, request: TTSRequest,
                         output_path: Path = Path("")) -> TTSResponse:
        """Convert text to speech audio file."""
        raise NotImplementedError

    async def list_voices(self) -> list[dict]:
        """List available voices with metadata."""
        return []

    async def synthesize_script(self, script: str, voice_id: str,
                                 output_path: Path,
                                 use_icl: bool = False) -> TTSResponse:
        """Synthesize a full oral broadcast script."""
        return await self.synthesize(
            TTSRequest(
                text=script,
                voice_id=voice_id,
                use_icl=use_icl,
            ),
            output_path=output_path,
        )
