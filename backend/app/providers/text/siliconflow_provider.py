"""SiliconFlow (硅基流动) 文本生成 Provider (OpenAI-compatible API).

SiliconFlow 是国内流行的模型推理平台，提供多种开源模型的托管服务，
包括 DeepSeek、Qwen、GLM 等的开源版本，性价比极高。
"""

from ..base import ProviderMetadata, ProviderType
from ..registry import ProviderRegistry
from .openai_compatible_base import OpenAICompatibleTextProvider


@ProviderRegistry.register
class SiliconFlowProvider(OpenAICompatibleTextProvider):
    """
    SiliconFlow 硅基流动推理平台。

    使用方法:
    - api_key: 填写 SiliconFlow API Key (https://siliconflow.cn)
    - model_id: 选择模型

    支持的模型包括各种开源模型的托管版本。
    """
    metadata = ProviderMetadata(
        key="siliconflow",
        name="SiliconFlow (硅基流动)",
        provider_type=ProviderType.TEXT,
        description="硅基流动模型推理平台，支持多种开源模型",
        supported_models=[
            "deepseek-ai/DeepSeek-V3",
            "deepseek-ai/DeepSeek-R1",
            "Qwen/Qwen2.5-72B-Instruct",
            "Qwen/Qwen2.5-32B-Instruct",
            "THUDM/glm-4-9b-chat",
            "meta-llama/Meta-Llama-3.1-70B-Instruct",
            "meta-llama/Meta-Llama-3.1-8B-Instruct",
        ],
        default_api_base="https://api.siliconflow.cn/v1",
        requires_api_key=True,
    )
