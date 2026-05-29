"""Prompt template model with version history."""

import uuid
from datetime import datetime

from sqlalchemy import String, Text, Float, Integer, DateTime, func, JSON
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class PromptTemplate(Base):
    """System-level default prompt templates for each pipeline step."""
    __tablename__ = "prompt_templates"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    step_name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    user_prompt_template: Mapped[str] = mapped_column(Text, nullable=False, default="")
    temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.7)
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=4096)
    variables: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list of variable names
    extra_config: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON for non-prompt params
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PromptTemplateHistory(Base):
    """Version history for prompt template changes."""
    __tablename__ = "prompt_template_history"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    template_id: Mapped[str] = mapped_column(String(32), nullable=False)
    step_name: Mapped[str] = mapped_column(String(50), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    user_prompt_template: Mapped[str] = mapped_column(Text, nullable=False, default="")
    temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.7)
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=4096)
    extra_config: Mapped[str | None] = mapped_column(Text, nullable=True)
    change_source: Mapped[str] = mapped_column(String(20), nullable=False, default="system")  # "system" or "project:{id}"
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
