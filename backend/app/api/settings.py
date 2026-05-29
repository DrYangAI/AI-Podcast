"""Global settings API routes."""

import json

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.global_setting import GlobalSetting

router = APIRouter()


@router.get("/defaults/{category}")
async def get_defaults(category: str, db: AsyncSession = Depends(get_db)):
    """Get global default settings for a category."""
    result = await db.execute(
        select(GlobalSetting).where(GlobalSetting.category == category)
    )
    setting = result.scalar_one_or_none()
    if not setting:
        return {}
    return json.loads(setting.settings_json)


@router.put("/defaults/{category}")
async def set_defaults(category: str, data: dict, db: AsyncSession = Depends(get_db)):
    """Save global default settings for a category."""
    result = await db.execute(
        select(GlobalSetting).where(GlobalSetting.category == category)
    )
    setting = result.scalar_one_or_none()
    if setting:
        setting.settings_json = json.dumps(data, ensure_ascii=False)
    else:
        setting = GlobalSetting(
            category=category,
            settings_json=json.dumps(data, ensure_ascii=False),
        )
        db.add(setting)
    return data
