"""字幕每行字数要随字号变化,否则字号一大就顶出画面。"""

import pytest

from app.video.subtitle_renderer import chars_per_line

PORTRAIT_WIDTH = 1080


def test_bigger_font_means_fewer_chars_per_line():
    sizes = [38, 54, 80, 120, 160]
    counts = [chars_per_line(s, PORTRAIT_WIDTH) for s in sizes]

    assert counts == sorted(counts, reverse=True)
    assert len(set(counts)) == len(counts)  # 每档都真的变了


@pytest.mark.parametrize("font_size", [20, 38, 54, 80, 120, 160])
def test_a_full_line_never_exceeds_the_frame(font_size):
    # 一行字排满时的像素宽度不能超过画面(中文按字号等宽估算)
    assert chars_per_line(font_size, PORTRAIT_WIDTH) * font_size <= PORTRAIT_WIDTH


def test_the_old_hardcoded_20_would_have_overflowed():
    # 原来写死 20 字:字号 54 时 20×54=1080 已经铺满整幅竖屏,再大就溢出
    assert 20 * 54 >= PORTRAIT_WIDTH
    assert chars_per_line(54, PORTRAIT_WIDTH) < 20


def test_always_leaves_room_for_at_least_a_few_chars():
    # 字号大到离谱时也不能返回 0,否则切行会死循环
    assert chars_per_line(9999, PORTRAIT_WIDTH) >= 4
    assert chars_per_line(0, PORTRAIT_WIDTH) >= 4
