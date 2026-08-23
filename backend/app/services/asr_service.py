"""ASR service - use faster-whisper to transcribe audio for precise subtitle timing.

字幕文字以口播稿为准,ASR 只负责给出时间轴。Whisper 会把"骨龄"听成"古灵"这类
同音词,而口播稿正是 TTS 念出来的原文,没道理让识别错误进到成片字幕里。做法是
把识别结果和口播稿做字符级对齐(difflib),取 ASR 的时间、用口播稿的字。

没有口播稿可对(或对不上)时退回纯 ASR 文本,总比没有字幕好。
"""

import asyncio
import difflib
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path

from ..config import get_settings
from ..video.subtitle_renderer import SubtitleEntry, SubtitleRenderer

logger = logging.getLogger(__name__)

# 对齐命中率低于此值就认为口播稿和音频压根不是一回事(比如口播稿改了但音频没重生成),
# 这时用口播稿去套 ASR 的时间轴只会得到驴唇不对马嘴的字幕,不如退回纯 ASR。
_MIN_ALIGN_RATIO = 0.6

# Global model cache — loaded once on first use
_model = None
_model_lock = threading.Lock()


@dataclass
class _AsrWord:
    text: str
    start: float
    end: float


@dataclass
class _AsrSegment:
    text: str
    start: float
    end: float
    words: list[_AsrWord] = field(default_factory=list)


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


def _transcribe_sync(audio_path: Path) -> list[_AsrSegment]:
    """Run Whisper transcription synchronously, returning raw segments + word times."""
    model = _get_or_load_model()

    segments_iter, info = model.transcribe(
        str(audio_path),
        language="zh",
        vad_filter=True,
        word_timestamps=True,
    )
    logger.info("ASR detected language: %s (prob=%.2f), duration=%.1fs",
                info.language, info.language_probability, info.duration)

    segments = []
    for seg in segments_iter:
        words = [_AsrWord(text=w.word, start=w.start, end=w.end)
                 for w in (seg.words or [])]
        segments.append(_AsrSegment(text=seg.text, start=seg.start,
                                    end=seg.end, words=words))
    return segments


# ── 纯 ASR 字幕(没有口播稿可对时的退路)──────────────────────────────────

def _entries_from_asr(segments: list[_AsrSegment],
                      max_chars_per_line: int) -> list[SubtitleEntry]:
    """Build subtitle entries straight from the transcription."""
    entries: list[SubtitleEntry] = []
    index = 1

    for segment in segments:
        if not segment.words:
            # No word-level timestamps, use segment-level
            text = segment.text.strip()
            if not text:
                continue
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
                candidate = current_line + word.text
                if len(candidate.strip()) > max_chars_per_line and current_line:
                    entries.append(SubtitleEntry(
                        index=index,
                        start_time=line_start,
                        end_time=word.start,
                        text=current_line.strip(),
                    ))
                    index += 1
                    current_line = word.text
                    line_start = word.start
                else:
                    current_line = candidate

            if current_line.strip():
                entries.append(SubtitleEntry(
                    index=index,
                    start_time=line_start,
                    end_time=segment.words[-1].end,
                    text=current_line.strip(),
                ))
                index += 1

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


# ── 口播稿对齐(默认路径)────────────────────────────────────────────────

def _char_times(segments: list[_AsrSegment]) -> list[tuple[str, float, float]]:
    """把 ASR 结果摊平成逐字的 (字, 起, 止)。

    Whisper 中文的一个"词"通常是 1-3 个字,词内按字数均分时间即可,
    误差远小于一行字幕的时长。
    """
    out: list[tuple[str, float, float]] = []
    for seg in segments:
        units = ([(w.text, w.start, w.end) for w in seg.words]
                 if seg.words else [(seg.text, seg.start, seg.end)])
        for text, start, end in units:
            chars = [c for c in text if not c.isspace()]
            if not chars:
                continue
            step = max(end - start, 1e-3) / len(chars)
            for k, c in enumerate(chars):
                out.append((c, start + k * step, start + (k + 1) * step))
    return out


def _matchable(chars: list[str]) -> tuple[str, list[int]]:
    """取出参与对齐的字符(汉字/字母/数字),并记下它们在原序列中的下标。

    标点和空白不参与:ASR 的断句习惯和口播稿不一样,拿它们比对只会制造噪声。
    标点仍会照常显示,只是不参与匹配。
    """
    kept, index_map = [], []
    for i, ch in enumerate(chars):
        if ch.isalnum():
            kept.append(ch)
            index_map.append(i)
    return "".join(kept), index_map


def _fill_gaps(times: list[tuple[float, float] | None],
               char_times: list[tuple[str, float, float]],
               asr_map: list[int], ref_map: list[int],
               anchor_by_ref: dict[int, int]) -> None:
    """给没对上的口播稿字符分配时间。

    两个锚点之间,ASR 那段音频对应的正是口播稿这段没对上的字(同音词、漏听
    都落在这里),所以把这段时间按字数均分下去。若简单沿用前一个字的时间,
    被替换掉的词会提前收尾 —— 比如"古灵"听错成"骨龄",字幕会在音频还在念
    的时候就消失。
    """
    n = len(ref_map)
    j = 0
    while j < n:
        if j in anchor_by_ref:
            j += 1
            continue
        run_start = j
        while j < n and j not in anchor_by_ref:
            j += 1
        prev_i = anchor_by_ref.get(run_start - 1)
        next_i = anchor_by_ref.get(j) if j < n else None
        start = char_times[asr_map[prev_i]][2] if prev_i is not None else char_times[0][1]
        end = char_times[asr_map[next_i]][1] if next_i is not None else char_times[-1][2]
        step = max(end - start, 0.0) / (j - run_start)
        for k, ref_norm_idx in enumerate(range(run_start, j)):
            times[ref_map[ref_norm_idx]] = (start + k * step, start + (k + 1) * step)


def _carry_punctuation(times: list[tuple[float, float] | None]) -> None:
    """标点没参与对齐,时间就近借用相邻的字。"""
    last: tuple[float, float] | None = None
    for i, t in enumerate(times):
        if t is not None:
            last = t
        elif last is not None:
            times[i] = last
    nxt: tuple[float, float] | None = None
    for i in range(len(times) - 1, -1, -1):
        if times[i] is not None:
            nxt = times[i]
        elif nxt is not None:
            times[i] = nxt


def _line_ranges(text: str, max_chars: int) -> list[tuple[int, int]]:
    """把一段文字切行,返回每行在原文中的下标区间。

    优先在标点处断句,断不动再按 max_chars 硬切,尽量不把句子切碎。
    """
    ranges: list[tuple[int, int]] = []
    start, n = 0, len(text)
    while start < n:
        while start < n and text[start].isspace():
            start += 1
        if start >= n:
            break
        end = min(start + max_chars, n)
        if end < n:
            # 往回找最近的标点当断点
            for i in range(end - 1, start, -1):
                if not text[i].isalnum() and not text[i].isspace():
                    end = i + 1
                    break
            # 断点后面紧跟的标点收进本行,否则下一行会以"。"开头。最多收 2 个
            # (句末通常就是 」。 或 …… 这种组合),不设上限的话一长串标点会把
            # 这一行撑得远超字号算出来的宽度。
            absorbed = 0
            while (end < n and absorbed < 2
                   and not text[end].isalnum() and not text[end].isspace()):
                end += 1
                absorbed += 1
        ranges.append((start, end))
        start = end
    return ranges


def _entries_from_reference(segments: list[_AsrSegment],
                            reference_texts: list[str],
                            max_chars_per_line: int) -> list[SubtitleEntry] | None:
    """用口播稿的文字 + ASR 的时间轴生成字幕。对不上时返回 None。"""
    char_times = _char_times(segments)
    if not char_times:
        return None

    asr_norm, asr_map = _matchable([c for c, _, _ in char_times])
    ref_full = "".join(reference_texts)
    ref_norm, ref_map = _matchable(list(ref_full))
    if not asr_norm or not ref_norm:
        return None

    matcher = difflib.SequenceMatcher(None, asr_norm, ref_norm, autojunk=False)
    blocks = matcher.get_matching_blocks()
    hit = sum(b.size for b in blocks)
    ratio = hit / len(ref_norm)
    if ratio < _MIN_ALIGN_RATIO:
        logger.warning("口播稿与音频对齐命中率仅 %.0f%%,退回纯 ASR 字幕"
                       "(口播稿改过但音频没重新生成?)", ratio * 100)
        return None

    # 口播稿每个字的时间:对上的直接取 ASR 的,没对上的按锚点之间的音频时长均分
    times: list[tuple[float, float] | None] = [None] * len(ref_full)
    anchor_by_ref: dict[int, int] = {}
    for b in blocks:
        for k in range(b.size):
            _, start, end = char_times[asr_map[b.a + k]]
            times[ref_map[b.b + k]] = (start, end)
            anchor_by_ref[b.b + k] = b.a + k
    _fill_gaps(times, char_times, asr_map, ref_map, anchor_by_ref)
    _carry_punctuation(times)

    entries: list[SubtitleEntry] = []
    index = 1
    prev_end = 0.0
    base = 0
    for text in reference_texts:
        for a, b_ in _line_ranges(text, max_chars_per_line):
            display = text[a:b_].strip()
            slot = [t for t in times[base + a:base + b_] if t is not None]
            if not display or not slot:
                continue
            start = max(slot[0][0], prev_end)
            end = max(slot[-1][1], start + 0.1)
            entries.append(SubtitleEntry(index=index, start_time=start,
                                         end_time=end, text=display))
            prev_end = end
            index += 1
        base += len(text)

    logger.info("字幕按口播稿生成:%d 行,对齐命中率 %.0f%%", len(entries), ratio * 100)
    return entries or None


async def transcribe_and_generate_srt(
    audio_path: Path,
    output_path: Path,
    max_chars_per_line: int = 20,
    reference_texts: list[str] | None = None,
) -> Path | None:
    """Transcribe audio with Whisper and generate a precise SRT file.

    ``reference_texts`` 是 TTS 实际念的口播稿(按播放顺序,片头/片尾也算一段)。
    传了就以它为字幕文字,ASR 只提供时间轴;不传或对不上则退回纯 ASR 文本。

    Returns the SRT path on success, None on failure (caller should fallback).
    """
    settings = get_settings()
    if not settings.asr.enabled:
        logger.info("ASR disabled in config, skipping")
        return None

    try:
        segments = await asyncio.to_thread(_transcribe_sync, audio_path)
        if not segments:
            logger.warning("ASR returned no segments for %s", audio_path)
            return None

        entries = None
        if reference_texts:
            entries = _entries_from_reference(
                segments, [t for t in reference_texts if t and t.strip()],
                max_chars_per_line,
            )
        if entries is None:
            entries = _entries_from_asr(segments, max_chars_per_line)
            logger.info("字幕使用 ASR 识别文本(%d 行)", len(entries))
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
