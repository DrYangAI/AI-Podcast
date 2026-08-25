"""微信公众号发布编排:读凭证、取项目素材、建图文草稿。

发布通道用一条 ProviderConfig 存凭证:
  provider_type="publish", provider_key="wechat_mp",
  api_key=AppSecret, config_json={"appid": "..."}
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.article import Article
from ..models.project import Project
from ..models.provider_config import ProviderConfig
from ..models.publish_asset import PublishAsset
from ..models.video_output import VideoOutput
from .publishers.wechat_publisher import (
    WeChatArticle,
    WeChatClient,
    article_text_to_html,
)

logger = logging.getLogger(__name__)

PUBLISH_TYPE = "publish"
WECHAT_KEY = "wechat_mp"

# 挑封面时的平台优先级(都没有就用任意一个存在的封面)
_COVER_PLATFORM_PREFERENCE = ["weixin", "douyin", "xiaohongshu"]


async def _get_config_row(db: AsyncSession) -> ProviderConfig | None:
    return (
        await db.execute(
            select(ProviderConfig).where(
                ProviderConfig.provider_type == PUBLISH_TYPE,
                ProviderConfig.provider_key == WECHAT_KEY,
            )
        )
    ).scalar_one_or_none()


async def get_wechat_config(db: AsyncSession) -> dict:
    """返回 {configured, appid}。不回传 AppSecret。"""
    row = await _get_config_row(db)
    if not row:
        return {"configured": False, "appid": ""}
    appid = ""
    if row.config_json:
        try:
            appid = (json.loads(row.config_json) or {}).get("appid", "")
        except json.JSONDecodeError:
            appid = ""
    return {"configured": bool(appid and row.api_key), "appid": appid}


async def save_wechat_config(db: AsyncSession, appid: str, app_secret: str) -> dict:
    """新增或更新公众号凭证。app_secret 传空则保留原值(便于只改 AppID)。"""
    appid = (appid or "").strip()
    app_secret = (app_secret or "").strip()
    if not appid:
        raise ValueError("AppID 不能为空")

    row = await _get_config_row(db)
    if row is None:
        if not app_secret:
            raise ValueError("首次配置必须填写 AppSecret")
        row = ProviderConfig(
            name="微信公众号",
            provider_type=PUBLISH_TYPE,
            provider_key=WECHAT_KEY,
            api_key=app_secret,
            config_json=json.dumps({"appid": appid}),
            is_active=True,
        )
        db.add(row)
    else:
        row.config_json = json.dumps({"appid": appid})
        if app_secret:  # 留空表示不改 secret
            row.api_key = app_secret
    await db.commit()
    return await get_wechat_config(db)


async def _load_credentials(db: AsyncSession) -> tuple[str, str]:
    row = await _get_config_row(db)
    if not row or not row.api_key:
        raise ValueError("尚未配置公众号 AppID / AppSecret")
    appid = ""
    if row.config_json:
        appid = (json.loads(row.config_json) or {}).get("appid", "")
    if not appid:
        raise ValueError("公众号 AppID 缺失,请在发布设置里补全")
    return appid, row.api_key


def _resolve_path(p: str | None) -> Path | None:
    if not p:
        return None
    path = Path(p)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path if path.exists() else None


async def _pick_cover(db: AsyncSession, project_id: str) -> Path:
    assets = (
        await db.execute(
            select(PublishAsset).where(PublishAsset.project_id == project_id)
        )
    ).scalars().all()
    by_platform = {a.platform: a for a in assets}
    ordered = [by_platform[p] for p in _COVER_PLATFORM_PREFERENCE if p in by_platform]
    ordered += [a for a in assets if a not in ordered]
    for a in ordered:
        path = _resolve_path(a.cover_path)
        if path:
            return path
    raise ValueError("没有可用封面,请先在「发布素材」步骤生成封面。")


async def _pick_video(db: AsyncSession, project_id: str) -> Path | None:
    videos = (
        await db.execute(
            select(VideoOutput)
            .where(VideoOutput.project_id == project_id)
            .order_by(VideoOutput.created_at.desc())
        )
    ).scalars().all()
    # 优先横屏(图文里更自然),否则用最新一个
    for v in videos:
        if v.aspect_ratio in ("16:9", "16-9") and _resolve_path(v.file_path):
            return _resolve_path(v.file_path)
    for v in videos:
        path = _resolve_path(v.file_path)
        if path:
            return path
    return None


async def create_draft_for_project(
    db: AsyncSession, project_id: str, include_video: bool = True
) -> dict:
    """为项目建一条公众号图文草稿。返回 {draft_media_id, video_uploaded, ...}。"""
    project = await db.get(Project, project_id)
    if not project:
        raise ValueError(f"项目不存在: {project_id}")

    appid, secret = await _load_credentials(db)

    # 文案:优先用「发布素材」里 weixin 的标题/摘要,回退到文章
    weixin_asset = (
        await db.execute(
            select(PublishAsset).where(
                PublishAsset.project_id == project_id,
                PublishAsset.platform == "weixin",
            )
        )
    ).scalar_one_or_none()
    article = (
        await db.execute(select(Article).where(Article.project_id == project_id))
    ).scalar_one_or_none()

    title = (weixin_asset.title if weixin_asset and weixin_asset.title else None) \
        or (article.title if article else None) or project.title
    digest = (weixin_asset.description if weixin_asset and weixin_asset.description else "")
    body_text = article.content if article else ""
    if not body_text.strip():
        raise ValueError("文章正文为空,无法生成图文草稿。请先生成文章。")
    content_html = article_text_to_html(body_text)

    cover_path = await _pick_cover(db, project_id)
    video_path = await _pick_video(db, project_id) if include_video else None

    client = WeChatClient(appid, secret)
    token = await client.get_access_token()

    thumb_media_id = await client.add_material_image(token, cover_path)
    logger.info("WeChat: uploaded cover material %s", thumb_media_id)

    video_uploaded = False
    if video_path is not None:
        try:
            await client.add_material_video(token, video_path, title=title, introduction=digest)
            video_uploaded = True
            logger.info("WeChat: uploaded video material for %s", project_id)
        except Exception as e:  # 视频进素材库失败不该拖垮整条草稿
            logger.warning("WeChat: video material upload failed: %s", e)

    draft_media_id = await client.add_draft(
        token,
        [WeChatArticle(
            title=title,
            content_html=content_html,
            thumb_media_id=thumb_media_id,
            digest=digest,
        )],
    )
    logger.info("WeChat: created draft %s for project %s", draft_media_id, project_id)

    return {
        "draft_media_id": draft_media_id,
        "video_uploaded": video_uploaded,
        "cover_used": str(cover_path.name),
        "title": title,
    }
