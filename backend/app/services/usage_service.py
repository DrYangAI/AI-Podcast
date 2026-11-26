"""用量记账 + 价格表 + 费用汇总。

设计:UsageRecord 只存原始用量(张/字/token),费用在汇总时用【当前价格表】实时
算。价格表是一组可编辑的条目(默认预填,存在 GlobalSetting category='pricing'),
改了立刻影响全部历史估算。所有金额均为【估算】,以火山/各平台实际账单为准。

价格按人类单位填写,更好改:
- 图片:元/张
- TTS :元/万字
- 文本:元/百万token(输入、输出分开)
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import async_session_factory
from ..models.global_setting import GlobalSetting
from ..models.usage_record import UsageRecord

logger = logging.getLogger(__name__)

PRICING_CATEGORY = "pricing"

# unit → (计价基准单位名, 换算除数)。cost = quantity / divisor * price
UNIT_BASIS = {
    "image": ("张", 1),
    "char": ("万字", 10_000),
    "token_in": ("百万token", 1_000_000),
    "token_out": ("百万token", 1_000_000),
}

# 默认价格表(2026-11 已知值;图片价来自火山方舟,其余为估算占位,请按实际改)。
# 每条:provider_type, provider_key, model_id(""=该 provider 任意模型), unit, price, note
DEFAULT_PRICING: list[dict] = [
    # ── 图片(火山方舟 Seedream,元/张) ──
    {"provider_type": "image", "provider_key": "doubao_seedream",
     "model_id": "doubao-seedream-5-0-flash-260915", "unit": "image", "price": 0.12,
     "note": "5.0-flash 固定 0.12 元/张"},
    {"provider_type": "image", "provider_key": "doubao_seedream",
     "model_id": "doubao-seedream-5-5-261028", "unit": "image", "price": 0.18,
     "note": "5.5 实际 0.13-0.23/张(按输出尺寸),这里取代表值"},
    {"provider_type": "image", "provider_key": "doubao_seedream",
     "model_id": "", "unit": "image", "price": 0.20, "note": "豆包图片兜底价"},
    {"provider_type": "image", "provider_key": "gemini_image",
     "model_id": "", "unit": "image", "price": 0.0, "note": "Gemini 图片单价未配置,请填入"},
    # ── 语音 TTS(元/万字) ──
    {"provider_type": "tts", "provider_key": "local_voxcpm",
     "model_id": "", "unit": "char", "price": 0.0, "note": "本地 VoxCPM,免费"},
    {"provider_type": "tts", "provider_key": "doubao_tts",
     "model_id": "", "unit": "char", "price": 1.0, "note": "占位估算 1 元/万字,请按火山实际改"},
    # ── 文本(元/百万token,输入/输出) ──
    {"provider_type": "text", "provider_key": "deepseek",
     "model_id": "", "unit": "token_in", "price": 1.0, "note": "占位估算,请按实际改"},
    {"provider_type": "text", "provider_key": "deepseek",
     "model_id": "", "unit": "token_out", "price": 2.0, "note": "占位估算,请按实际改"},
    {"provider_type": "text", "provider_key": "gemini",
     "model_id": "", "unit": "token_in", "price": 1.0, "note": "占位估算,请按实际改"},
    {"provider_type": "text", "provider_key": "gemini",
     "model_id": "", "unit": "token_out", "price": 4.0, "note": "占位估算,请按实际改"},
]


# ── 价格表读写 ──────────────────────────────────────────────────────────
async def get_pricing(db: AsyncSession) -> list[dict]:
    """返回当前价格表(DB 覆盖优先,否则默认)。"""
    row = await db.get(GlobalSetting, PRICING_CATEGORY)
    if row and row.settings_json:
        try:
            data = json.loads(row.settings_json)
            entries = data.get("entries")
            if isinstance(entries, list) and entries:
                return entries
        except json.JSONDecodeError:
            pass
    return [dict(e) for e in DEFAULT_PRICING]


async def set_pricing(db: AsyncSession, entries: list[dict]) -> list[dict]:
    row = await db.get(GlobalSetting, PRICING_CATEGORY)
    payload = json.dumps({"entries": entries}, ensure_ascii=False)
    if row is None:
        db.add(GlobalSetting(category=PRICING_CATEGORY, settings_json=payload))
    else:
        row.settings_json = payload
    await db.commit()
    return entries


def _price_lookup(entries: list[dict], ptype: str, key: str, model: str, unit: str) -> float:
    """最具体优先:精确 model > 该 provider 的 model=''(通配) 。找不到返回 0。"""
    exact = None
    wildcard = None
    for e in entries:
        if e.get("provider_type") == ptype and e.get("provider_key") == key and e.get("unit") == unit:
            em = e.get("model_id", "")
            if em == model:
                exact = e
            elif em == "":
                wildcard = e
    hit = exact or wildcard
    return float(hit.get("price", 0.0)) if hit else 0.0


def cost_of(entries: list[dict], ptype: str, key: str, model: str, unit: str, quantity: float) -> float:
    price = _price_lookup(entries, ptype, key, model, unit)
    _, divisor = UNIT_BASIS.get(unit, ("", 1))
    return quantity / divisor * price if divisor else 0.0


# ── 记账(埋点调用这个) ─────────────────────────────────────────────────
# 用独立 session,与调用方的事务完全解耦:记账失败/回滚绝不影响主流程生成。
async def record_usage(*, project_id: str | None, provider_type: str,
                       provider_key: str, model_id: str, unit: str, quantity: float,
                       label: str | None = None) -> None:
    try:
        if not quantity or quantity <= 0:
            return
        async with async_session_factory() as db:
            db.add(UsageRecord(
                project_id=project_id, provider_type=provider_type,
                provider_key=provider_key or "", model_id=model_id or "",
                unit=unit, quantity=float(quantity), label=label,
            ))
            await db.commit()
    except Exception as e:  # noqa: BLE001 - 记账是旁路,不能拖垮生成
        logger.warning("record_usage failed (ignored): %s", e)


async def record_text_usage(*, project_id: str | None, provider_key: str,
                            model_id: str, token_usage: dict, label: str | None = None) -> None:
    """文本调用:从 token_usage 拆出输入/输出 token 各记一行。"""
    tin = token_usage.get("prompt_tokens") or token_usage.get("input_tokens") or 0
    tout = token_usage.get("completion_tokens") or token_usage.get("output_tokens") or 0
    if tin:
        await record_usage(project_id=project_id, provider_type="text",
                           provider_key=provider_key, model_id=model_id,
                           unit="token_in", quantity=tin, label=label)
    if tout:
        await record_usage(project_id=project_id, provider_type="text",
                           provider_key=provider_key, model_id=model_id,
                           unit="token_out", quantity=tout, label=label)


# ── 汇总 ────────────────────────────────────────────────────────────────
_TYPE_NAMES = {"image": "图片", "tts": "语音", "text": "文本"}


async def get_summary(db: AsyncSession, project_id: str | None = None, days: int | None = None) -> dict:
    """返回总费用 + 按类型/模型/项目/日期的拆分(均为估算)。"""
    entries = await get_pricing(db)

    q = select(UsageRecord)
    if project_id:
        q = q.where(UsageRecord.project_id == project_id)
    if days:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        q = q.where(UsageRecord.created_at >= since)
    records = (await db.execute(q)).scalars().all()

    total = 0.0
    by_model: dict[tuple, dict] = defaultdict(lambda: {"quantity": 0.0, "cost": 0.0})
    by_type: dict[str, float] = defaultdict(float)
    by_project: dict[str | None, float] = defaultdict(float)
    by_day: dict[str, float] = defaultdict(float)

    for r in records:
        c = cost_of(entries, r.provider_type, r.provider_key, r.model_id, r.unit, r.quantity)
        total += c
        by_type[r.provider_type] += c
        by_project[r.project_id] += c
        day = r.created_at.strftime("%Y-%m-%d") if r.created_at else "?"
        by_day[day] += c
        k = (r.provider_type, r.provider_key, r.model_id, r.unit)
        by_model[k]["quantity"] += r.quantity
        by_model[k]["cost"] += c

    def unit_label(u: str) -> str:
        return {"image": "张", "char": "字", "token_in": "输入token", "token_out": "输出token"}.get(u, u)

    models_out = [
        {"provider_type": pt, "type_name": _TYPE_NAMES.get(pt, pt), "provider_key": pk,
         "model_id": mid or "(默认)", "unit": unit_label(un),
         "quantity": round(v["quantity"], 2), "cost": round(v["cost"], 4)}
        for (pt, pk, mid, un), v in sorted(by_model.items(), key=lambda kv: -kv[1]["cost"])
    ]

    return {
        "total_cost": round(total, 4),
        "currency": "CNY",
        "record_count": len(records),
        "by_type": [{"provider_type": k, "type_name": _TYPE_NAMES.get(k, k), "cost": round(v, 4)}
                    for k, v in sorted(by_type.items(), key=lambda kv: -kv[1])],
        "by_model": models_out,
        "by_day": [{"day": k, "cost": round(v, 4)} for k, v in sorted(by_day.items())],
        "by_project": {str(k): round(v, 4) for k, v in by_project.items()},
    }
