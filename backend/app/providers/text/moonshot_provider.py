"""月之暗面 Moonshot / Kimi 文本生成 Provider (OpenAI-compatible API)."""

from ..base import ProviderMetadata, ProviderType
from ..registry import ProviderRegistry
from .openai_compatible_base import OpenAICompatibleTextProvider


@ProviderRegistry.register
class MoonshotProvider(OpenAICompatibleTextProvider):
    """
    月之暗面 Kimi 系列模型。
    Moonshot API 兼容 OpenAI chat/completions 格式。

    使用方法:
    - api_key: 填写 Moonshot API Key (https://platform.moonshot.cn)
    - model_id: 选择模型
    """
    metadata = ProviderMetadata(
        key="moonshot",
        name="Kimi (月之暗面)",
        provider_type=ProviderType.TEXT,
        description="月之暗面 Kimi / Moonshot 大模型",
        supported_models=[
            "moonshot-v1-auto",
            "moonshot-v1-8k",
            "moonshot-v1-32k",
            "moonshot-v1-128k",
        ],
        default_api_base="https://api.moonshot.cn/v1",
        requires_api_key=True,
    )
