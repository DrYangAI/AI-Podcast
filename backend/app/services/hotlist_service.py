"""Hot topic recommendation service — scrape + AI filter."""

import json
import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import async_session_factory
from ..models import ProviderConfig
from ..providers.base import ProviderType
from ..providers.registry import ProviderRegistry
from ..providers.text.base import TextGenerationRequest
from ..config import get_settings
from ..utils.hotlist_scraper import HotTopic, scrape_hotlists, SOURCE_NAMES

logger = logging.getLogger(__name__)


@dataclass
class HealthTopicRecommendation:
    title: str
    source: str
    source_name: str
    url: str | None
    rank: int
    heat: str
    relevance_score: float
    health_angle: str
    category: str


class HotlistService:
    """Scrape hot topics and filter health-relevant ones using AI."""

    async def get_health_recommendations(
        self,
        sources: list[str] | None = None,
        max_results: int = 15,
        provider_id: str | None = None,
        mode: str = "health",
    ) -> tuple[list[HealthTopicRecommendation], int]:
        """Scrape hot topics and filter health-related ones.

        Returns (recommendations, total_scraped_count).
        """
        # Step 1: Scrape
        all_topics = await scrape_hotlists(sources)

        flat_topics: list[HotTopic] = []
        for topics in all_topics.values():
            flat_topics.extend(topics)

        if not flat_topics:
            return [], 0

        # Step 2: AI filtering
        from .prompt_template_service import PromptTemplateService

        template_key = "psychology_filtering" if mode == "psychology" else "hotlist_filtering"

        async with async_session_factory() as db:
            provider_config = await self._get_text_provider(db, provider_id=provider_id)
            settings = get_settings()
            text_provider = self._instantiate_provider(provider_config, settings)
            prompt_config = await PromptTemplateService.resolve(db, template_key)

        if not prompt_config:
            raise ValueError("未找到热榜筛选提示词模板，请检查系统配置。")

        topic_lines = "\n".join(
            f"{i + 1}. [{t.source}] {t.title}"
            for i, t in enumerate(flat_topics)
        )

        target_count = min(max_results * 2, len(flat_topics))

        try:
            prompt = prompt_config.user_prompt_template.format(
                topic_lines=topic_lines,
                target_count=target_count,
            )
        except KeyError as e:
            logger.warning("Template variable error: %s, using raw template", e)
            prompt = prompt_config.user_prompt_template

        response = await text_provider.generate(TextGenerationRequest(
            prompt=prompt,
            system_prompt=prompt_config.system_prompt,
            temperature=prompt_config.temperature,
            max_tokens=prompt_config.max_tokens,
        ))

        # Step 3: Parse AI response
        recommendations = self._parse_ai_response(response.content, flat_topics)
        recommendations.sort(key=lambda r: r.relevance_score, reverse=True)
        return recommendations[:max_results], len(flat_topics)

    @staticmethod
    def _try_fix_truncated_json(text: str) -> list | None:
        """Attempt to recover items from a truncated JSON array."""
        import re
        # Find all complete JSON objects in the text
        results = []
        for m in re.finditer(r'\{[^{}]*\}', text):
            try:
                obj = json.loads(m.group(0))
                if "index" in obj:
                    results.append(obj)
            except json.JSONDecodeError:
                continue
        if results:
            logger.info("Recovered %d items from truncated JSON", len(results))
            return results
        return None

    @staticmethod
    def _extract_json_array(text: str) -> str | None:
        """Try to extract a JSON array from text that may contain extra content."""
        import re
        # 1. Try the whole text directly
        stripped = text.strip()
        if stripped.startswith("["):
            return stripped

        # 2. Strip markdown code blocks (```json ... ``` or ``` ... ```)
        md_match = re.search(r"```(?:json)?\s*\n?(.*?)```", stripped, re.DOTALL)
        if md_match:
            return md_match.group(1).strip()

        # 3. Find the first [ ... ] block
        bracket_match = re.search(r"\[.*\]", stripped, re.DOTALL)
        if bracket_match:
            return bracket_match.group(0)

        return None

    def _parse_ai_response(
        self,
        ai_content: str,
        flat_topics: list[HotTopic],
    ) -> list[HealthTopicRecommendation]:
        """Parse the AI JSON response and map back to original topics."""
        content = self._extract_json_array(ai_content)
        if not content:
            logger.error("No JSON array found in AI response: %s", ai_content[:300])
            return []

        try:
            items = json.loads(content)
        except json.JSONDecodeError:
            # Try to fix truncated JSON: find the last complete object and close the array
            items = self._try_fix_truncated_json(content)
            if items is None:
                logger.error("Failed to parse AI response as JSON: %s", content[:300])
                return []

        if not isinstance(items, list):
            return []

        results = []
        for item in items:
            idx = item.get("index", 0) - 1  # 1-based to 0-based
            if idx < 0 or idx >= len(flat_topics):
                continue

            topic = flat_topics[idx]
            results.append(HealthTopicRecommendation(
                title=topic.title,
                source=topic.source,
                source_name=SOURCE_NAMES.get(topic.source, topic.source),
                url=topic.url,
                rank=topic.rank,
                heat=topic.heat,
                relevance_score=min(1.0, max(0.0, float(item.get("relevance", 0.5)))),
                health_angle=item.get("angle", ""),
                category=item.get("category", ""),
            ))

        return results

    async def _get_text_provider(self, db: AsyncSession, provider_id: str | None = None) -> ProviderConfig | None:
        """Resolve text provider using the same chain as ArticleService."""
        from .provider_helper import get_provider_from_env, get_first_provider

        # If a specific provider is requested, use it directly
        if provider_id:
            config = await db.get(ProviderConfig, provider_id)
            if config:
                return config

        # Try DB default
        result = await db.execute(
            select(ProviderConfig)
            .where(ProviderConfig.provider_type == "text", ProviderConfig.is_default == True)
        )
        config = result.scalar_one_or_none()
        if config:
            return config

        config = await get_provider_from_env(db, "text")
        if config:
            return config

        return await get_first_provider(db, "text")

    def _instantiate_provider(self, config: ProviderConfig | None, settings):
        """Create a provider instance from config."""
        if not config:
            raise ValueError("未配置文本AI模型，请先在设置中添加。")

        extra_config = json.loads(config.config_json) if config.config_json else None
        api_key = config.api_key

        if not api_key:
            key_map = {
                "claude": settings.claude_api_key,
                "openai": settings.openai_api_key,
                "deepseek": settings.deepseek_api_key,
                "doubao": settings.doubao_api_key,
                "qwen": settings.qwen_api_key,
                "zhipu": settings.zhipu_api_key,
                "minimax": settings.minimax_api_key,
                "wenxin": settings.wenxin_api_key,
                "moonshot": settings.moonshot_api_key,
                "stepfun": settings.stepfun_api_key,
                "siliconflow": settings.siliconflow_api_key,
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
