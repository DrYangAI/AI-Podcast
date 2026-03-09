"""百度文心一言 (ERNIE / Wenxin) text generation provider — 千帆 API (OpenAI-compatible)."""

from ..base import ProviderMetadata, ProviderType
from ..registry import ProviderRegistry
from .openai_compatible_base import OpenAICompatibleTextProvider


@ProviderRegistry.register
class WenxinProvider(OpenAICompatibleTextProvider):
    """
    百度文心一言 / ERNIE 系列模型。
    百度千帆平台新版 API 已兼容 OpenAI chat/completions 格式。

    使用方法:
    - api_key: 填写千帆平台的 Bearer Token
    - model_id: 选择模型
    """
    metadata = ProviderMetadata(
        key="wenxin",
        name="文心一言 (ERNIE)",
        provider_type=ProviderType.TEXT,
        description="百度文心一言 / ERNIE 大模型系列",
        supported_models=[
            "ernie-4.0-8k",
            "ernie-4.0-turbo-8k",
            "ernie-3.5-8k",
            "ernie-3.5-128k",
            "ernie-speed-8k",
            "ernie-speed-128k",
            "ernie-lite-8k",
        ],
        default_api_base="https://qianfan.baidubce.com/v2",
        requires_api_key=True,
    )
