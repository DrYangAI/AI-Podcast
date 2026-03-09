"""通义千问 (Qwen / Alibaba Cloud) text generation provider — DashScope API (OpenAI-compatible)."""

from ..base import ProviderMetadata, ProviderType
from ..registry import ProviderRegistry
from .openai_compatible_base import OpenAICompatibleTextProvider


@ProviderRegistry.register
class QwenProvider(OpenAICompatibleTextProvider):
    """
    阿里云通义千问系列模型。
    DashScope 服务兼容 OpenAI chat/completions 格式。

    使用方法:
    - api_key: 填写阿里云 DashScope API Key
    - model_id: 选择模型，如 qwen-max, qwen-plus 等
    """
    metadata = ProviderMetadata(
        key="qwen",
        name="通义千问 (Qwen)",
        provider_type=ProviderType.TEXT,
        description="阿里云通义千问大模型系列",
        supported_models=[
            "qwen-max",
            "qwen-max-latest",
            "qwen-plus",
            "qwen-plus-latest",
            "qwen-turbo",
            "qwen-turbo-latest",
            "qwen-long",
            "qwen2.5-72b-instruct",
            "qwen2.5-32b-instruct",
            "qwen2.5-14b-instruct",
        ],
        default_api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
        requires_api_key=True,
    )
