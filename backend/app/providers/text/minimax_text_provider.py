"""MiniMax text generation provider (OpenAI-compatible API)."""

from ..base import ProviderMetadata, ProviderType
from ..registry import ProviderRegistry
from .openai_compatible_base import OpenAICompatibleTextProvider


@ProviderRegistry.register
class MiniMaxTextProvider(OpenAICompatibleTextProvider):
    """
    MiniMax 大模型 (海螺 AI)。
    MiniMax API 兼容 OpenAI chat/completions 格式。

    使用方法:
    - api_key: 填写 MiniMax API Key
    - model_id: 选择模型
    """
    metadata = ProviderMetadata(
        key="minimax",
        name="MiniMax (海螺AI)",
        provider_type=ProviderType.TEXT,
        description="MiniMax 海螺 AI 大模型",
        supported_models=[
            "MiniMax-Text-01",
            "abab6.5s-chat",
            "abab6.5-chat",
            "abab5.5-chat",
        ],
        default_api_base="https://api.minimax.chat/v1",
        requires_api_key=True,
    )
