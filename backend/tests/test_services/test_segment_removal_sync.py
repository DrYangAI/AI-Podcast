"""删段落时,口播稿 / 音频分段 / 段落音频要一起跟着删。"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import AudioAsset, Script, Segment
from app.providers.tts.base import TTSProvider
from app.services import audio_service

PROJECT_ID = "p1"


@pytest.fixture
def storage(tmp_path, monkeypatch):
    """把 storage.base_dir 指到临时目录,并跳过真正的 ffmpeg 拼接。"""
    monkeypatch.setattr(
        audio_service, "get_settings",
        lambda: SimpleNamespace(storage=SimpleNamespace(base_dir=str(tmp_path))),
    )

    concat_calls = []

    async def fake_concat(chunk_paths, output_path, gap_seconds=0.0):
        concat_calls.append([p.name for p in chunk_paths])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("merged")
        return 12.5

    monkeypatch.setattr(TTSProvider, "_concat_audio", staticmethod(fake_concat))
    return SimpleNamespace(root=tmp_path, concat_calls=concat_calls)


def write_audio_tree(root: Path, chunks: list[dict], segment_orders: list[int]) -> None:
    """铺出一份合成完毕的音频:chunks.json + 分段 mp3 + 段落音频目录。"""
    audio_dir = root / "audio" / PROJECT_ID
    chunks_dir = audio_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    for chunk in chunks:
        (chunks_dir / chunk["file"]).write_text(chunk["text"])
    (chunks_dir / "chunks.json").write_text(
        json.dumps({"chunks": chunks, "voice_id": "v1", "use_icl": False,
                    "voice_display": "测试声音"}, ensure_ascii=False),
        encoding="utf-8",
    )
    for order in segment_orders:
        seg_dir = audio_dir / "segments" / f"seg_{order:03d}"
        seg_dir.mkdir(parents=True, exist_ok=True)
        (seg_dir / "speech.mp3").write_text(f"seg{order}")


def body_chunks(texts: list[str], with_intro: bool = False) -> list[dict]:
    entries = []
    if with_intro:
        entries.append({"text": "片头", "type": "intro"})
    entries.extend({"text": t} for t in texts)
    for i, entry in enumerate(entries):
        entry["index"] = i
        entry["file"] = f"chunk_{i:03d}.mp3"
    return entries


@pytest_asyncio.fixture
async def db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session = async_sessionmaker(engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        await session.close()
        await engine.dispose()


async def seed(db, script_texts: list[str | None], script_content: str) -> None:
    for order, text in enumerate(script_texts):
        db.add(Segment(
            id=f"s{order}", article_id="a1", project_id=PROJECT_ID,
            segment_order=order, content=f"原文{order}", script_text=text,
            audio_file=None if text is None else
            f"{Path('/tmp')}/audio/{PROJECT_ID}/segments/seg_{order:03d}/speech.mp3",
        ))
    db.add(Script(id="sc1", project_id=PROJECT_ID, content=script_content))
    db.add(AudioAsset(id="au1", project_id=PROJECT_ID, file_path="old.mp3",
                      duration=99.0, status="completed"))
    await db.flush()


async def delete_segment(db, removed_order: int) -> None:
    """复现接口里的删除+重排序,好让 sync 看到删除后的状态。"""
    result = await db.execute(
        select(Segment).where(Segment.project_id == PROJECT_ID,
                              Segment.segment_order == removed_order)
    )
    await db.delete(result.scalar_one())
    await db.flush()

    later = await db.execute(
        select(Segment).where(Segment.project_id == PROJECT_ID,
                              Segment.segment_order > removed_order)
        .order_by(Segment.segment_order)
    )
    for seg in later.scalars().all():
        seg.segment_order -= 1
        await db.flush()


def read_chunks(root: Path) -> list[dict]:
    meta = json.loads((root / "audio" / PROJECT_ID / "chunks" / "chunks.json").read_text())
    return meta["chunks"]


@pytest.mark.asyncio
async def test_removes_paragraph_from_script_and_its_audio_chunk(db, storage):
    await seed(db, ["甲", "乙", "丙"], "甲\n\n乙\n\n丙")
    write_audio_tree(storage.root, body_chunks(["甲", "乙", "丙"], with_intro=True),
                     segment_orders=[0, 1, 2])

    await delete_segment(db, 1)
    result = await audio_service.sync_after_segment_removed(db, PROJECT_ID, 1, 3)

    assert result == {"script_synced": True, "chunks_synced": True, "audio_duration": 12.5}

    script = (await db.execute(select(Script))).scalar_one()
    assert script.content == "甲\n\n丙"

    chunks = read_chunks(storage.root)
    assert [c["text"] for c in chunks] == ["片头", "甲", "丙"]
    # 编号和文件名重新对齐,否则按下标点"重新生成"会念错段
    assert [c["index"] for c in chunks] == [0, 1, 2]
    assert [c["file"] for c in chunks] == [f"chunk_{i:03d}.mp3" for i in range(3)]
    chunks_dir = storage.root / "audio" / PROJECT_ID / "chunks"
    assert (chunks_dir / "chunk_002.mp3").read_text() == "丙"
    assert not (chunks_dir / "chunk_003.mp3").exists()

    # 段落音频目录整体前移,seg_XXX 重新对上 segment_order
    seg_dir = storage.root / "audio" / PROJECT_ID / "segments"
    assert sorted(d.name for d in seg_dir.iterdir()) == ["seg_000", "seg_001"]
    assert (seg_dir / "seg_001" / "speech.mp3").read_text() == "seg2"

    segments = (await db.execute(
        select(Segment).order_by(Segment.segment_order))).scalars().all()
    assert [s.script_text for s in segments] == ["甲", "丙"]
    assert segments[1].audio_file == str(seg_dir / "seg_001" / "speech.mp3")

    # 整段语音按剩下的分段重拼,时长同步到 AudioAsset
    assert storage.concat_calls == [["chunk_000.mp3", "chunk_001.mp3", "chunk_002.mp3"]]
    audio = (await db.execute(select(AudioAsset))).scalar_one()
    assert audio.duration == 12.5


@pytest.mark.asyncio
async def test_last_segment_removal_drops_trailing_chunk(db, storage):
    await seed(db, ["甲", "乙"], "甲\n\n乙")
    write_audio_tree(storage.root, body_chunks(["甲", "乙"]), segment_orders=[0, 1])

    await delete_segment(db, 1)
    await audio_service.sync_after_segment_removed(db, PROJECT_ID, 1, 2)

    assert [c["text"] for c in read_chunks(storage.root)] == ["甲"]
    script = (await db.execute(select(Script))).scalar_one()
    assert script.content == "甲"


@pytest.mark.asyncio
async def test_script_without_per_segment_text_drops_paragraph_by_position(db, storage):
    # 整篇模式:段落没有各自的口播稿,只能按空行切开删对应那一段
    await seed(db, [None, None, None], "甲\n\n乙\n\n丙")
    write_audio_tree(storage.root, body_chunks(["甲", "乙", "丙"]), segment_orders=[0, 1, 2])

    await delete_segment(db, 0)
    result = await audio_service.sync_after_segment_removed(db, PROJECT_ID, 0, 3)

    assert result["script_synced"] is True
    script = (await db.execute(select(Script))).scalar_one()
    assert script.content == "乙\n\n丙"


@pytest.mark.asyncio
async def test_script_left_alone_when_paragraph_count_disagrees(db, storage):
    await seed(db, [None, None, None], "甲\n\n乙")

    await delete_segment(db, 0)
    result = await audio_service.sync_after_segment_removed(db, PROJECT_ID, 0, 3)

    assert result["script_synced"] is False
    script = (await db.execute(select(Script))).scalar_one()
    assert script.content == "甲\n\n乙"


@pytest.mark.asyncio
async def test_misaligned_chunks_are_left_untouched(db, storage):
    # 旧的"整篇按字数切块":分段和段落对不上,无从判断该删哪一段
    await seed(db, ["甲", "乙", "丙"], "甲\n\n乙\n\n丙")
    write_audio_tree(storage.root, body_chunks(["甲乙", "丙"]), segment_orders=[0, 1, 2])

    await delete_segment(db, 1)
    result = await audio_service.sync_after_segment_removed(db, PROJECT_ID, 1, 3)

    assert result == {"script_synced": True, "chunks_synced": False, "audio_duration": None}
    assert [c["text"] for c in read_chunks(storage.root)] == ["甲乙", "丙"]
    assert storage.concat_calls == []

    # 说了"没动音频"就一个字节都不能动:段落音频目录必须原封不动。
    # 判断该删哪一段之前就把目录删改掉的话,这条退路等于先毁了数据再说不敢动。
    seg_dir = storage.root / "audio" / PROJECT_ID / "segments"
    assert sorted(d.name for d in seg_dir.iterdir()) == ["seg_000", "seg_001", "seg_002"]
    assert (seg_dir / "seg_001" / "speech.mp3").read_text() == "seg1"
    segments = (await db.execute(
        select(Segment).order_by(Segment.segment_order))).scalars().all()
    assert all(s.audio_file for s in segments)


@pytest.mark.asyncio
async def test_no_audio_yet_still_fixes_the_script(db, storage):
    await seed(db, ["甲", "乙"], "甲\n\n乙")

    await delete_segment(db, 0)
    result = await audio_service.sync_after_segment_removed(db, PROJECT_ID, 0, 2)

    assert result == {"script_synced": True, "chunks_synced": False, "audio_duration": None}
    script = (await db.execute(select(Script))).scalar_one()
    assert script.content == "乙"


@pytest.mark.asyncio
async def test_missing_chunk_file_skips_reconcatenation(db, storage):
    await seed(db, ["甲", "乙", "丙"], "甲\n\n乙\n\n丙")
    write_audio_tree(storage.root, body_chunks(["甲", "乙", "丙"]), segment_orders=[0, 1, 2])
    (storage.root / "audio" / PROJECT_ID / "chunks" / "chunk_000.mp3").unlink()

    await delete_segment(db, 2)
    result = await audio_service.sync_after_segment_removed(db, PROJECT_ID, 2, 3)

    # 分段照删,但不拿缺东西的分段拼出一段残缺成品
    assert result["chunks_synced"] is True
    assert result["audio_duration"] is None
    assert storage.concat_calls == []
    audio = (await db.execute(select(AudioAsset))).scalar_one()
    assert audio.duration == 99.0


@pytest.mark.asyncio
async def test_no_script_yet_reports_nothing_to_sync(db, storage):
    db.add(Segment(id="s0", article_id="a1", project_id=PROJECT_ID,
                   segment_order=0, content="原文0"))
    db.add(Segment(id="s1", article_id="a1", project_id=PROJECT_ID,
                   segment_order=1, content="原文1"))
    await db.flush()

    await delete_segment(db, 0)
    result = await audio_service.sync_after_segment_removed(db, PROJECT_ID, 0, 2)

    # 还没生成口播稿:没有对不上的东西,不该报警告
    assert result["script_synced"] is None
