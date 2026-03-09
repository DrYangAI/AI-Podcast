"""Image generation service."""

import json
import logging
from pathlib import Path

from sqlalchemy import select

from ..database import async_session_factory
from ..models import Project, Segment, ImageAsset, ProviderConfig
from ..providers.base import ProviderType
from ..providers.registry import ProviderRegistry
from ..config import get_settings

logger = logging.getLogger(__name__)


class ImageService:
    """Handles image generation for segments."""

    async def generate_images(self, project_id: str,
                               provider_overrides: dict[str, str] | None = None):
        """Generate images for all segments of a project."""
        settings = get_settings()

        async with async_session_factory() as db:
            project = await db.get(Project, project_id)
            if not project:
                raise ValueError(f"Project {project_id} not found")

            # Get segments
            result = await db.execute(
                select(Segment)
                .where(Segment.project_id == project_id)
                .order_by(Segment.segment_order)
            )
            segments = list(result.scalars().all())
            if not segments:
                raise ValueError(f"No segments found for project {project_id}")

            # Generate image prompts using text provider
            image_prompt_language = getattr(project, 'image_prompt_language', 'en') or 'en'
            # Always regenerate prompts to respect current language setting
            text_config = await self._get_provider(db, "text", provider_overrides)
            if text_config:
                await self._generate_image_prompts(
                    db, segments, text_config, settings,
                    language=image_prompt_language,
                )

            # Get image provider
            image_config = await self._get_provider(db, "image", provider_overrides)
            if not image_config:
                raise ValueError("No image provider configured")

            api_key = image_config.api_key
            # Fallback to environment variables if not in DB
            if not api_key:
                key_map = {
                    "doubao_seedream": settings.doubao_api_key,
                    "doubao_tts": settings.doubao_api_key,
                    "dalle": settings.openai_api_key,
                    "qwen_wanx": settings.qwen_api_key,
                    "zhipu_cogview": settings.zhipu_api_key,
                    "minimax_image": settings.minimax_api_key,
                }
                api_key = key_map.get(image_config.provider_key, "")

            extra_config = json.loads(image_config.config_json) if image_config.config_json else None

            # Get model_id - use default if not set
            model_id = image_config.model_id
            if not model_id:
                try:
                    provider_cls = ProviderRegistry.get_provider_class(ProviderType.IMAGE, image_config.provider_key)
                    model_id = provider_cls.metadata.supported_models[0] if provider_cls.metadata.supported_models else ""
                except Exception:
                    pass

            # Now instantiate the provider
            image_provider = ProviderRegistry.instantiate(
                provider_type=ProviderType.IMAGE,
                key=image_config.provider_key,
                api_key=api_key,
                api_base_url=image_config.api_base_url or "",
                model_id=model_id or "",
                config=extra_config,
            )

            # Generate images for each segment
            output_dir = Path(settings.storage.base_dir) / "images" / project_id
            output_dir.mkdir(parents=True, exist_ok=True)

            for segment in segments:
                # Refresh segment to get updated image_prompt
                await db.refresh(segment)
                prompt = segment.image_prompt or segment.content[:200]

                try:
                    response = await image_provider.generate_for_segment(
                        segment_text=segment.content,
                        image_prompt=prompt,
                        aspect_ratio=project.aspect_ratio,
                        output_dir=output_dir,
                        width=project.image_width,
                        height=project.image_height,
                        quality=getattr(project, 'image_quality', 'standard') or 'standard',
                        style=getattr(project, 'image_style', 'natural') or 'natural',
                        negative_prompt=getattr(project, 'image_negative_prompt', '') or '',
                    )

                    if response.file_paths:
                        # Check if image asset already exists for this segment (take first if multiple)
                        existing = await db.execute(
                            select(ImageAsset).where(ImageAsset.segment_id == segment.id)
                        )
                        image_asset = existing.scalars().first()

                        if image_asset:
                            image_asset.file_path = str(response.file_paths[0])
                            image_asset.prompt_used = prompt
                            image_asset.provider_id = image_config.id
                            image_asset.status = "completed"
                        else:
                            image_asset = ImageAsset(
                                segment_id=segment.id,
                                project_id=project_id,
                                file_path=str(response.file_paths[0]),
                                prompt_used=prompt,
                                provider_id=image_config.id,
                                status="completed",
                            )
                            db.add(image_asset)

                except Exception as e:
                    logger.error(f"Failed to generate image for segment {segment.id}: {e}")
                    image_asset = ImageAsset(
                        segment_id=segment.id,
                        project_id=project_id,
                        file_path="",
                        prompt_used=prompt,
                        provider_id=image_config.id,
                        status="failed",
                    )
                    db.add(image_asset)

            await db.commit()

    async def regenerate_single_image(self, project_id: str, segment_id: str,
                                        custom_prompt: str | None = None):
        """Regenerate a single image for one segment, optionally with a custom prompt."""
        settings = get_settings()

        async with async_session_factory() as db:
            project = await db.get(Project, project_id)
            if not project:
                raise ValueError(f"Project {project_id} not found")

            result = await db.execute(
                select(Segment).where(Segment.id == segment_id, Segment.project_id == project_id)
            )
            segment = result.scalar_one_or_none()
            if not segment:
                raise ValueError(f"Segment {segment_id} not found")

            # If custom prompt provided, update segment's image_prompt
            if custom_prompt is not None:
                segment.image_prompt = custom_prompt
                await db.flush()

            prompt = segment.image_prompt or segment.content[:200]

            # Get image provider
            image_config = await self._get_provider(db, "image")
            if not image_config:
                raise ValueError("No image provider configured")

            api_key = image_config.api_key
            if not api_key:
                key_map = {
                    "doubao_seedream": settings.doubao_api_key,
                    "doubao_tts": settings.doubao_api_key,
                    "dalle": settings.openai_api_key,
                    "qwen_wanx": settings.qwen_api_key,
                    "zhipu_cogview": settings.zhipu_api_key,
                    "minimax_image": settings.minimax_api_key,
                }
                api_key = key_map.get(image_config.provider_key, "")

            extra_config = json.loads(image_config.config_json) if image_config.config_json else None

            model_id = image_config.model_id
            if not model_id:
                try:
                    provider_cls = ProviderRegistry.get_provider_class(ProviderType.IMAGE, image_config.provider_key)
                    model_id = provider_cls.metadata.supported_models[0] if provider_cls.metadata.supported_models else ""
                except Exception:
                    pass

            image_provider = ProviderRegistry.instantiate(
                provider_type=ProviderType.IMAGE,
                key=image_config.provider_key,
                api_key=api_key,
                api_base_url=image_config.api_base_url or "",
                model_id=model_id or "",
                config=extra_config,
            )

            output_dir = Path(settings.storage.base_dir) / "images" / project_id
            output_dir.mkdir(parents=True, exist_ok=True)

            try:
                response = await image_provider.generate_for_segment(
                    segment_text=segment.content,
                    image_prompt=prompt,
                    aspect_ratio=project.aspect_ratio,
                    output_dir=output_dir,
                    width=project.image_width,
                    height=project.image_height,
                    quality=getattr(project, 'image_quality', 'standard') or 'standard',
                    style=getattr(project, 'image_style', 'natural') or 'natural',
                    negative_prompt=getattr(project, 'image_negative_prompt', '') or '',
                )

                if response.file_paths:
                    existing = await db.execute(
                        select(ImageAsset).where(ImageAsset.segment_id == segment.id)
                    )
                    image_asset = existing.scalars().first()

                    if image_asset:
                        image_asset.file_path = str(response.file_paths[0])
                        image_asset.prompt_used = prompt
                        image_asset.provider_id = image_config.id
                        image_asset.status = "completed"
                        image_asset.is_manual = False
                    else:
                        image_asset = ImageAsset(
                            segment_id=segment.id,
                            project_id=project_id,
                            file_path=str(response.file_paths[0]),
                            prompt_used=prompt,
                            provider_id=image_config.id,
                            status="completed",
                        )
                        db.add(image_asset)

            except Exception as e:
                logger.error(f"Failed to regenerate image for segment {segment.id}: {e}")
                existing = await db.execute(
                    select(ImageAsset).where(ImageAsset.segment_id == segment.id)
                )
                image_asset = existing.scalars().first()
                if image_asset:
                    image_asset.status = "failed"
                else:
                    image_asset = ImageAsset(
                        segment_id=segment.id,
                        project_id=project_id,
                        file_path="",
                        prompt_used=prompt,
                        provider_id=image_config.id,
                        status="failed",
                    )
                    db.add(image_asset)
                await db.commit()
                raise

            await db.commit()

    async def _generate_image_prompts(self, db, segments, text_config, settings,
                                        language: str = "en"):
        """Use text provider to generate image prompts for segments."""
        api_key = text_config.api_key
        if not api_key:
            key_map = {
                "claude": settings.claude_api_key,
                "openai": settings.openai_api_key,
            }
            api_key = key_map.get(text_config.provider_key, "")

        extra_config = json.loads(text_config.config_json) if text_config.config_json else None
        text_provider = ProviderRegistry.instantiate(
            provider_type=ProviderType.TEXT,
            key=text_config.provider_key,
            api_key=api_key,
            api_base_url=text_config.api_base_url or "",
            model_id=text_config.model_id or "",
            config=extra_config,
        )

        segment_texts = [s.content for s in segments]
        prompts = await text_provider.generate_image_prompts(segment_texts, language=language)

        for segment, prompt in zip(segments, prompts):
            segment.image_prompt = prompt

        await db.flush()

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
