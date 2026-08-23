"""字幕文字以口播稿为准,ASR 只提供时间轴。

Whisper 会把"骨龄"听成"古灵"这类同音词,成片字幕不该带上这种错误。
"""

from app.services.asr_service import (
    _AsrSegment,
    _AsrWord,
    _entries_from_reference,
    _line_ranges,
)


def asr(*words: tuple[str, float, float]) -> list[_AsrSegment]:
    """按 (文字, 起, 止) 造一段带逐词时间戳的识别结果。"""
    return [_AsrSegment(
        text="".join(w for w, _, _ in words),
        start=words[0][1],
        end=words[-1][2],
        words=[_AsrWord(text=w, start=s, end=e) for w, s, e in words],
    )]


def test_homophone_errors_are_replaced_by_the_script():
    # ASR 把"骨龄"听成了"古灵",两处都要按口播稿纠回来
    segments = asr(("大家", 0.0, 0.6), ("对", 0.6, 0.8), ("古灵", 0.8, 1.4),
                   ("偏大的", 1.4, 2.0), ("焦虑", 2.0, 2.6))
    entries = _entries_from_reference(
        segments, ["大家对骨龄偏大的焦虑"], max_chars_per_line=20
    )

    assert [e.text for e in entries] == ["大家对骨龄偏大的焦虑"]
    assert "古灵" not in entries[0].text


def test_timing_comes_from_the_asr_result():
    segments = asr(("大家", 0.0, 0.6), ("对", 0.6, 0.8), ("古灵", 0.8, 1.4))
    entries = _entries_from_reference(
        segments, ["大家对骨龄"], max_chars_per_line=20
    )

    # "骨龄"没对上"古灵",但要拿到它对应的那段音频时间(0.8→1.4),
    # 而不是沿用前一个字的 0.8 —— 否则字幕会在音频还在念的时候消失
    assert entries[0].start_time == 0.0
    assert entries[0].end_time == 1.4


def test_punctuation_in_the_script_is_kept():
    # ASR 一般不给标点,口播稿的标点要照常显示,只是不参与对齐
    segments = asr(("骨龄", 0.0, 0.6), ("不是", 0.6, 1.0), ("匀速的", 1.0, 1.6))
    entries = _entries_from_reference(
        segments, ["骨龄，不是匀速的。"], max_chars_per_line=20
    )

    assert entries[0].text == "骨龄，不是匀速的。"


def test_lines_never_span_two_segments():
    segments = asr(("第一段", 0.0, 1.0), ("第二段", 1.0, 2.0))
    entries = _entries_from_reference(
        segments, ["第一段", "第二段"], max_chars_per_line=20
    )

    assert [e.text for e in entries] == ["第一段", "第二段"]
    assert entries[0].end_time <= entries[1].start_time


def test_entries_do_not_overlap_in_time():
    segments = asr(("一二三四五", 0.0, 1.0), ("六七八九十", 1.0, 2.0))
    entries = _entries_from_reference(
        segments, ["一二三四五六七八九十"], max_chars_per_line=5
    )

    for a, b in zip(entries, entries[1:]):
        assert a.end_time <= b.start_time
        assert a.end_time > a.start_time


def test_words_asr_missed_still_get_a_time():
    # ASR 把"偏大"漏听了,口播稿里的这两个字要从相邻锚点之间借到时间
    segments = asr(("大家对", 0.0, 0.9), ("骨龄", 0.9, 1.5), ("的", 1.5, 1.8),
                   ("焦虑", 1.8, 2.4), ("来源于", 2.4, 3.0), ("认知偏差", 3.0, 3.9))
    entries = _entries_from_reference(
        segments, ["大家对骨龄偏大的焦虑来源于认知偏差"], max_chars_per_line=30
    )

    assert entries[0].text == "大家对骨龄偏大的焦虑来源于认知偏差"
    assert entries[0].start_time == 0.0
    assert entries[0].end_time == 3.9


def test_falls_back_when_script_does_not_match_the_audio():
    # 口播稿改过但音频没重新生成:硬套只会得到驴唇不对马嘴的字幕,应退回纯 ASR
    segments = asr(("大家", 0.0, 0.6), ("对", 0.6, 0.8), ("古灵", 0.8, 1.4))
    assert _entries_from_reference(
        segments, ["完全不相干的另一段稿子内容"], max_chars_per_line=20
    ) is None


def test_line_ranges_break_at_punctuation():
    text = "骨龄不是匀速的，它会突然冲刺。"
    lines = [text[a:b] for a, b in _line_ranges(text, 10)]

    assert lines[0] == "骨龄不是匀速的，"
    assert "".join(lines) == text


def test_line_ranges_hard_split_when_no_punctuation():
    text = "一二三四五六七八九十"
    lines = [text[a:b] for a, b in _line_ranges(text, 4)]

    assert lines == ["一二三四", "五六七八", "九十"]


def test_line_never_starts_with_punctuation():
    # 窗口内没有标点只能硬切，但紧跟其后的句号要收进本行，
    # 否则下一行会以"。"开头
    text = "来源于对骨龄增长应该与年龄增长匹配的预期。我之前发过"
    lines = [text[a:b] for a, b in _line_ranges(text, 20)]

    assert lines[0] == "来源于对骨龄增长应该与年龄增长匹配的预期。"
    assert not any(l[0] in "，。、！？；：" for l in lines)
    assert "".join(lines) == text
