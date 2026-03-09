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
        async with async_session_factory() as db:
            provider_config = await self._get_text_provider(db)
            settings = get_settings()
            text_provider = self._instantiate_provider(provider_config, settings)

        topic_lines = "\n".join(
            f"{i + 1}. [{t.source}] {t.title}"
            for i, t in enumerate(flat_topics)
        )

        prompt = (
            f"以下是当前中文互联网热门话题列表：\n\n"
            f"{topic_lines}\n\n"
            f"请从中筛选出与健康、医疗、养生、营养、心理健康、运动健身、"
            f"疾病预防、食品安全、睡眠、母婴健康等健康领域相关的话题。\n\n"
            f"对于每个健康相关话题，请输出 JSON 数组，每个元素包含：\n"
            f'- "index": 话题在列表中的序号（从1开始）\n'
            f'- "relevance": 与健康领域的相关度（0.0-1.0）\n'
            f'- "angle": 建议的健康科普切入角度（一句话）\n'
            f'- "category": 健康分类（如：营养饮食、心理健康、运动健身、'
            f"疾病预防、中医养生、食品安全、睡眠健康、母婴健康等）\n\n"
            f"只输出 JSON 数组，不要其他文字。如果没有健康相关话题则输出空数组 []。\n"
            f"示例格式：\n"
            f'[{{"index": 3, "relevance": 0.9, "angle": "从营养学角度解读该食品的健康影响", '
            f'"category": "营养饮食"}}]'
        )

        system_prompt = (
            "你是一位健康科普领域的编辑，擅长从热门话题中发现健康科普创作机会。"
            "你的任务是筛选与健康相关的话题，并给出创作建议。只输出JSON，不要输出其他内容。"
        )

        response = await text_provider.generate(TextGenerationRequest(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=0.3,
            max_tokens=2048,
        ))

        # Step 3: Parse AI response
        recommendations = self._parse_ai_response(response.content, flat_topics)
        recommendations.sort(key=lambda r: r.relevance_score, reverse=True)
        return recommendations[:max_results], len(flat_topics)

    def _parse_ai_response(
        self,
        ai_content: str,
        flat_topics: list[HotTopic],
    ) -> list[HealthTopicRecommendation]:
        """Parse the AI JSON response and map back to original topics."""
        content = ai_content.strip()
        # Handle markdown code blocks
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1]) if len(lines) > 2 else content

        try:
            items = json.loads(content)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse AI response as JSON: {content[:200]}")
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

    async def _get_text_provider(self, db: AsyncSession) -> ProviderConfig | None:
        """Resolve text provider using the same chain as ArticleService."""
        from .provider_helper import get_provider_from_env, get_first_provider

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
