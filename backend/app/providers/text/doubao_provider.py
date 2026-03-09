"""字节跳动豆包 (Doubao) text generation provider — 火山引擎 ARK API (OpenAI-compatible)."""

from ..base import ProviderMetadata, ProviderType
from ..registry import ProviderRegistry
from .openai_compatible_base import OpenAICompatibleTextProvider


@ProviderRegistry.register
class DoubaoTextProvider(OpenAICompatibleTextProvider):
    """
    豆包大模型通过火山引擎方舟 (ARK) 平台对外服务。
    ARK API 兼容 OpenAI chat/completions 格式。

    使用方法:
    - api_key: 填写火山引擎 ARK 的 API Key
    - model_id: 填写创建的推理接入点 (Endpoint ID), 例如 ep-2024xxxx-xxxxx
      也可以直接使用模型名如 doubao-pro-32k
    """
    metadata = ProviderMetadata(
        key="doubao",
        name="豆包 (Doubao)",
        provider_type=ProviderType.TEXT,
        description="字节跳动豆包大模型，通过火山引擎 ARK 平台调用",
        supported_models=[
            "doubao-pro-256k",
            "doubao-pro-32k",
            "doubao-pro-4k",
            "doubao-lite-32k",
            "doubao-lite-4k",
        ],
        default_api_base="https://ark.cn-beijing.volces.com/api/v3",
        requires_api_key=True,
    )
