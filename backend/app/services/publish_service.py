"""Publish assets service - generate covers and copy for multiple platforms."""

import io
import json
import logging
import uuid
from pathlib import Path

from PIL import Image, ImageFilter
from sqlalchemy import select

from ..config import get_settings
from ..database import async_session_factory
from ..models import Project, Article, ImageAsset, Segment, ProviderConfig, PublishAsset
from ..providers.base import ProviderType
from ..providers.registry import ProviderRegistry

logger = logging.getLogger(__name__)


class PublishService:
    """Generate platform-specific covers, titles, descriptions and tags."""

    PLATFORMS = {
        "weixin":        {"cover": (1080, 1260), "ratio": "6:7",  "title_max": 30, "desc_max": 1000, "base": "vertical"},
        "xiaohongshu":   {"cover": (1080, 1440), "ratio": "3:4",  "title_max": 20, "desc_max": 1000, "base": "vertical"},
        "douyin":        {"cover": (1080, 1920), "ratio": "9:16", "title_max": 30, "desc_max": 300,  "base": "vertical"},
        "tencent_video": {"cover": (1280, 720),  "ratio": "16:9", "title_max": 30, "desc_max": 200,  "base": "horizontal"},
        "toutiao":       {"cover": (1280, 720),  "ratio": "16:9", "title_max": 30, "desc_max": 400,  "base": "horizontal"},
    }

    async def generate_publish_assets(self, project_id: str,
                                        provider_overrides: dict[str, str] | None = None):
        """Generate covers and copy for all platforms."""
        settings = get_settings()

        async with async_session_factory() as db:
            project = await db.get(Project, project_id)
            if not project:
                raise ValueError(f"Project {project_id} not found")

            # Load article
            result = await db.execute(
                select(Article).where(Article.project_id == project_id)
            )
            article = result.scalar_one_or_none()
            if not article:
                raise ValueError(f"No article found for project {project_id}. Run article_generation first.")

            # --- 1. Generate platform copy (titles, descriptions, tags) ---
            text_config = await self._get_provider(db, "text", provider_overrides)
            if not text_config:
                raise ValueError("No text provider configured")

            platform_copy = await self._generate_copy(text_config, settings,
                                                        article.title, article.content, project.topic)

            # --- 2. Generate cover images ---
            output_dir = Path(settings.storage.base_dir) / "covers" / project_id
            output_dir.mkdir(parents=True, exist_ok=True)

            image_config = await self._get_provider(db, "image", provider_overrides)

            vertical_path = None
            horizontal_path = None
            used_prompt = None

            if image_config:
                # Generate AI cover images
                try:
                    vertical_path, horizontal_path, used_prompt = await self._generate_cover_images(
                        image_config, settings,
                        project.topic, article.title, output_dir,
                        text_config=text_config,
                        override_prompt=project.cover_prompt,
                    )
                except Exception as e:
                    logger.error(f"Cover image generation failed: {e}")
                    # Fallback: try to use first segment image
                    vertical_path, horizontal_path = await self._fallback_segment_images(
                        db, project_id, output_dir,
                    )
            else:
                # No image provider — fallback to segment images
                logger.info("No image provider configured, using segment images for covers")
                vertical_path, horizontal_path = await self._fallback_segment_images(
                    db, project_id, output_dir,
                )

            # Save cover prompt if one was used
            if used_prompt:
                project.cover_prompt = used_prompt

            # --- 3. Derive platform covers via Pillow ---
            cover_paths = self._derive_covers(vertical_path, horizontal_path, output_dir)

            has_any_cover = any(v is not None for v in cover_paths.values())
            cover_status = "completed" if has_any_cover else "failed"

            # --- 4. Save to database ---
            for platform, spec in self.PLATFORMS.items():
                copy_data = platform_copy.get(platform, {})
                cover_path = cover_paths.get(platform)
                w, h = spec["cover"]

                # Upsert
                result = await db.execute(
                    select(PublishAsset).where(
                        PublishAsset.project_id == project_id,
                        PublishAsset.platform == platform,
                    )
                )
                asset = result.scalar_one_or_none()

                if asset:
                    asset.title = copy_data.get("title", "")
                    asset.description = copy_data.get("description", "")
                    asset.tags = copy_data.get("tags", "")
                    asset.cover_path = str(cover_path) if cover_path else None
                    asset.cover_width = w if cover_path else None
                    asset.cover_height = h if cover_path else None
                    asset.status = "completed"
                    asset.cover_status = cover_status if cover_path else "failed"
                else:
                    asset = PublishAsset(
                        project_id=project_id,
                        platform=platform,
                        title=copy_data.get("title", ""),
                        description=copy_data.get("description", ""),
                        tags=copy_data.get("tags", ""),
                        cover_path=str(cover_path) if cover_path else None,
                        cover_width=w if cover_path else None,
                        cover_height=h if cover_path else None,
                        status="completed",
                        cover_status=cover_status if cover_path else "failed",
                    )
                    db.add(asset)

            await db.commit()
            logger.info(f"Generated publish assets for {len(self.PLATFORMS)} platforms")

    async def regenerate_covers(self, project_id: str, custom_prompt: str | None = None):
        """Regenerate cover images independently of text copy."""
        logger.info(f"Regenerating covers for project {project_id}")
        settings = get_settings()

        try:
            async with async_session_factory() as db:
                project = await db.get(Project, project_id)
                if not project:
                    raise ValueError(f"Project {project_id} not found")

                # Mark all assets as generating
                result = await db.execute(
                    select(PublishAsset).where(PublishAsset.project_id == project_id)
                )
                for asset in result.scalars().all():
                    asset.cover_status = "generating"
                await db.commit()

            # Run generation in a new session
            async with async_session_factory() as db:
                project = await db.get(Project, project_id)

                # Load article for topic/title context
                result = await db.execute(
                    select(Article).where(Article.project_id == project_id)
                )
                article = result.scalar_one_or_none()
                topic = project.topic
                title = article.title if article else project.title

                output_dir = Path(settings.storage.base_dir) / "covers" / project_id
                output_dir.mkdir(parents=True, exist_ok=True)

                image_config = await self._get_provider(db, "image")
                if not image_config:
                    raise ValueError("No image provider configured. Please add an image provider first.")

                # Determine prompt: custom > existing > generate via LLM
                prompt_to_use = custom_prompt
                text_config = None
                if not prompt_to_use:
                    text_config = await self._get_provider(db, "text")

                vertical_path, horizontal_path, used_prompt = await self._generate_cover_images(
                    image_config, settings,
                    topic, title, output_dir,
                    text_config=text_config,
                    override_prompt=prompt_to_use,
                )

                # Save prompt
                if used_prompt:
                    project.cover_prompt = used_prompt

                # Derive platform covers
                cover_paths = self._derive_covers(vertical_path, horizontal_path, output_dir)

                # Update DB
                for platform, spec in self.PLATFORMS.items():
                    cover_path = cover_paths.get(platform)
                    w, h = spec["cover"]

                    result = await db.execute(
                        select(PublishAsset).where(
                            PublishAsset.project_id == project_id,
                            PublishAsset.platform == platform,
                        )
                    )
                    asset = result.scalar_one_or_none()
                    if asset:
                        asset.cover_path = str(cover_path) if cover_path else None
                        asset.cover_width = w if cover_path else None
                        asset.cover_height = h if cover_path else None
                        asset.cover_status = "completed" if cover_path else "failed"

                await db.commit()
                logger.info(f"Regenerated covers for project {project_id}")

        except Exception as e:
            logger.error(f"Cover regeneration failed: {e}", exc_info=True)
            # Mark all as failed
            try:
                async with async_session_factory() as db:
                    result = await db.execute(
                        select(PublishAsset).where(PublishAsset.project_id == project_id)
                    )
                    for asset in result.scalars().all():
                        asset.cover_status = "failed"
                    await db.commit()
            except Exception:
                logger.error("Failed to mark covers as failed", exc_info=True)

    async def regenerate_from_segment(self, project_id: str, segment_id: str):
        """Re-derive covers from a segment image instead of AI-generated base."""
        settings = get_settings()

        async with async_session_factory() as db:
            # Mark all as generating first
            result = await db.execute(
                select(PublishAsset).where(PublishAsset.project_id == project_id)
            )
            for asset in result.scalars().all():
                asset.cover_status = "generating"
            await db.commit()

        try:
            async with async_session_factory() as db:
                # Get segment image
                result = await db.execute(
                    select(ImageAsset).where(
                        ImageAsset.segment_id == segment_id,
                        ImageAsset.project_id == project_id,
                        ImageAsset.status == "completed",
                    )
                )
                image_asset = result.scalar_one_or_none()
                if not image_asset or not image_asset.file_path:
                    raise ValueError(f"No completed image for segment {segment_id}")

                output_dir = Path(settings.storage.base_dir) / "covers" / project_id
                output_dir.mkdir(parents=True, exist_ok=True)

                src_path = Path(image_asset.file_path)
                if not src_path.exists():
                    raise ValueError(f"Image file not found: {src_path}")

                # Copy and resize as base images
                vertical_path, horizontal_path = self._prepare_bases_from_source(
                    src_path, output_dir,
                )

                # Re-derive all covers
                cover_paths = self._derive_covers(vertical_path, horizontal_path, output_dir)

                # Update DB
                for platform, spec in self.PLATFORMS.items():
                    cover_path = cover_paths.get(platform)
                    w, h = spec["cover"]

                    result = await db.execute(
                        select(PublishAsset).where(
                            PublishAsset.project_id == project_id,
                            PublishAsset.platform == platform,
                        )
                    )
                    asset = result.scalar_one_or_none()
                    if asset:
                        asset.cover_path = str(cover_path) if cover_path else None
                        asset.cover_width = w if cover_path else None
                        asset.cover_height = h if cover_path else None
                        asset.cover_status = "completed" if cover_path else "failed"

                await db.commit()
                logger.info(f"Re-derived covers from segment {segment_id}")

        except Exception as e:
            logger.error(f"Segment cover regeneration failed: {e}")
            async with async_session_factory() as db:
                result = await db.execute(
                    select(PublishAsset).where(PublishAsset.project_id == project_id)
                )
                for asset in result.scalars().all():
                    asset.cover_status = "failed"
                await db.commit()
            raise

    async def handle_cover_upload(self, project_id: str, platform: str,
                                    file_content: bytes, filename: str):
        """Upload and resize a custom cover for a specific platform."""
        settings = get_settings()
        spec = self.PLATFORMS.get(platform)
        if not spec:
            raise ValueError(f"Invalid platform: {platform}")

        w, h = spec["cover"]
        output_dir = Path(settings.storage.base_dir) / "covers" / project_id
        output_dir.mkdir(parents=True, exist_ok=True)

        # Open and resize uploaded image
        try:
            img = Image.open(io.BytesIO(file_content)).convert("RGB")
        except Exception as e:
            raise ValueError(f"Cannot open uploaded image: {e}")

        resized = self._center_crop_resize(img, w, h)
        out_path = output_dir / f"{platform}_{w}x{h}.png"
        resized.save(str(out_path), "PNG")

        # Update DB
        async with async_session_factory() as db:
            result = await db.execute(
                select(PublishAsset).where(
                    PublishAsset.project_id == project_id,
                    PublishAsset.platform == platform,
                )
            )
            asset = result.scalar_one_or_none()
            if asset:
                asset.cover_path = str(out_path)
                asset.cover_width = w
                asset.cover_height = h
                asset.cover_status = "completed"
            else:
                asset = PublishAsset(
                    project_id=project_id,
                    platform=platform,
                    cover_path=str(out_path),
                    cover_width=w,
                    cover_height=h,
                    cover_status="completed",
                    status="completed",
                )
                db.add(asset)

            await db.commit()
            logger.info(f"Uploaded cover for {platform}: {out_path}")

    # ---- Internal methods ----

    async def _generate_copy(self, text_config: ProviderConfig, settings,
                               title: str, article: str, topic: str) -> dict[str, dict]:
        """Call text provider to generate platform copy."""
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

        return await text_provider.generate_publish_copy(title, article, topic)

    async def _generate_cover_images(self, image_config, settings,
                                       topic: str, title: str,
                                       output_dir: Path,
                                       text_config=None,
                                       override_prompt: str | None = None,
                                       ) -> tuple[Path | None, Path | None, str]:
        """Generate vertical (3:4) and horizontal (16:9) cover base images.

        Returns (vertical_path, horizontal_path, prompt_used).
        """
        # Get image provider
        api_key_img = image_config.api_key
        if not api_key_img:
            key_map = {
                "doubao_seedream": settings.doubao_api_key,
                "dalle": settings.openai_api_key,
                "qwen_wanx": settings.qwen_api_key,
                "zhipu_cogview": settings.zhipu_api_key,
                "minimax_image": settings.minimax_api_key,
            }
            api_key_img = key_map.get(image_config.provider_key, "")

        extra_config_img = json.loads(image_config.config_json) if image_config.config_json else None
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
            api_key=api_key_img,
            api_base_url=image_config.api_base_url or "",
            model_id=model_id or "",
            config=extra_config_img,
        )

        # Determine the base prompt
        base_prompt = override_prompt
        if not base_prompt and text_config:
            # Generate prompt via text provider
            api_key_text = text_config.api_key
            if not api_key_text:
                key_map = {"claude": settings.claude_api_key, "openai": settings.openai_api_key}
                api_key_text = key_map.get(text_config.provider_key, "")

            extra_config_text = json.loads(text_config.config_json) if text_config.config_json else None
            text_provider = ProviderRegistry.instantiate(
                provider_type=ProviderType.TEXT,
                key=text_config.provider_key,
                api_key=api_key_text,
                api_base_url=text_config.api_base_url or "",
                model_id=text_config.model_id or "",
                config=extra_config_text,
            )
            base_prompt = await text_provider.generate_cover_prompt(topic, title, "3:4")

        if not base_prompt:
            # Last resort: construct a simple prompt
            base_prompt = f"Modern health science cover image about: {topic}. Bright, clean, professional design, no text, no faces."

        vertical_path = None
        horizontal_path = None

        # Generate vertical cover (9:16 → crop to 3:4)
        # Note: don't pass explicit width/height — let the provider use its
        # minimum-compliant dimensions (e.g., Seedream needs ≥3,686,400 pixels).
        # We'll resize the result to 1080x1440 afterward.
        try:
            vert_prompt = base_prompt + ", vertical portrait composition"
            logger.info(f"Generating vertical cover: {vert_prompt[:80]}...")
            vert_response = await image_provider.generate_for_segment(
                segment_text=topic,
                image_prompt=vert_prompt,
                aspect_ratio="9:16",
                output_dir=output_dir,
                quality="hd",
                style="natural",
                negative_prompt="text, watermark, logo, words, letters",
            )
            if vert_response.file_paths:
                src = Path(vert_response.file_paths[0])
                dest = output_dir / "base_vertical.png"
                # Resize from high-res 9:16 to 1080x1440 (3:4) via center-crop
                img = Image.open(src).convert("RGB")
                resized = self._center_crop_resize(img, 1080, 1440)
                resized.save(str(dest), "PNG")
                if src != dest:
                    src.unlink(missing_ok=True)
                vertical_path = dest
                logger.info(f"Generated vertical cover base: {dest}")
        except Exception as e:
            logger.error(f"Failed to generate vertical cover: {e}", exc_info=True)

        # Generate horizontal cover (16:9 → resize to 1280x720)
        try:
            horiz_prompt = base_prompt + ", horizontal widescreen landscape composition"
            logger.info(f"Generating horizontal cover: {horiz_prompt[:80]}...")
            horiz_response = await image_provider.generate_for_segment(
                segment_text=topic,
                image_prompt=horiz_prompt,
                aspect_ratio="16:9",
                output_dir=output_dir,
                quality="hd",
                style="natural",
                negative_prompt="text, watermark, logo, words, letters",
            )
            if horiz_response.file_paths:
                src = Path(horiz_response.file_paths[0])
                dest = output_dir / "base_horizontal.png"
                # Resize from high-res 16:9 to 1280x720
                img = Image.open(src).convert("RGB")
                resized = img.resize((1280, 720), Image.LANCZOS)
                resized.save(str(dest), "PNG")
                if src != dest:
                    src.unlink(missing_ok=True)
                horizontal_path = dest
                logger.info(f"Generated horizontal cover base: {dest}")
        except Exception as e:
            logger.error(f"Failed to generate horizontal cover: {e}", exc_info=True)

        return vertical_path, horizontal_path, base_prompt

    async def _fallback_segment_images(self, db, project_id: str,
                                         output_dir: Path) -> tuple[Path | None, Path | None]:
        """Use first segment image as cover fallback."""
        result = await db.execute(
            select(ImageAsset).where(
                ImageAsset.project_id == project_id,
                ImageAsset.status == "completed",
            ).order_by(ImageAsset.created_at)
        )
        first_image = result.scalars().first()
        if not first_image or not first_image.file_path:
            return None, None

        src_path = Path(first_image.file_path)
        if not src_path.exists():
            return None, None

        return self._prepare_bases_from_source(src_path, output_dir)

    def _prepare_bases_from_source(self, src_path: Path,
                                     output_dir: Path) -> tuple[Path | None, Path | None]:
        """Create vertical and horizontal base images from a source image."""
        try:
            img = Image.open(src_path).convert("RGB")
        except Exception as e:
            logger.error(f"Cannot open image {src_path}: {e}")
            return None, None

        vertical_path = output_dir / "base_vertical.png"
        horizontal_path = output_dir / "base_horizontal.png"

        # Create vertical base (3:4 = 1080x1440)
        vert = self._center_crop_resize(img, 1080, 1440)
        vert.save(str(vertical_path), "PNG")

        # Create horizontal base (16:9 = 1280x720)
        horiz = self._center_crop_resize(img, 1280, 720)
        horiz.save(str(horizontal_path), "PNG")

        return vertical_path, horizontal_path

    def _derive_covers(self, vertical_path: Path | None, horizontal_path: Path | None,
                        output_dir: Path) -> dict[str, Path | None]:
        """Derive platform-specific covers from base images."""
        covers: dict[str, Path | None] = {}

        vert_img = None
        horiz_img = None

        if vertical_path and vertical_path.exists():
            vert_img = Image.open(vertical_path).convert("RGB")
        if horizontal_path and horizontal_path.exists():
            horiz_img = Image.open(horizontal_path).convert("RGB")

        for platform, spec in self.PLATFORMS.items():
            w, h = spec["cover"]
            base_type = spec["base"]
            out_path = output_dir / f"{platform}_{w}x{h}.png"

            base_img = vert_img if base_type == "vertical" else horiz_img

            if base_img is None:
                # Try the other base as fallback
                base_img = horiz_img if base_type == "vertical" else vert_img

            if base_img is None:
                covers[platform] = None
                continue

            try:
                if platform == "douyin" and vert_img is not None:
                    # 9:16 from 3:4: need to extend height with blurred fill
                    derived = self._extend_with_blur(vert_img, w, h)
                else:
                    derived = self._center_crop_resize(base_img, w, h)

                derived.save(str(out_path), "PNG")
                covers[platform] = out_path
            except Exception as e:
                logger.error(f"Failed to derive cover for {platform}: {e}")
                covers[platform] = None

        return covers

    @staticmethod
    def _center_crop_resize(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
        """Center-crop image to target aspect ratio, then resize."""
        src_w, src_h = img.size
        target_ratio = target_w / target_h
        src_ratio = src_w / src_h

        if src_ratio > target_ratio:
            # Source is wider — crop sides
            new_w = int(src_h * target_ratio)
            left = (src_w - new_w) // 2
            cropped = img.crop((left, 0, left + new_w, src_h))
        else:
            # Source is taller — crop top/bottom
            new_h = int(src_w / target_ratio)
            top = (src_h - new_h) // 2
            cropped = img.crop((0, top, src_w, top + new_h))

        return cropped.resize((target_w, target_h), Image.LANCZOS)

    @staticmethod
    def _extend_with_blur(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
        """Extend image to target size by filling extra space with blurred version.

        Used for 3:4 → 9:16 conversion (抖音 covers).
        """
        # Create blurred background at target size
        bg = img.resize((target_w, target_h), Image.LANCZOS)
        bg = bg.filter(ImageFilter.GaussianBlur(radius=30))

        # Resize source to fit width, preserving aspect ratio
        src_ratio = img.width / img.height
        fit_w = target_w
        fit_h = int(fit_w / src_ratio)

        if fit_h > target_h:
            fit_h = target_h
            fit_w = int(fit_h * src_ratio)

        resized = img.resize((fit_w, fit_h), Image.LANCZOS)

        # Center paste
        x = (target_w - fit_w) // 2
        y = (target_h - fit_h) // 2
        bg.paste(resized, (x, y))

        return bg

    async def _get_provider(self, db, provider_type: str,
                             overrides: dict[str, str] | None = None) -> ProviderConfig | None:
        """Get provider config (same pattern as ImageService)."""
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

        from .provider_helper import get_provider_from_env
        config = await get_provider_from_env(db, provider_type)
        if config:
            return config

        from .provider_helper import get_first_provider
        return await get_first_provider(db, provider_type)
