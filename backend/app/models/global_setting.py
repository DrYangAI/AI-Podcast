"""Global settings model for storing default configurations."""

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class GlobalSetting(Base):
    """Key-value store for global default settings (e.g., portrait defaults)."""

    __tablename__ = "global_settings"

    category: Mapped[str] = mapped_column(String(50), primary_key=True)
    settings_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
