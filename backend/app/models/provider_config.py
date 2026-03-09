"""Provider configuration model - stores AI model provider settings."""

import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import String, Text, Boolean, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class ProviderConfig(Base):
    __tablename__ = "provider_configs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_key: Mapped[str] = mapped_column(String(50), nullable=False)
    api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    config_json: Mapped[str | None] = mapped_column("config", Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("provider_type", "provider_key", "model_id", name="uq_provider"),
    )

    @property
    def config(self) -> dict[str, Any] | None:
        """Parse config_json for Pydantic serialization."""
        if self.config_json:
            return json.loads(self.config_json)
        return None
