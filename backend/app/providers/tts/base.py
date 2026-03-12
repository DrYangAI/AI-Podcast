"""Text-to-speech provider interface."""

import asyncio
import logging
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from ..base import BaseProvider

logger = logging.getLogger(__name__)


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
                                 use_icl: bool = False,
                                 max_chunk_chars: int | None = None) -> TTSResponse:
        """Synthesize a full oral broadcast script.

        For long texts, splits into chunks and synthesizes each separately
        to maintain voice consistency (especially important for ICL/voice cloning).
        """
        from ...utils.text_splitter import split_text_for_tts

        max_chars = max_chunk_chars or (500 if use_icl else 2000)
        chunks = split_text_for_tts(script, max_chars)

        if len(chunks) <= 1:
            # Short text — single synthesis call (unchanged behavior)
            return await self.synthesize(
                TTSRequest(text=script, voice_id=voice_id, use_icl=use_icl),
                output_path=output_path,
            )

        # Multiple chunks — synthesize each, then concatenate
        logger.info("Splitting TTS into %d chunks (max_chars=%d, use_icl=%s)",
                     len(chunks), max_chars, use_icl)

        temp_dir = output_path.parent / f"_tts_chunks_{uuid.uuid4().hex[:8]}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        chunk_paths: list[Path] = []

        try:
            for i, chunk_text in enumerate(chunks):
                chunk_path = temp_dir / f"chunk_{i:03d}.mp3"
                logger.info("  Chunk %d/%d: %d chars", i + 1, len(chunks), len(chunk_text))
                await self.synthesize(
                    TTSRequest(text=chunk_text, voice_id=voice_id, use_icl=use_icl),
                    output_path=chunk_path,
                )
                chunk_paths.append(chunk_path)

            # Concatenate with ffmpeg -c copy (stream copy, no re-encoding)
            duration = await self._concat_audio(chunk_paths, output_path)

            return TTSResponse(
                file_path=output_path,
                duration=duration,
                sample_rate=24000,
                model_used="chunked",
            )
        finally:
            # Clean up temp files
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)

    @staticmethod
    async def _concat_audio(chunk_paths: list[Path], output_path: Path) -> float:
        """Concatenate MP3 audio files using ffmpeg concat demuxer."""
        concat_list = output_path.parent / f"_concat_{uuid.uuid4().hex[:8]}.txt"
        try:
            # Write concat file list
            with open(concat_list, "w") as f:
                for p in chunk_paths:
                    # Escape single quotes in path for ffmpeg
                    safe = str(p).replace("'", "'\\''")
                    f.write(f"file '{safe}'\n")

            # Run ffmpeg concat
            process = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", str(concat_list), "-c", "copy", str(output_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await process.communicate()
            if process.returncode != 0:
                raise RuntimeError(f"ffmpeg concat failed: {stderr.decode()[:500]}")

            # Get duration via ffprobe
            probe = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "csv=p=0", str(output_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await probe.communicate()
            duration = float(stdout.decode().strip()) if stdout.decode().strip() else 0.0
            return duration
        finally:
            if concat_list.exists():
                concat_list.unlink()
