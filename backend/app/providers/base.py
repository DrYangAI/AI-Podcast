"""Abstract base classes for all AI providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ProviderType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    TTS = "tts"
    VIDEO = "video"


@dataclass
class ProviderMetadata:
    """Declarative metadata about a provider plugin."""
    key: str
    name: str
    provider_type: ProviderType
    description: str = ""
    supported_models: list[str] = field(default_factory=list)
    config_schema: dict = field(default_factory=dict)
    requires_api_key: bool = True
    default_api_base: str = ""


class BaseProvider(ABC):
    """Abstract base for all AI providers."""

    metadata: ProviderMetadata  # Subclasses must define as class variable

    def __init__(self, api_key: str = "", api_base_url: str = "",
                 model_id: str = "", config: dict[str, Any] | None = None):
        self.api_key = api_key
        self.api_base_url = api_base_url or self.metadata.default_api_base
        self.model_id = model_id
        self.config = config or {}

    @abstractmethod
    async def validate_connection(self) -> bool:
        """Test that the provider is reachable and the API key is valid."""
        ...

    async def get_usage_info(self) -> dict[str, Any]:
        """Return provider-specific usage/quota information."""
        return {}
