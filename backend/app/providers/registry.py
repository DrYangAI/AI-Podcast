"""Provider discovery and registration registry."""

from typing import Any, Type

from .base import BaseProvider, ProviderMetadata, ProviderType


class ProviderRegistry:
    """
    Central registry for all AI provider plugins.
    Providers register themselves at import time via the @register decorator.
    """

    _providers: dict[ProviderType, dict[str, Type[BaseProvider]]] = {
        ProviderType.TEXT: {},
        ProviderType.IMAGE: {},
        ProviderType.TTS: {},
        ProviderType.VIDEO: {},
    }

    @classmethod
    def register(cls, provider_class: Type[BaseProvider]) -> Type[BaseProvider]:
        """Decorator to register a provider plugin."""
        meta = provider_class.metadata
        cls._providers[meta.provider_type][meta.key] = provider_class
        return provider_class

    @classmethod
    def get_provider_class(cls, provider_type: ProviderType, key: str) -> Type[BaseProvider]:
        """Retrieve a registered provider class by type and key."""
        type_providers = cls._providers.get(provider_type, {})
        if key not in type_providers:
            available = list(type_providers.keys())
            raise ValueError(
                f"No provider '{key}' registered for type '{provider_type}'. "
                f"Available: {available}"
            )
        return type_providers[key]

    @classmethod
    def list_providers(cls, provider_type: ProviderType | None = None) -> list[ProviderMetadata]:
        """List all registered providers, optionally filtered by type."""
        result = []
        types = [provider_type] if provider_type else list(ProviderType)
        for pt in types:
            for provider_cls in cls._providers.get(pt, {}).values():
                result.append(provider_cls.metadata)
        return result

    @classmethod
    def instantiate(cls, provider_type: ProviderType, key: str,
                    api_key: str = "", api_base_url: str = "",
                    model_id: str = "", config: dict[str, Any] | None = None) -> BaseProvider:
        """Create an instance of a registered provider."""
        provider_cls = cls.get_provider_class(provider_type, key)
        return provider_cls(
            api_key=api_key,
            api_base_url=api_base_url,
            model_id=model_id,
            config=config,
        )
