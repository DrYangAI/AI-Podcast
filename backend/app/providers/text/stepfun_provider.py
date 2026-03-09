"""阶跃星辰 Step Fun 文本生成 Provider (OpenAI-compatible API)."""

from ..base import ProviderMetadata, ProviderType
from ..registry import ProviderRegistry
from .openai_compatible_base import OpenAICompatibleTextProvider


@ProviderRegistry.register
class StepFunProvider(OpenAICompatibleTextProvider):
    """
    阶跃星辰 Step 系列模型。
    API 兼容 OpenAI chat/completions 格式。

    使用方法:
    - api_key: 填写 StepFun API Key (https://platform.stepfun.com)
    - model_id: 选择模型
    """
    metadata = ProviderMetadata(
        key="stepfun",
        name="阶跃星辰 (Step Fun)",
        provider_type=ProviderType.TEXT,
        description="阶跃星辰 Step 系列大模型",
        supported_models=[
            "step-2-16k",
            "step-1-128k",
            "step-1-32k",
            "step-1-8k",
            "step-1-flash",
        ],
        default_api_base="https://api.stepfun.com/v1",
        requires_api_key=True,
    )
