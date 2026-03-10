"""Pipeline step model - tracks status of each processing stage."""

import uuid
from datetime import datetime

from sqlalchemy import String, Text, Integer, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class PipelineStep(Base):
    __tablename__ = "pipeline_steps"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    project_id: Mapped[str] = mapped_column(String(32), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    step_name: Mapped[str] = mapped_column(String(30), nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    provider_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("provider_configs.id"), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("project_id", "step_name", name="uq_pipeline_step"),
    )

    # Relationships
    project = relationship("Project", back_populates="pipeline_steps")
    provider = relationship("ProviderConfig")

    # Step name constants
    STEP_NAMES = [
        "topic_input",
        "article_generation",
        "content_splitting",
        "image_generation",
        "script_generation",
        "tts_audio",
        "video_composition",
        "portrait_composite",
    ]
