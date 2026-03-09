"""DeepSeek text generation provider (OpenAI-compatible API)."""

from ..base import ProviderMetadata, ProviderType
from ..registry import ProviderRegistry
from .openai_compatible_base import OpenAICompatibleTextProvider


@ProviderRegistry.register
class DeepSeekProvider(OpenAICompatibleTextProvider):
    metadata = ProviderMetadata(
        key="deepseek",
        name="DeepSeek",
        provider_type=ProviderType.TEXT,
        description="DeepSeek 深度求索大模型，支持深度推理",
        supported_models=[
            "deepseek-chat",
            "deepseek-reasoner",
        ],
        default_api_base="https://api.deepseek.com/v1",
        requires_api_key=True,
    )
