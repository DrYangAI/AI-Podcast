"""Audio service - TTS generation and manual upload handling."""

import json
import logging
import re
from pathlib import Path

from sqlalchemy import select

from ..database import async_session_factory
from ..models import Project, Script, AudioAsset, ProviderConfig
from ..providers.base import ProviderType
from ..providers.registry import ProviderRegistry
from ..config import get_settings

logger = logging.getLogger(__name__)


def clean_script_for_tts(text: str) -> str:
    """Remove annotations, markdown formatting, and other non-speech content
    from the script before sending to TTS.

    Cleans:
    - Stage direction annotations in Chinese parentheses: （轻松、亲切的开场）
    - Stage direction annotations in regular parentheses: (轻松开场)
    - Markdown bold/italic markers: **text** / *text*
    - Markdown headings: # / ## / ###
    - Extra whitespace and blank lines
    """
    # Remove annotations in Chinese parentheses （...）
    text = re.sub(r'[（(][^）)]*?[的地]?(?:开场白?|语气|口吻|过渡|结尾|总结|转折|停顿|感叹|强调)[^）)]*?[）)]', '', text)
    # Broader: remove any Chinese parenthetical that looks like a stage direction
    # (contains descriptive words like 轻松、亲切、认真 etc.)
    text = re.sub(r'[（(][\u4e00-\u9fff、，\s]{2,20}[）)]', '', text)

    # Remove markdown bold/italic markers (keep the text inside)
    text = re.sub(r'\*{1,3}(.+?)\*{1,3}', r'\1', text)

    # Remove markdown heading markers
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)

    # Remove markdown bullet points (- or *)
    text = re.sub(r'^\s*[-*]\s+', '', text, flags=re.MULTILINE)

    # Clean up extra blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


class AudioService:
    """Handles TTS audio generation and manual audio upload."""

    async def generate_tts(self, project_id: str,
                            provider_overrides: dict[str, str] | None = None):
        """Generate TTS audio from the project's script."""
        settings = get_settings()

        async with async_session_factory() as db:
            result = await db.execute(select(Script).where(Script.project_id == project_id))
            script = result.scalar_one_or_none()
            if not script:
                raise ValueError(f"No script found for project {project_id}")

            # Get TTS provider
            tts_config = await self._get_provider(db, "tts", provider_overrides)
            if not tts_config:
                raise ValueError("No TTS provider configured")

            api_key = tts_config.api_key
            if not api_key:
                key_map = {
                    "openai_tts": settings.openai_api_key,
                    "elevenlabs": settings.elevenlabs_api_key,
                    "doubao_tts": settings.doubao_api_key,
                    "minimax_tts": settings.minimax_api_key,
                }
                api_key = key_map.get(tts_config.provider_key, "")

            extra_config = json.loads(tts_config.config_json) if tts_config.config_json else None
            tts_provider = ProviderRegistry.instantiate(
                provider_type=ProviderType.TTS,
                key=tts_config.provider_key,
                api_key=api_key,
                api_base_url=tts_config.api_base_url or "",
                model_id=tts_config.model_id or "",
                config=extra_config,
            )

            # Generate audio
            output_dir = Path(settings.storage.base_dir) / "audio" / project_id
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / "speech.mp3"

            voice_id = extra_config.get("voice", "") if extra_config else ""

            # Clean script text: remove annotations and markdown formatting
            clean_text = clean_script_for_tts(script.content)
            logger.info("Cleaned script for TTS: removed %d chars of annotations/formatting",
                        len(script.content) - len(clean_text))

            response = await tts_provider.synthesize_script(
                script=clean_text,
                voice_id=voice_id,
                output_path=output_path,
            )

            # Save or update audio asset
            result = await db.execute(select(AudioAsset).where(AudioAsset.project_id == project_id))
            audio = result.scalar_one_or_none()

            if audio:
                audio.file_path = str(response.file_path)
                audio.duration = response.duration
                audio.sample_rate = response.sample_rate
                audio.provider_id = tts_config.id
                audio.voice_id = voice_id
                audio.is_manual = False
                audio.status = "completed"
            else:
                audio = AudioAsset(
                    project_id=project_id,
                    file_path=str(response.file_path),
                    duration=response.duration,
                    sample_rate=response.sample_rate,
                    provider_id=tts_config.id,
                    voice_id=voice_id,
                    is_manual=False,
                    status="completed",
                )
                db.add(audio)

            await db.commit()
            return audio

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
