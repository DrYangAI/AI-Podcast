from app.services.audio_service import chunk_segment_index, chunks_align_with_segments


def _chunks(with_intro=False, with_outro=False, body=3):
    chunks = []
    if with_intro:
        chunks.append({"text": "片头", "type": "intro"})
    chunks.extend({"text": f"第{i}段"} for i in range(body))
    if with_outro:
        chunks.append({"text": "片尾", "type": "outro"})
    for i, c in enumerate(chunks):
        c["index"] = i
    return chunks


def test_segment_index_without_intro_is_identity():
    chunks = _chunks()
    assert [chunk_segment_index(chunks, i) for i in range(3)] == [0, 1, 2]


def test_intro_shifts_segment_index_by_one():
    chunks = _chunks(with_intro=True)
    assert chunk_segment_index(chunks, 0) is None
    assert [chunk_segment_index(chunks, i) for i in range(1, 4)] == [0, 1, 2]


def test_outro_maps_to_no_segment():
    chunks = _chunks(with_intro=True, with_outro=True)
    assert chunk_segment_index(chunks, 4) is None
    assert chunk_segment_index(chunks, 3) == 2


def test_alignment_requires_one_chunk_per_segment():
    segments = [object()] * 3
    assert chunks_align_with_segments(_chunks(), segments) is True
    assert chunks_align_with_segments(_chunks(with_intro=True, with_outro=True), segments) is True
    # 旧的"整篇按字数切块"模式:块数和段落数对不上,不能按下标改段落文字
    assert chunks_align_with_segments(_chunks(body=7), segments) is False
    assert chunks_align_with_segments(_chunks(), []) is False
