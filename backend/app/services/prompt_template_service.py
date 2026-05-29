"""Prompt template service - seeding, CRUD, resolution."""

import json
import logging
from dataclasses import dataclass

from sqlalchemy import select, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.prompt_template import PromptTemplate, PromptTemplateHistory

logger = logging.getLogger(__name__)


@dataclass
class ResolvedPromptConfig:
    """Runtime-resolved prompt configuration."""
    step_name: str
    system_prompt: str
    user_prompt_template: str
    temperature: float
    max_tokens: int
    variables: list[str]
    is_override: bool = False


# ---- Default template definitions ----

DEFAULTS = {
    "article_generation": {
        "description": "文章生成",
        "system_prompt": (
            "你是一位专业的健康科普作家,擅长将复杂的医学知识转化为通俗易懂的科普文章。\n"
            "你的文章应该:\n"
            "- 科学准确,引用可靠的医学来源\n"
            "- 通俗易懂,避免过多专业术语\n"
            "- 结构清晰,用空行分段\n"
            "- 适合大众阅读的健康科普内容\n"
            "- 输出纯文本,绝对不使用任何Markdown格式标记"
        ),
        "user_prompt_template": (
            "请围绕以下主题撰写一篇健康科普文章:\n"
            "主题: {topic}\n\n"
            "要求:\n"
            "- 字数: {min_words}-{max_words}字\n"
            "- 风格: {style}\n"
            "- 语言: {language}\n"
            "- 分成3-8个自然段落\n"
            "- 包含实用的健康建议\n"
            "- 如果提供了参考资料，必须以参考资料的核心观点为基础撰写，不得偏离原文核心思想\n"
            "- 【重要】输出纯文本,不要使用Markdown格式(不要用#标题、**加粗**、- 列表等标记)\n"
            "- 用空行分隔段落即可,不需要任何格式标记"
            "{reference_content}"
            "{user_notes}"
        ),
        "temperature": 0.7,
        "max_tokens": 4096,
        "variables": ["topic", "min_words", "max_words", "style", "language", "reference_content", "user_notes"],
    },
    "script_generation": {
        "description": "口播稿生成（整篇）",
        "system_prompt": (
            "你是一位专业的口播稿撰写专家,擅长将科普文章改写为适合口播的稿件。\n"
            "你的输出将直接发送给TTS语音合成系统朗读,因此:\n"
            "- 只输出纯文本,绝对不要使用Markdown格式(不要用**、#、-等标记)\n"
            "- 不要添加任何括号内的注释、舞台指导或情绪提示\n"
            "- 直接输出可以朗读的自然文字"
        ),
        "user_prompt_template": (
            "请将以下科普文章改写为口播稿:\n\n{article}\n\n"
            "要求:\n"
            "- 口语化表达,适合朗读\n"
            "- 保持专业性但更加亲切\n"
            "- 适当添加过渡词和语气词\n"
            "- 风格: {style}\n"
            "- 【重要】输出纯文本,不要使用任何Markdown格式(如**加粗**、# 标题、- 列表等)\n"
            "- 【重要】不要添加任何括号注释或舞台指导(如「（轻松开场）」「（停顿）」等),直接输出可朗读的文字"
        ),
        "temperature": 0.5,
        "max_tokens": 4096,
        "variables": ["article", "style"],
    },
    "segmented_script_generation": {
        "description": "口播稿生成（分段）",
        "system_prompt": (
            "你是一位专业的口播稿撰写专家,擅长将科普文章改写为适合口播的稿件。\n"
            "你的输出将直接发送给TTS语音合成系统朗读,因此:\n"
            "- 只输出纯文本,绝对不要使用Markdown格式(不要用**、#、-等标记)\n"
            "- 不要添加任何括号内的注释、舞台指导或情绪提示\n"
            "- 直接输出可以朗读的自然文字"
        ),
        "user_prompt_template": (
            "请将以下{segment_count}个内容段落分别改写为口播稿。\n\n"
            "{numbered_segments}\n\n"
            "要求:\n"
            "- 严格输出{segment_count}个段落,每个段落前用标记 {markers} 标识\n"
            "- 第一个段落需要有自然的开场（如问候听众）,最后一个段落需要有收尾总结\n"
            "- 相邻段落之间要有自然的过渡衔接\n"
            "- 口语化表达,适合朗读\n"
            "- 保持专业性但更加亲切\n"
            "- 适当添加过渡词和语气词\n"
            "- 风格: {style}\n"
            "- 【重要】输出纯文本,不要使用任何Markdown格式\n"
            "- 【重要】不要添加任何括号注释或舞台指导,直接输出可朗读的文字"
        ),
        "temperature": 0.5,
        "max_tokens": 8192,
        "variables": ["segment_count", "numbered_segments", "markers", "style"],
    },
    "image_prompt_generation": {
        "description": "图片提示词生成",
        "system_prompt": "你是一位AI绘画提示词专家。请为每个段落生成适合的图片描述提示词。",
        "user_prompt_template": (
            "请为以下每个段落生成一个用于AI绘图的{lang_label}:\n\n{numbered_segments}\n\n"
            "要求:\n"
            "- {lang_instruction}\n"
            "- 风格: 专业医学科普插图,现代扁平风格\n"
            "- 避免出现人脸特写\n"
            "- 如果画面中需要出现文字或标注,请确保文字内容准确无误,使用简体中文\n"
            "- 【重要】构图要求: {ratio_hint}\n"
            "- 每个提示词中必须明确描述画面元素的空间布局方向\n"
            "- 用 [PROMPT_1], [PROMPT_2]... 标记每个提示词"
        ),
        "temperature": 0.6,
        "max_tokens": 8192,
        "variables": ["lang_label", "numbered_segments", "lang_instruction", "ratio_hint"],
    },
    "publish_copy": {
        "description": "发布文案生成",
        "system_prompt": (
            "你是一位资深的短视频运营专家,精通微信视频号、小红书、抖音、腾讯视频和今日头条的内容运营。\n"
            "你擅长撰写高点击率的标题和摘要,了解各平台的用户特点和推荐算法偏好。\n"
            "请严格按照指定格式输出,每个平台一个[PLATFORM_xxx]区块。"
        ),
        "user_prompt_template": (
            "请根据以下健康科普视频内容,为5个平台生成爆款标题、摘要和标签。\n\n"
            "视频主题: {topic}\n"
            "文章标题: {title}\n"
            "文章内容:\n{article_excerpt}\n\n"
            "为以下每个平台各生成一组:\n\n"
            "1. 微信视频号(weixin) - 标题≤30字, 摘要≤1000字\n"
            "2. 小红书(xiaohongshu) - 标题≤20字, 摘要200-600字, 种草风格, 适当使用emoji\n"
            "3. 抖音(douyin) - 标题≤30字, 摘要≤300字, 短视频风格\n"
            "4. 腾讯视频(tencent_video) - 标题10-30字, 摘要≤200字, 正式风格\n"
            "5. 今日头条(toutiao) - 标题≤30字, 摘要≤400字, 不要夸张\n\n"
            "要求:\n"
            "- 标题要有吸引力,能引发点击\n"
            "- 摘要要包含核心信息,引发观看欲望\n"
            "- 每个平台生成3-5个推荐标签(带#号)\n"
            "- 不同平台的标题和摘要风格要有差异,符合各平台用户习惯\n\n"
            "请严格按以下格式输出(每个平台一个区块):\n\n"
            "[PLATFORM_weixin]\ntitle: 标题内容\ndescription: 摘要内容\ntags: #标签1 #标签2 #标签3\n\n"
            "[PLATFORM_xiaohongshu]\ntitle: 标题内容\ndescription: 摘要内容\ntags: #标签1 #标签2 #标签3\n\n"
            "[PLATFORM_douyin]\ntitle: 标题内容\ndescription: 摘要内容\ntags: #标签1 #标签2 #标签3\n\n"
            "[PLATFORM_tencent_video]\ntitle: 标题内容\ndescription: 摘要内容\ntags: #标签1 #标签2 #标签3\n\n"
            "[PLATFORM_toutiao]\ntitle: 标题内容\ndescription: 摘要内容\ntags: #标签1 #标签2 #标签3"
        ),
        "temperature": 0.7,
        "max_tokens": 4096,
        "variables": ["topic", "title", "article_excerpt"],
    },
    "cover_prompt": {
        "description": "封面提示词生成",
        "system_prompt": "你是一位AI绘画提示词专家,擅长设计短视频封面。只输出英文提示词。",
        "user_prompt_template": (
            "请为以下健康科普短视频生成一个封面背景图的AI绘图提示词:\n\n"
            "视频主题: {topic}\n"
            "视频标题: {title}\n\n"
            "要求:\n"
            "- 使用英文提示词\n"
            "- 画面明亮、专业、现代感强\n"
            "- 适合健康/医学科普类视频封面\n"
            "- 色彩鲜明,视觉冲击力强\n"
            "- 不包含任何文字\n"
            "- {ratio_hint}\n"
            "- 避免出现人脸特写\n"
            "- 只输出提示词本身,不要任何额外说明"
        ),
        "temperature": 0.6,
        "max_tokens": 4096,
        "variables": ["topic", "title", "ratio_hint"],
    },
    "content_splitting": {
        "description": "内容切分配置",
        "system_prompt": "",
        "user_prompt_template": "",
        "temperature": 0.0,
        "max_tokens": 0,
        "variables": [],
        "extra_config": {"split_method": "paragraph", "min_paragraph_length": 10},
    },
    "hotlist_filtering": {
        "description": "热榜健康话题筛选",
        "system_prompt": (
            "你是一位健康科普自媒体的选题编辑，擅长蹭热点做健康科普。"
            "你的核心能力是把任何热门话题和健康知识巧妙结合，找到创作角度。"
            "筛选要宽松，宁可多选也不要漏掉潜在的好选题。只输出JSON，不要输出其他内容。"
        ),
        "user_prompt_template": (
            "以下是当前中文互联网热门话题列表：\n\n"
            "{topic_lines}\n\n"
            "请从中挑选可以和健康科普结合的话题。筛选标准要宽松：\n"
            "1. 直接相关：医疗、疾病、养生、营养、心理健康、运动、食品安全、睡眠、母婴等\n"
            "2. 间接相关：任何能和健康挂钩的社会新闻、生活方式、季节时令、食品饮品、"
            "明星/运动员（可聊运动健康）、天气气候（可聊防护保健）、职场压力（可聊心理健康）等\n"
            "3. 蹭热点型：即使话题本身与健康无直接关系，但可以巧妙结合健康角度做科普的也算\n\n"
            "尽量多选，目标是找出 {target_count} 个左右的话题。\n\n"
            "对于每个话题，请输出 JSON 数组，每个元素包含：\n"
            '- "index": 话题在列表中的序号（从1开始）\n'
            '- "relevance": 与健康领域的相关度（0.0-1.0，直接相关>0.7，间接相关0.4-0.7，蹭热点0.2-0.4）\n'
            '- "angle": 建议的健康科普切入角度（一句话，要具体且有吸引力）\n'
            '- "category": 健康分类（如：营养饮食、心理健康、运动健身、'
            "疾病预防、中医养生、食品安全、睡眠健康、母婴健康、生活方式、职场健康、"
            "季节养生、热点科普等）\n\n"
            "只输出 JSON 数组，不要其他文字。\n"
            "示例格式：\n"
            '[{{"index": 3, "relevance": 0.9, "angle": "从营养学角度解读该食品的健康影响", '
            '"category": "营养饮食"}}, '
            '{{"index": 15, "relevance": 0.35, "angle": "借此热点聊聊久坐办公的职场人如何保护腰椎", '
            '"category": "职场健康"}}]'
        ),
        "temperature": 0.5,
        "max_tokens": 8192,
        "variables": ["topic_lines", "target_count"],
    },
    "psychology_filtering": {
        "description": "热榜心理健康话题筛选",
        "system_prompt": (
            "你是一位心理健康科普自媒体的选题编辑，擅长从热门话题中发现心理健康相关的创作角度。"
            "你的核心能力是把社会热点与心理学知识巧妙结合，帮助大众关注心理健康。"
            "筛选要宽松，宁可多选也不要漏掉潜在的好选题。只输出JSON，不要输出其他内容。"
        ),
        "user_prompt_template": (
            "以下是当前中文互联网热门话题列表：\n\n"
            "{topic_lines}\n\n"
            "请从中挑选可以和心理健康科普结合的话题。筛选标准要宽松：\n"
            "1. 直接相关：心理健康、情绪管理、焦虑抑郁、人际关系、原生家庭、"
            "心理咨询、自我成长、心理创伤、压力应对、人格心理等\n"
            "2. 间接相关：职场压力、亲子教育、婚姻情感、校园霸凌、社交媒体焦虑、"
            "睡眠问题（心理因素）、成瘾行为、身心健康、生活方式与心理影响等\n"
            "3. 蹭热点型：即使话题本身与心理健康无直接关系，但可以巧妙结合心理学角度做科普的也算"
            "（如名人事件可聊心理韧性、社会事件可聊群体心理等）\n\n"
            "尽量多选，目标是找出 {target_count} 个左右的话题。\n\n"
            "对于每个话题，请输出 JSON 数组，每个元素包含：\n"
            '- "index": 话题在列表中的序号（从1开始）\n'
            '- "relevance": 与心理健康领域的相关度（0.0-1.0，直接相关>0.7，间接相关0.4-0.7，蹭热点0.2-0.4）\n'
            '- "angle": 建议的心理健康科普切入角度（一句话，要具体且有吸引力）\n'
            '- "category": 心理分类（如：情绪管理、焦虑抑郁、人际关系、职场心理、'
            "亲子教育、自我成长、睡眠心理、心理咨询、社会心理、婚姻情感、"
            "校园心理、热点解读等）\n\n"
            "只输出 JSON 数组，不要其他文字。\n"
            "示例格式：\n"
            '[{{"index": 5, "relevance": 0.9, "angle": "从依恋理论解读亲密关系中的安全感缺失", '
            '"category": "婚姻情感"}}, '
            '{{"index": 12, "relevance": 0.4, "angle": "借此热点聊聊职场PUA的心理学本质与应对策略", '
            '"category": "职场心理"}}]'
        ),
        "temperature": 0.5,
        "max_tokens": 8192,
        "variables": ["topic_lines", "target_count"],
    },
}

VARIABLE_DESCRIPTIONS: dict[str, str] = {
    "topic": "主题/话题内容",
    "min_words": "文章最少字数",
    "max_words": "文章最多字数",
    "style": "写作风格（如科普、口语化等）",
    "language": "输出语言（如中文、英文）",
    "reference_content": "参考资料原文（从URL导入或手动输入，可选）",
    "user_notes": "用户自定义观点和角度（可选）",
    "article": "生成的文章全文",
    "segment_count": "内容段落总数",
    "numbered_segments": "带编号的段落列表",
    "markers": "段落分隔标记列表",
    "lang_label": "图片提示词语言标签",
    "lang_instruction": "图片提示词语言指令",
    "ratio_hint": "画面构图比例提示（如16:9横屏）",
    "title": "文章/视频标题",
    "article_excerpt": "文章内容摘要（前500字）",
    "topic_lines": "热榜话题列表（自动生成，每行一条）",
    "target_count": "目标筛选数量（自动计算）",
}


class PromptTemplateService:
    """Service for prompt template management."""

    @staticmethod
    async def seed_defaults(db: AsyncSession) -> None:
        """Seed default templates, inserting any missing entries."""
        result = await db.execute(select(PromptTemplate.step_name))
        existing = {row[0] for row in result.all()}

        new_count = 0
        for step_name, data in DEFAULTS.items():
            if step_name in existing:
                continue
            template = PromptTemplate(
                step_name=step_name,
                description=data["description"],
                system_prompt=data["system_prompt"],
                user_prompt_template=data["user_prompt_template"],
                temperature=data["temperature"],
                max_tokens=data["max_tokens"],
                variables=json.dumps(data["variables"], ensure_ascii=False),
                extra_config=json.dumps(data.get("extra_config"), ensure_ascii=False) if data.get("extra_config") else None,
            )
            db.add(template)
            new_count += 1

        if new_count:
            await db.commit()
            logger.info("Seeded %d new prompt templates", new_count)

    @staticmethod
    async def list_all(db: AsyncSession) -> list[PromptTemplate]:
        """List all system prompt templates."""
        result = await db.execute(select(PromptTemplate).order_by(PromptTemplate.step_name))
        return list(result.scalars().all())

    @staticmethod
    async def get_by_step(db: AsyncSession, step_name: str) -> PromptTemplate | None:
        """Get a template by step name."""
        result = await db.execute(
            select(PromptTemplate).where(PromptTemplate.step_name == step_name)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def update_template(db: AsyncSession, step_name: str,
                               updates: dict, change_source: str = "system") -> PromptTemplate:
        """Update a template and save history."""
        template = await PromptTemplateService.get_by_step(db, step_name)
        if not template:
            raise ValueError(f"Template not found: {step_name}")

        # Get current version number
        result = await db.execute(
            select(sa_func.max(PromptTemplateHistory.version))
            .where(PromptTemplateHistory.template_id == template.id)
        )
        max_version = result.scalar() or 0

        # Save current state to history before updating
        history = PromptTemplateHistory(
            template_id=template.id,
            step_name=template.step_name,
            version=max_version + 1,
            system_prompt=template.system_prompt,
            user_prompt_template=template.user_prompt_template,
            temperature=template.temperature,
            max_tokens=template.max_tokens,
            extra_config=template.extra_config,
            change_source=change_source,
        )
        db.add(history)

        # Apply updates
        if updates.get("system_prompt") is not None:
            template.system_prompt = updates["system_prompt"]
        if updates.get("user_prompt_template") is not None:
            template.user_prompt_template = updates["user_prompt_template"]
        if updates.get("temperature") is not None:
            template.temperature = updates["temperature"]
        if updates.get("max_tokens") is not None:
            template.max_tokens = updates["max_tokens"]
        if "extra_config" in updates and updates["extra_config"] is not None:
            template.extra_config = json.dumps(updates["extra_config"], ensure_ascii=False)

        await db.commit()
        await db.refresh(template)
        return template

    @staticmethod
    async def reset_to_default(db: AsyncSession, step_name: str) -> PromptTemplate:
        """Reset a template to its hardcoded default."""
        if step_name not in DEFAULTS:
            raise ValueError(f"No default found for step: {step_name}")

        data = DEFAULTS[step_name]
        return await PromptTemplateService.update_template(
            db, step_name,
            {
                "system_prompt": data["system_prompt"],
                "user_prompt_template": data["user_prompt_template"],
                "temperature": data["temperature"],
                "max_tokens": data["max_tokens"],
                "extra_config": data.get("extra_config"),
            },
            change_source="system_reset",
        )

    @staticmethod
    async def get_history(db: AsyncSession, step_name: str) -> list[PromptTemplateHistory]:
        """Get version history for a template."""
        result = await db.execute(
            select(PromptTemplateHistory)
            .where(PromptTemplateHistory.step_name == step_name)
            .order_by(PromptTemplateHistory.version.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def restore_version(db: AsyncSession, step_name: str, version_id: str) -> PromptTemplate:
        """Restore a template from a history version."""
        result = await db.execute(
            select(PromptTemplateHistory).where(PromptTemplateHistory.id == version_id)
        )
        history = result.scalar_one_or_none()
        if not history:
            raise ValueError(f"History version not found: {version_id}")

        return await PromptTemplateService.update_template(
            db, step_name,
            {
                "system_prompt": history.system_prompt,
                "user_prompt_template": history.user_prompt_template,
                "temperature": history.temperature,
                "max_tokens": history.max_tokens,
                "extra_config": json.loads(history.extra_config) if history.extra_config else None,
            },
            change_source=f"restore_v{history.version}",
        )

    @staticmethod
    async def resolve(db: AsyncSession, step_name: str,
                       project_metadata_json: str | None = None) -> ResolvedPromptConfig | None:
        """Resolve prompt config: project override > system default > hardcoded."""
        template = await PromptTemplateService.get_by_step(db, step_name)
        if not template:
            # Fallback to hardcoded defaults
            if step_name in DEFAULTS:
                data = DEFAULTS[step_name]
                return ResolvedPromptConfig(
                    step_name=step_name,
                    system_prompt=data["system_prompt"],
                    user_prompt_template=data["user_prompt_template"],
                    temperature=data["temperature"],
                    max_tokens=data["max_tokens"],
                    variables=data["variables"],
                )
            return None

        # Start with system default
        config = ResolvedPromptConfig(
            step_name=step_name,
            system_prompt=template.system_prompt,
            user_prompt_template=template.user_prompt_template,
            temperature=template.temperature,
            max_tokens=template.max_tokens,
            variables=json.loads(template.variables) if template.variables else [],
        )

        # Apply project overrides if present
        if project_metadata_json:
            try:
                metadata = json.loads(project_metadata_json)
                overrides = metadata.get("prompt_overrides", {}).get(step_name, {})
                if overrides:
                    config.is_override = True
                    if overrides.get("system_prompt") is not None:
                        config.system_prompt = overrides["system_prompt"]
                    if overrides.get("user_prompt_template") is not None:
                        config.user_prompt_template = overrides["user_prompt_template"]
                    if overrides.get("temperature") is not None:
                        config.temperature = overrides["temperature"]
                    if overrides.get("max_tokens") is not None:
                        config.max_tokens = overrides["max_tokens"]
            except (json.JSONDecodeError, AttributeError):
                pass

        return config
