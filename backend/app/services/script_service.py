"""Script generation service."""

import json
import logging

from sqlalchemy import select

from ..database import async_session_factory
from ..models import Project, Article, Script, ProviderConfig
from ..providers.base import ProviderType
from ..providers.registry import ProviderRegistry
from ..config import get_settings

logger = logging.getLogger(__name__)


class ScriptService:
    """Handles oral broadcast script generation."""

    async def generate_script(self, project_id: str,
                               provider_overrides: dict[str, str] | None = None):
        """Generate an oral broadcast script from the project's article."""
        settings = get_settings()

        async with async_session_factory() as db:
            result = await db.execute(select(Article).where(Article.project_id == project_id))
            article = result.scalar_one_or_none()
            if not article:
                raise ValueError(f"No article found for project {project_id}")

            # Get text provider
            provider_config = await self._get_provider(db, "text", provider_overrides)
            if not provider_config:
                raise ValueError("No text provider configured")

            api_key = provider_config.api_key
            if not api_key:
                key_map = {
                    "claude": settings.claude_api_key,
                    "openai": settings.openai_api_key,
                }
                api_key = key_map.get(provider_config.provider_key, "")

            extra_config = json.loads(provider_config.config_json) if provider_config.config_json else None
            text_provider = ProviderRegistry.instantiate(
                provider_type=ProviderType.TEXT,
                key=provider_config.provider_key,
                api_key=api_key,
                api_base_url=provider_config.api_base_url or "",
                model_id=provider_config.model_id or "",
                config=extra_config,
            )

            response = await text_provider.generate_script(
                article=article.content,
                style=settings.content.script_default_style,
            )

            # Save or update script
            result = await db.execute(select(Script).where(Script.project_id == project_id))
            script = result.scalar_one_or_none()

            if script:
                script.content = response.content
                script.provider_id = provider_config.id
                script.is_manual = False
                script.version += 1
            else:
                script = Script(
                    project_id=project_id,
                    content=response.content,
                    style=settings.content.script_default_style,
                    provider_id=provider_config.id,
                    is_manual=False,
                )
                db.add(script)

            await db.commit()
            return script

    async def _get_provider(self, db, provider_type: str,
                             overrides: dict[str, str] | None = None) -> ProviderConfig | None:
        # Priority: 1. Override, 2. DB default, 3. Env var fallback, 4. First available
        if overrides and provider_type in overrides:
            result = await db.execute(
                select(ProviderConfig).where(ProviderConfig.id == overrides[provider_type])
            )
            return result.scalar_one_or_none()

        result = await db.execute(
            select(ProviderConfig)
            .where(ProviderConfig.provider_type == provider_type, ProviderConfig.is_default == True)
        )
        config = result.scalar_one_or_none()
        if config:
            return config

        # Fallback 1: try to create from environment variables
        from .provider_helper import get_provider_from_env
        config = await get_provider_from_env(db, provider_type)
        if config:
            return config

        # Fallback 2: get first available provider (for UI-added providers)
        from .provider_helper import get_first_provider
        return await get_first_provider(db, provider_type)
