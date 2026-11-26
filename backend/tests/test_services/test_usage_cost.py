"""费用核算:价格查找 + 单位换算 + 汇总聚合。"""

import pytest

from app.services.usage_service import DEFAULT_PRICING, _price_lookup, cost_of


def test_price_lookup_exact_beats_wildcard():
    entries = [
        {"provider_type": "image", "provider_key": "doubao_seedream", "model_id": "", "unit": "image", "price": 0.20},
        {"provider_type": "image", "provider_key": "doubao_seedream", "model_id": "m-flash", "unit": "image", "price": 0.12},
    ]
    assert _price_lookup(entries, "image", "doubao_seedream", "m-flash", "image") == 0.12  # 精确优先
    assert _price_lookup(entries, "image", "doubao_seedream", "其它", "image") == 0.20     # 回退通配
    assert _price_lookup(entries, "image", "别的provider", "x", "image") == 0.0            # 找不到=0


def test_unit_conversion():
    e = DEFAULT_PRICING
    # 图片:元/张
    assert cost_of(e, "image", "doubao_seedream", "doubao-seedream-5-0-flash-260915", "image", 3) == pytest.approx(0.36)
    # TTS:元/万字 → 5000 字 = 0.5 万字
    assert cost_of(e, "tts", "doubao_tts", "", "char", 5000) == pytest.approx(0.5)  # 1元/万字
    # 本地 VoxCPM 免费
    assert cost_of(e, "tts", "local_voxcpm", "", "char", 99999) == 0.0
    # 文本:元/百万token
    assert cost_of(e, "text", "deepseek", "", "token_in", 500_000) == pytest.approx(0.5)   # 1元/1M
    assert cost_of(e, "text", "deepseek", "", "token_out", 500_000) == pytest.approx(1.0)   # 2元/1M


def test_unknown_unit_is_zero():
    assert cost_of(DEFAULT_PRICING, "image", "doubao_seedream", "", "weird_unit", 10) == 0.0


@pytest.mark.asyncio
async def test_record_and_summary_roundtrip():
    """用真实(临时)DB:记几笔 → 汇总金额/拆分正确。"""
    import uuid
    from app.database import async_session_factory
    from app.services.usage_service import record_usage, get_summary
    from app.models.usage_record import UsageRecord
    from sqlalchemy import delete

    pid = "test_" + uuid.uuid4().hex[:8]
    try:
        # 3 张 flash 图 + 10000 字豆包 TTS
        await record_usage(project_id=pid, provider_type="image",
                           provider_key="doubao_seedream",
                           model_id="doubao-seedream-5-0-flash-260915",
                           unit="image", quantity=3)
        await record_usage(project_id=pid, provider_type="tts",
                           provider_key="doubao_tts", model_id="", unit="char", quantity=10000)
        async with async_session_factory() as db:
            s = await get_summary(db, project_id=pid)
        # 3×0.12 + 1万字×1元 = 0.36 + 1.0 = 1.36
        assert s["total_cost"] == pytest.approx(1.36)
        assert s["record_count"] == 2
        types = {t["provider_type"]: t["cost"] for t in s["by_type"]}
        assert types["image"] == pytest.approx(0.36)
        assert types["tts"] == pytest.approx(1.0)
    finally:
        async with async_session_factory() as db:
            await db.execute(delete(UsageRecord).where(UsageRecord.project_id == pid))
            await db.commit()
