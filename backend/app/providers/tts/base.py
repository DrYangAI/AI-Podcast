"""Text-to-speech provider interface."""

import asyncio
import json
import logging
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
        Chunk files are persisted for manual retry.
        """
        from ...utils.text_splitter import split_text_for_tts

        max_chars = max_chunk_chars or (500 if use_icl else 2000)
        chunks = split_text_for_tts(script, max_chars)

        if len(chunks) <= 1:
            # Short text — single synthesis call (unchanged behavior)
            resp = await self.synthesize(
                TTSRequest(text=script, voice_id=voice_id, use_icl=use_icl),
                output_path=output_path,
            )
            # Still save chunks.json for consistency (1 chunk)
            chunks_dir = output_path.parent / "chunks"
            chunks_dir.mkdir(parents=True, exist_ok=True)
            single_chunk_path = chunks_dir / "chunk_000.mp3"
            shutil.copy2(str(output_path), str(single_chunk_path))
            dur = resp.duration or await self._probe_duration(output_path)
            speed = len(script) / dur if dur > 0 else 0.0
            self._save_chunks_json(chunks_dir, [{
                "index": 0, "text": script,
                "file": "chunk_000.mp3", "duration": dur,
                "speed": speed, "chars": len(script),
            }], voice_id, use_icl)
            return resp

        # Multiple chunks — synthesize each, then concatenate
        logger.info("Splitting TTS into %d chunks (max_chars=%d, use_icl=%s)",
                     len(chunks), max_chars, use_icl)

        max_retries = 2 if use_icl else 0  # ICL 模式启用语速一致性重试
        speed_tolerance = 0.35  # 语速偏差容忍度

        # Persistent chunk directory (not cleaned up after synthesis)
        chunks_dir = output_path.parent / "chunks"
        if chunks_dir.exists():
            shutil.rmtree(chunks_dir)  # Clear old chunks on full re-synthesis
        chunks_dir.mkdir(parents=True, exist_ok=True)

        chunk_paths: list[Path] = []
        chunk_speeds: list[float] = []
        chunk_durations: list[float] = []

        for i, chunk_text in enumerate(chunks):
            chunk_path = chunks_dir / f"chunk_{i:03d}.mp3"
            logger.info("  Chunk %d/%d: %d chars", i + 1, len(chunks), len(chunk_text))

            best_path = chunk_path
            best_speed = 0.0
            best_dur = 0.0

            for attempt in range(max_retries + 1):
                attempt_path = (chunks_dir / f"chunk_{i:03d}_try{attempt}.mp3"
                                if attempt > 0 else chunk_path)
                await self.synthesize(
                    TTSRequest(text=chunk_text, voice_id=voice_id, use_icl=use_icl),
                    output_path=attempt_path,
                )
                dur = await self._probe_duration(attempt_path)
                speed = len(chunk_text) / dur if dur > 0 else 0.0

                if attempt == 0:
                    best_path = attempt_path
                    best_speed = speed
                    best_dur = dur
                    if len(chunk_speeds) < 2:
                        break
                    median_speed = sorted(chunk_speeds)[len(chunk_speeds) // 2]
                    deviation = abs(speed - median_speed) / median_speed if median_speed > 0 else 0
                    if deviation <= speed_tolerance:
                        break
                    logger.warning(
                        "  Chunk %d speed %.1f chars/s deviates %.0f%% from median %.1f, retrying...",
                        i, speed, deviation * 100, median_speed)
                else:
                    median_speed = sorted(chunk_speeds)[len(chunk_speeds) // 2]
                    if abs(speed - median_speed) < abs(best_speed - median_speed):
                        if best_path != chunk_path:
                            best_path.unlink(missing_ok=True)
                        best_path = attempt_path
                        best_speed = speed
                        best_dur = dur
                        logger.info("  Retry %d better: %.1f chars/s (median %.1f)",
                                    attempt, speed, median_speed)
                    else:
                        attempt_path.unlink(missing_ok=True)
                        logger.info("  Retry %d not better: %.1f chars/s, keeping %.1f",
                                    attempt, speed, best_speed)
                    deviation = abs(best_speed - median_speed) / median_speed if median_speed > 0 else 0
                    if deviation <= speed_tolerance:
                        break

            # Rename best attempt to canonical path if needed
            if best_path != chunk_path:
                best_path.rename(chunk_path)

            chunk_paths.append(chunk_path)
            chunk_speeds.append(best_speed)
            chunk_durations.append(best_dur)

        logger.info("  Chunk speeds (chars/s): %s",
                    ", ".join(f"{s:.1f}" for s in chunk_speeds))

        # Save chunks.json metadata
        chunks_meta = []
        for i, chunk_text in enumerate(chunks):
            chunks_meta.append({
                "index": i,
                "text": chunk_text,
                "file": f"chunk_{i:03d}.mp3",
                "duration": chunk_durations[i],
                "speed": chunk_speeds[i],
                "chars": len(chunk_text),
            })
        self._save_chunks_json(chunks_dir, chunks_meta, voice_id, use_icl)

        # Concatenate all chunks。本地 VoxCPM 走小分块抗漂移,块间补一小段静音
        # 补齐句间停顿;其它 provider(豆包等)保持无缝拼接。
        gap = 0.0
        if getattr(self, "metadata", None) is not None and self.metadata.key == "local_voxcpm":
            from ...config import get_settings
            gap = get_settings().tts.local_voxcpm_chunk_gap_seconds
        duration = await self._concat_audio(chunk_paths, output_path, gap_seconds=gap)

        return TTSResponse(
            file_path=output_path,
            duration=duration,
            sample_rate=24000,
            model_used="chunked",
        )

    @staticmethod
    def _save_chunks_json(chunks_dir: Path, chunks: list[dict],
                          voice_id: str, use_icl: bool,
                          voice_display: str = ""):
        """Write chunks.json metadata to the chunks directory."""
        meta = {
            "chunks": chunks,
            "voice_id": voice_id,
            "voice_display": voice_display or voice_id,
            "use_icl": use_icl,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        (chunks_dir / "chunks.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @staticmethod
    def load_chunks_json(chunks_dir: Path) -> dict | None:
        """Read chunks.json from a chunks directory. Returns None if not found."""
        meta_path = chunks_dir / "chunks.json"
        if not meta_path.exists():
            return None
        return json.loads(meta_path.read_text(encoding="utf-8"))

    @staticmethod
    async def _probe_duration(file_path: Path) -> float:
        """Get audio duration in seconds via ffprobe."""
        probe = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "csv=p=0", str(file_path.resolve()),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await probe.communicate()
        try:
            return float(stdout.decode().strip())
        except (ValueError, AttributeError):
            return 0.0

    @staticmethod
    async def _probe_sample_rate(file_path: Path) -> int:
        """Get audio sample rate via ffprobe (fallback 16000)."""
        probe = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=sample_rate", "-of", "csv=p=0",
            str(file_path.resolve()),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await probe.communicate()
        try:
            return int(stdout.decode().strip())
        except (ValueError, AttributeError):
            return 16000

    @staticmethod
    async def _concat_audio(chunk_paths: list[Path], output_path: Path,
                            gap_seconds: float = 0.0) -> float:
        """Concatenate MP3 audio files using ffmpeg concat demuxer.

        gap_seconds>0 时在相邻块之间插入等长静音(与首块同采样率),用于本地
        VoxCPM 小分块拼接时补齐句间停顿(避免相邻句子直接贴在一起)。
        """
        concat_list = (output_path.parent / f"_concat_{uuid.uuid4().hex[:8]}.txt").resolve()
        silence_path: Path | None = None
        files_to_concat: list[Path] = list(chunk_paths)
        try:
            if gap_seconds > 0 and len(chunk_paths) > 1:
                sr = await TTSProvider._probe_sample_rate(chunk_paths[0])
                silence_path = (output_path.parent / f"_gap_{uuid.uuid4().hex[:8]}.mp3").resolve()
                sp = await asyncio.create_subprocess_exec(
                    "ffmpeg", "-y", "-f", "lavfi",
                    "-i", f"anullsrc=r={sr}:cl=mono", "-t", f"{gap_seconds}",
                    "-c:a", "libmp3lame", "-q:a", "2", str(silence_path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await sp.communicate()
                if sp.returncode == 0 and silence_path.exists():
                    interleaved: list[Path] = []
                    for i, p in enumerate(chunk_paths):
                        if i > 0:
                            interleaved.append(silence_path)
                        interleaved.append(p)
                    files_to_concat = interleaved
                else:
                    silence_path = None  # 静音生成失败则退回无缝拼接

            # Write concat file list
            with open(concat_list, "w") as f:
                for p in files_to_concat:
                    # Use absolute path to avoid ffmpeg resolving relative to list file
                    safe = str(p.resolve()).replace("'", "'\\''")
                    f.write(f"file '{safe}'\n")

            # Run ffmpeg concat (re-encode to ensure reliable MP3 concatenation)
            process = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", str(concat_list),
                "-c:a", "libmp3lame", "-q:a", "2",
                str(output_path.resolve()),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await process.communicate()
            if process.returncode != 0:
                stderr_text = stderr.decode(errors="replace")
                # Filter out ffmpeg banner lines, keep actual error info
                error_lines = [
                    l for l in stderr_text.splitlines()
                    if l.strip() and not l.startswith("  ")
                    and "Copyright" not in l and "configuration:" not in l
                    and "built with" not in l
                ]
                raise RuntimeError(
                    f"ffmpeg concat failed: {'  '.join(error_lines[-10:])}"
                )

            # Get duration via ffprobe
            duration = await TTSProvider._probe_duration(output_path)
            return duration
        finally:
            if concat_list.exists():
                concat_list.unlink()
            if silence_path and silence_path.exists():
                silence_path.unlink()
