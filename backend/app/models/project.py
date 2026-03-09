"""Project model - the top-level container for one video production."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, String, Text, DateTime, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    aspect_ratio: Mapped[str] = mapped_column(String(10), nullable=False, default="16:9")
    video_template: Mapped[str] = mapped_column(String(50), nullable=False, default="slideshow")
    image_prompt_language: Mapped[str] = mapped_column(String(10), nullable=False, default="zh")
    output_format: Mapped[str] = mapped_column(String(10), nullable=False, default="mp4")
    image_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_quality: Mapped[str] = mapped_column(String(20), nullable=False, default="standard")
    image_style: Mapped[str] = mapped_column(String(20), nullable=False, default="natural")
    image_negative_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    subtitle_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    subtitle_font_size: Mapped[int] = mapped_column(Integer, nullable=False, default=18)
    subtitle_font_color: Mapped[str] = mapped_column(String(20), nullable=False, default="#FFFFFF")
    subtitle_outline_width: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    subtitle_position: Mapped[str] = mapped_column(String(10), nullable=False, default="bottom")
    subtitle_margin_bottom: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    metadata_json: Mapped[str | None] = mapped_column("metadata", Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    pipeline_steps = relationship("PipelineStep", back_populates="project", cascade="all, delete-orphan", order_by="PipelineStep.step_order")
    article = relationship("Article", back_populates="project", uselist=False, cascade="all, delete-orphan")
    segments = relationship("Segment", back_populates="project", cascade="all, delete-orphan", order_by="Segment.segment_order")
    images = relationship("ImageAsset", back_populates="project", cascade="all, delete-orphan")
    script = relationship("Script", back_populates="project", uselist=False, cascade="all, delete-orphan")
    audio = relationship("AudioAsset", back_populates="project", uselist=False, cascade="all, delete-orphan")
    videos = relationship("VideoOutput", back_populates="project", cascade="all, delete-orphan")
