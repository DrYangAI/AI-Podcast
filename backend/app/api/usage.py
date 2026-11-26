"""费用核算接口:用量汇总(估算) + 可编辑价格表。"""

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..services.usage_service import get_pricing, get_summary, set_pricing

logger = logging.getLogger(__name__)
router = APIRouter()


class PricingEntry(BaseModel):
    provider_type: str
    provider_key: str
    model_id: str = ""
    unit: str                      # image / char / token_in / token_out
    price: float = 0.0             # 人类单位:图=元/张, TTS=元/万字, 文本=元/百万token
    note: str = ""


class PricingPayload(BaseModel):
    entries: list[PricingEntry]


@router.get("/summary")
async def usage_summary(project_id: str | None = None, days: int | None = None,
                        db: AsyncSession = Depends(get_db)):
    """总费用(估算)+ 按类型/模型/项目/日期拆分。project_id 过滤单项目;days 过滤近 N 天。"""
    return await get_summary(db, project_id=project_id, days=days)


@router.get("/pricing")
async def pricing_get(db: AsyncSession = Depends(get_db)):
    return {"entries": await get_pricing(db)}


@router.put("/pricing")
async def pricing_put(payload: PricingPayload, db: AsyncSession = Depends(get_db)):
    entries = [e.model_dump() for e in payload.entries]
    return {"entries": await set_pricing(db, entries)}
