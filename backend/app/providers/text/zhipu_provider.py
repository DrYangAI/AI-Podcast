"""智谱AI (Zhipu / GLM) text generation provider — BigModel API (OpenAI-compatible)."""

from ..base import ProviderMetadata, ProviderType
from ..registry import ProviderRegistry
from .openai_compatible_base import OpenAICompatibleTextProvider


@ProviderRegistry.register
class ZhipuProvider(OpenAICompatibleTextProvider):
    """
    智谱 AI GLM 系列模型。
    BigModel 平台 API 兼容 OpenAI chat/completions 格式。

    使用方法:
    - api_key: 填写智谱 API Key
    - model_id: 选择模型，如 glm-4-plus, glm-4-flash 等
    """
    metadata = ProviderMetadata(
        key="zhipu",
        name="智谱 AI (GLM)",
        provider_type=ProviderType.TEXT,
        description="智谱 AI GLM 系列大模型",
        supported_models=[
            "glm-4-plus",
            "glm-4-0520",
            "glm-4-air",
            "glm-4-airx",
            "glm-4-long",
            "glm-4-flash",
            "glm-4-flashx",
        ],
        default_api_base="https://open.bigmodel.cn/api/paas/v4",
        requires_api_key=True,
    )
