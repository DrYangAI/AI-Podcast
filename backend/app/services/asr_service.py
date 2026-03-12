"""ASR service - use faster-whisper to transcribe audio for precise subtitle timing."""

import asyncio
import logging
import threading
from pathlib import Path

from ..config import get_settings
from ..video.subtitle_renderer import SubtitleEntry, SubtitleRenderer

logger = logging.getLogger(__name__)

# Global model cache — loaded once on first use
_model = None
_model_lock = threading.Lock()


def _get_or_load_model():
    """Load the Whisper model (synchronous, called via to_thread)."""
    global _model
    with _model_lock:
        if _model is not None:
            return _model

        from faster_whisper import WhisperModel

        settings = get_settings()
        model_size = settings.asr.model_size
        device = settings.asr.device
        compute_type = settings.asr.compute_type

        # "auto" → use cpu on macOS (no CUDA)
        if device == "auto":
            device = "cpu"

        logger.info("Loading Whisper model: size=%s, device=%s, compute_type=%s",
                    model_size, device, compute_type)
        _model = WhisperModel(model_size, device=device, compute_type=compute_type)
        logger.info("Whisper model loaded successfully")
        return _model


def _transcribe_sync(audio_path: Path, max_chars_per_line: int) -> list[SubtitleEntry]:
    """Run Whisper transcription synchronously.

    Returns SubtitleEntry list with precise timestamps from ASR.
    """
    model = _get_or_load_model()

    segments_iter, info = model.transcribe(
        str(audio_path),
        language="zh",
        vad_filter=True,
        word_timestamps=True,
    )
    logger.info("ASR detected language: %s (prob=%.2f), duration=%.1fs",
                info.language, info.language_probability, info.duration)

    entries = []
    index = 1

    for segment in segments_iter:
        if not segment.words:
            # No word-level timestamps, use segment-level
            text = segment.text.strip()
            if not text:
                continue
            # Split into lines by max_chars_per_line
            lines = _split_to_lines(text, max_chars_per_line)
            seg_duration = segment.end - segment.start
            line_duration = seg_duration / len(lines)
            for i, line in enumerate(lines):
                entries.append(SubtitleEntry(
                    index=index,
                    start_time=segment.start + i * line_duration,
                    end_time=segment.start + (i + 1) * line_duration,
                    text=line,
                ))
                index += 1
        else:
            # Use word-level timestamps for maximum precision
            current_line = ""
            line_start = segment.words[0].start

            for word in segment.words:
                candidate = current_line + word.word
                if len(candidate.strip()) > max_chars_per_line and current_line:
                    # Flush current line
                    entries.append(SubtitleEntry(
                        index=index,
                        start_time=line_start,
                        end_time=word.start,
                        text=current_line.strip(),
                    ))
                    index += 1
                    current_line = word.word
                    line_start = word.start
                else:
                    current_line = candidate

            # Flush remaining
            if current_line.strip():
                entries.append(SubtitleEntry(
                    index=index,
                    start_time=line_start,
                    end_time=segment.words[-1].end,
                    text=current_line.strip(),
                ))
                index += 1

    logger.info("ASR generated %d subtitle entries", len(entries))
    return entries


def _split_to_lines(text: str, max_chars: int) -> list[str]:
    """Split text into lines of at most max_chars characters."""
    text = text.strip()
    if not text:
        return [""]
    lines = []
    while text:
        lines.append(text[:max_chars])
        text = text[max_chars:]
    return lines


async def transcribe_and_generate_srt(
    audio_path: Path,
    output_path: Path,
    max_chars_per_line: int = 20,
) -> Path | None:
    """Transcribe audio with Whisper and generate precise SRT file.

    Returns the SRT path on success, None on failure (caller should fallback).
    """
    settings = get_settings()
    if not settings.asr.enabled:
        logger.info("ASR disabled in config, skipping")
        return None

    try:
        entries = await asyncio.to_thread(
            _transcribe_sync, audio_path, max_chars_per_line
        )
        if not entries:
            logger.warning("ASR returned no entries for %s", audio_path)
            return None

        renderer = SubtitleRenderer()
        renderer.generate_srt_from_entries(entries, output_path)
        logger.info("ASR SRT written to %s (%d entries)", output_path, len(entries))
        return output_path

    except Exception:
        logger.exception("ASR transcription failed for %s, will fallback", audio_path)
        return None
