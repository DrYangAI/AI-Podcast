"""Google Gemini text generation provider (OpenAI-compatible API)."""

from ..base import ProviderMetadata, ProviderType
from ..registry import ProviderRegistry
from .openai_compatible_base import OpenAICompatibleTextProvider


@ProviderRegistry.register
class GeminiProvider(OpenAICompatibleTextProvider):
    metadata = ProviderMetadata(
        key="gemini",
        name="Google Gemini",
        provider_type=ProviderType.TEXT,
        description="Google Gemini 系列大模型，支持超长上下文",
        supported_models=[
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.5-flash-lite",
            "gemini-3-flash-preview",
            "gemini-3.1-pro-preview",
            "gemini-3.1-flash-lite-preview",
        ],
        default_api_base="https://generativelanguage.googleapis.com/v1beta/openai",
        requires_api_key=True,
    )
