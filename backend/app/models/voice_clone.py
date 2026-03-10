"""VoiceClone model - stores cloned voice configurations with reference audio."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Integer, String, Text, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class VoiceClone(Base):
    __tablename__ = "voice_clones"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_key: Mapped[str] = mapped_column(String(50), nullable=False, default="doubao_tts")
    speaker_id: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    reference_audio_path: Mapped[str] = mapped_column(Text, nullable=False)
    reference_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Training status: 0=NotFound, 1=Training, 2=Success, 3=Failed, 4=Active
    training_status: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
