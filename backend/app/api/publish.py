"""发布通道接口(目前:微信公众号图文草稿)。

只做到「建草稿」,不做发布(freepublish 不可逆),发布留给用户在公众号后台完成。
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..services.publishers.wechat_publisher import WeChatAPIError
from ..services.wechat_publish_service import (
    create_draft_for_project,
    get_wechat_config,
    save_wechat_config,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class WeChatConfigIn(BaseModel):
    appid: str = Field(..., description="公众号 AppID")
    app_secret: str = Field("", description="公众号 AppSecret;留空表示不修改已存的 secret")


class WeChatConfigOut(BaseModel):
    configured: bool
    appid: str


class WeChatDraftIn(BaseModel):
    include_video: bool = Field(True, description="是否把成片视频上传到公众号素材库")


class WeChatDraftOut(BaseModel):
    draft_media_id: str
    video_uploaded: bool
    cover_used: str
    title: str


@router.get("/wechat/config", response_model=WeChatConfigOut)
async def wechat_get_config(db: AsyncSession = Depends(get_db)):
    return await get_wechat_config(db)


@router.put("/wechat/config", response_model=WeChatConfigOut)
async def wechat_put_config(data: WeChatConfigIn, db: AsyncSession = Depends(get_db)):
    try:
        return await save_wechat_config(db, data.appid, data.app_secret)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/wechat/draft/{project_id}", response_model=WeChatDraftOut)
async def wechat_create_draft(
    project_id: str, data: WeChatDraftIn, db: AsyncSession = Depends(get_db)
):
    try:
        result = await create_draft_for_project(db, project_id, data.include_video)
        return result
    except WeChatAPIError as e:
        # 微信业务错误(白名单/未认证/配额等)透出友好提示
        raise HTTPException(status_code=502, detail=e.friendly)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        logger.exception("WeChat draft failed for %s", project_id)
        raise HTTPException(status_code=500, detail=f"建草稿失败: {e}")
