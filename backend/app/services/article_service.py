"""Article generation service."""

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import async_session_factory
from ..models import Project, Article, ProviderConfig
from ..providers.base import ProviderType
from ..providers.registry import ProviderRegistry
from ..config import get_settings

logger = logging.getLogger(__name__)


class ArticleService:
    """Handles article generation using AI text providers."""

    async def generate_article(self, project_id: str,
                                provider_overrides: dict[str, str] | None = None):
        """Generate an article for a project using the configured text provider."""
        settings = get_settings()

        async with async_session_factory() as db:
            project = await db.get(Project, project_id)
            if not project:
                raise ValueError(f"Project {project_id} not found")

            # Get text provider
            provider_config = await self._get_provider(db, "text", provider_overrides)
            text_provider = self._instantiate_provider(provider_config, settings)

            # Generate article
            response = await text_provider.generate_article(
                topic=project.topic,
                style=settings.content.article_default_style,
                language=settings.content.default_language,
                min_words=settings.content.article_min_words,
                max_words=settings.content.article_max_words,
            )

            # Save or update article
            result = await db.execute(select(Article).where(Article.project_id == project_id))
            article = result.scalar_one_or_none()

            if article:
                article.content = response.content
                article.title = project.title
                article.word_count = len(response.content)
                article.provider_id = provider_config.id if provider_config else None
                article.is_manual = False
                article.version += 1
            else:
                article = Article(
                    project_id=project_id,
                    title=project.title,
                    content=response.content,
                    word_count=len(response.content),
                    language=settings.content.default_language,
                    provider_id=provider_config.id if provider_config else None,
                    is_manual=False,
                )
                db.add(article)

            await db.commit()
            return article

    async def _get_provider(self, db: AsyncSession, provider_type: str,
                             overrides: dict[str, str] | None = None) -> ProviderConfig | None:
        """Get the provider config for the given type.

        Priority:
        1. Override from pipeline parameters
        2. Database default provider config
        3. Environment variable fallback (auto-detect)
        """
        if overrides and provider_type in overrides:
            result = await db.execute(
                select(ProviderConfig).where(ProviderConfig.id == overrides[provider_type])
            )
            return result.scalar_one_or_none()

        # Try to get default from database
        result = await db.execute(
            select(ProviderConfig)
            .where(ProviderConfig.provider_type == provider_type, ProviderConfig.is_default == True)
        )
        config = result.scalar_one_or_none()

        if config:
            return config

        # Fallback 1: try to create from environment variables
        config = await self._get_provider_from_env(db, provider_type)
        if config:
            return config

        # Fallback 2: get first available provider (for UI-added providers without default set)
        from .provider_helper import get_first_provider
        return await get_first_provider(db, provider_type)

    async def _get_provider_from_env(self, db: AsyncSession, provider_type: str) -> ProviderConfig | None:
        """Auto-detect and create provider config from environment variables."""
        settings = get_settings()

        # Map provider keys to their env var names and supported types
        env_provider_map = {
            "text": [
                ("deepseek", settings.deepseek_api_key, "deepseek-chat"),
                ("doubao", settings.doubao_api_key, "doubao-pro-4k"),
                ("qwen", settings.qwen_api_key, "qwen-turbo"),
                ("zhipu", settings.zhipu_api_key, "glm-4-flash"),
                ("minimax", settings.minimax_api_key, "abab6.5s-chat"),
                ("moonshot", settings.moonshot_api_key, "moonshot-v1-8k"),
                ("stepfun", settings.stepfun_api_key, "step-1-flash"),
                ("siliconflow", settings.siliconflow_api_key, "deepseek-ai/DeepSeek-V3"),
                ("wenxin", settings.wenxin_api_key, "ernie-3.5-8k"),
                ("openai", settings.openai_api_key, "gpt-4o-mini"),
                ("claude", settings.claude_api_key, "claude-haiku-4-5-20251001"),
            ],
            "image": [
                ("doubao_seedream", settings.doubao_api_key, "doubao-seedream-5-0-260128"),
                ("zhipu_cogview", settings.zhipu_api_key, "cogview-3-plus"),
                ("qwen_wanx", settings.qwen_api_key, "wanx2.1-t2i-turbo"),
                ("minimax_image", settings.minimax_api_key, "image-01"),
                ("dalle", settings.openai_api_key, "dall-e-3"),
            ],
            "tts": [
                ("doubao_tts", settings.doubao_api_key, "doubao-tts"),
                ("minimax_tts", settings.minimax_api_key, "speech-02-turbo"),
                ("aliyun_cosyvoice", settings.qwen_api_key, "cosyvoice-v2"),
                ("openai_tts", settings.openai_api_key, "tts-1-hd"),
                ("xunfei_tts", settings.xunfei_api_key, "xtts"),
            ],
            "video": [
                ("doubao_seedance", settings.doubao_api_key, "doubao-seedance-2-0-260128"),
                ("zhipu_cogvideo", settings.zhipu_api_key, "cogvideox-2"),
            ],
        }

        providers = env_provider_map.get(provider_type, [])
        for key, api_key, model_id in providers:
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

    def _instantiate_provider(self, config: ProviderConfig | None, settings):
        """Create a provider instance from config."""
        if not config:
            raise ValueError("No text provider configured. Please add one in Settings.")

        extra_config = json.loads(config.config_json) if config.config_json else None
        api_key = config.api_key

        # Fallback to environment API keys if not set in DB
        if not api_key:
            key_map = {
                "claude": settings.claude_api_key,
                "openai": settings.openai_api_key,
                "qwen": settings.qwen_api_key,
                "zhipu": settings.zhipu_api_key,
                "wenxin": settings.wenxin_api_key,
            }
            api_key = key_map.get(config.provider_key, "")

        return ProviderRegistry.instantiate(
            provider_type=ProviderType(config.provider_type),
            key=config.provider_key,
            api_key=api_key,
            api_base_url=config.api_base_url or "",
            model_id=config.model_id or "",
            config=extra_config,
        )
