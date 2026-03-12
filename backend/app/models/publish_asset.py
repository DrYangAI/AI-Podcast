"""Publish asset model - stores cover images and copy for each platform."""

import uuid
from datetime import datetime

from sqlalchemy import String, Text, Integer, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class PublishAsset(Base):
    __tablename__ = "publish_assets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    project_id: Mapped[str] = mapped_column(String(32), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    platform: Mapped[str] = mapped_column(String(30), nullable=False)  # weixin, xiaohongshu, douyin, tencent_video, toutiao
    cover_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cover_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cover_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    cover_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("project_id", "platform", name="uq_publish_asset_platform"),
    )

    # Relationships
    project = relationship("Project", back_populates="publish_assets")

    PLATFORM_NAMES = {
        "weixin": "微信视频号",
        "xiaohongshu": "小红书",
        "douyin": "抖音",
        "tencent_video": "腾讯视频",
        "toutiao": "今日头条",
    }
