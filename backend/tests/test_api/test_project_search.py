"""项目列表的关键词搜索:标题和话题都要搜,LIKE 通配符不能被用户输入撬开。"""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.projects import _escape_like, list_projects
from app.database import Base
from app.models import Project

FIXTURES = [
    ("p1", "骨龄陡增，一半以上是假象！", "骨龄评估的常见误区"),
    ("p2", "看懂过敏原报告_家长版", "过敏原 sIgE 检测解读"),
    ("p3", "补钙会导致骨龄提前吗", "家长常问的补钙问题"),
    ("p4", "维生素D缺乏", "血清 25 羟维生素 D 达到 100% 才算够吗"),
]


@pytest_asyncio.fixture
async def db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session = async_sessionmaker(engine, expire_on_commit=False)()
    for pid, title, topic in FIXTURES:
        session.add(Project(id=pid, title=title, topic=topic))
    await session.flush()
    try:
        yield session
    finally:
        await session.close()
        await engine.dispose()


async def search(db, term: str | None) -> list[str]:
    page = await list_projects(page=1, page_size=20, status=None, search=term, db=db)
    return sorted(p.title for p in page.items)


@pytest.mark.asyncio
async def test_no_search_returns_everything(db):
    assert len(await search(db, None)) == 4
    assert len(await search(db, "   ")) == 4


@pytest.mark.asyncio
async def test_matches_title_substring(db):
    assert await search(db, "骨龄") == ["补钙会导致骨龄提前吗", "骨龄陡增，一半以上是假象！"]


@pytest.mark.asyncio
async def test_matches_topic_when_title_does_not(db):
    # 只有话题里有"检测",标题里没有
    assert await search(db, "检测") == ["看懂过敏原报告_家长版"]


@pytest.mark.asyncio
async def test_percent_is_matched_literally(db):
    # 没转义的话 % 会匹配所有项目
    assert await search(db, "%") == ["维生素D缺乏"]


@pytest.mark.asyncio
async def test_underscore_is_matched_literally(db):
    # 没转义的话 _ 会匹配任意单个字符,四个项目全中
    assert await search(db, "_") == ["看懂过敏原报告_家长版"]


@pytest.mark.asyncio
async def test_total_reflects_the_filtered_count(db):
    page = await list_projects(page=1, page_size=20, status=None, search="骨龄", db=db)
    assert page.total == 2


def test_escape_like_escapes_backslash_first():
    # 先转义反斜杠,否则后面补上的转义符自己又会被转义一遍
    assert _escape_like(r"a\b") == r"a\\b"
    assert _escape_like("50%_off") == r"50\%\_off"
