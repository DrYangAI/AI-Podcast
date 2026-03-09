"""Utility functions for auto-detecting providers from environment variables."""

import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ProviderConfig
from ..config import get_settings

logger = logging.getLogger(__name__)


# Map provider keys to their env var names and default models
ENV_PROVIDER_MAP = {
    "text": [
        ("deepseek", "deepseek_api_key", "deepseek-chat"),
        ("doubao", "doubao_api_key", "doubao-pro-4k"),
        ("qwen", "qwen_api_key", "qwen-turbo"),
        ("zhipu", "zhipu_api_key", "glm-4-flash"),
        ("minimax", "minimax_api_key", "abab6.5s-chat"),
        ("moonshot", "moonshot_api_key", "moonshot-v1-8k"),
        ("stepfun", "stepfun_api_key", "step-1-flash"),
        ("siliconflow", "siliconflow_api_key", "deepseek-ai/DeepSeek-V3"),
        ("wenxin", "wenxin_api_key", "ernie-3.5-8k"),
        ("openai", "openai_api_key", "gpt-4o-mini"),
        ("claude", "claude_api_key", "claude-haiku-4-5-20251001"),
    ],
    "image": [
        ("doubao_seedream", "doubao_api_key", "doubao-seedream-5-0-260128"),
        ("zhipu_cogview", "zhipu_api_key", "cogview-3-plus"),
        ("qwen_wanx", "qwen_api_key", "wanx2.1-t2i-turbo"),
        ("minimax_image", "minimax_api_key", "image-01"),
        ("dalle", "openai_api_key", "dall-e-3"),
    ],
    "tts": [
        ("doubao_tts", "doubao_api_key", "doubao-tts"),
        ("minimax_tts", "minimax_api_key", "speech-02-turbo"),
        ("aliyun_cosyvoice", "qwen_api_key", "cosyvoice-v2"),
        ("openai_tts", "openai_api_key", "tts-1-hd"),
        ("xunfei_tts", "xunfei_api_key", "xtts"),
    ],
    "video": [
        ("doubao_seedance", "doubao_api_key", "doubao-seedance-2-0-260128"),
        ("zhipu_cogvideo", "zhipu_api_key", "cogvideox-2"),
    ],
}


async def get_provider_from_env(db: AsyncSession, provider_type: str) -> ProviderConfig | None:
    """
    Auto-detect and create provider config from environment variables.

    Scans through known provider keys and returns the first one
 has a valid API key in    that the environment.
    """
    settings = get_settings()
    providers = ENV_PROVIDER_MAP.get(provider_type, [])

    for key, env_var_name, model_id in providers:
        api_key = getattr(settings, env_var_name, "")
        if api_key:
            # Found a valid env var provider, create config
            config = ProviderConfig(
                provider_key=key,
                provider_type=provider_type,
                api_key=api_key,
                model_id=model_id,
                is_default=True,
            )
            db.add(config)
            await db.flush()
            logger.info(f"Auto-created {provider_type} provider from env: {key}")
            return config

    return None


async def get_first_provider(db: AsyncSession, provider_type: str) -> ProviderConfig | None:
    """
    Get the first available provider from database (fallback if no default set).

    This handles the case where users add providers via UI but don't set
    any as default.
    """
    result = await db.execute(
        select(ProviderConfig)
        .where(
            ProviderConfig.provider_type == provider_type,
            ProviderConfig.is_active == True
        )
        .order_by(ProviderConfig.created_at)
        .limit(1)
    )
    return result.scalar_one_or_none()
