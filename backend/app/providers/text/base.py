"""Text generation provider interface."""

import logging
import re
from dataclasses import dataclass, field
from typing import AsyncIterator

from ..base import BaseProvider

logger = logging.getLogger(__name__)


@dataclass
class TextGenerationRequest:
    prompt: str
    system_prompt: str = ""
    max_tokens: int = 4096
    temperature: float = 0.7
    language: str = "zh-CN"


@dataclass
class TextGenerationResponse:
    content: str
    model_used: str
    token_usage: dict[str, int] = field(default_factory=dict)
    raw_response: dict | None = None


class TextProvider(BaseProvider):
    """Interface for text generation providers (article & script generation)."""

    async def generate(self, request: TextGenerationRequest) -> TextGenerationResponse:
        """Generate text content."""
        raise NotImplementedError

    async def generate_stream(self, request: TextGenerationRequest) -> AsyncIterator[str]:
        """Stream text generation (optional)."""
        response = await self.generate(request)
        yield response.content

    async def generate_article(self, topic: str, style: str = "science_popularization",
                                language: str = "zh-CN",
                                min_words: int = 300, max_words: int = 1500,
                                prompt_config=None,
                                reference_content: str | None = None,
                                user_notes: str | None = None) -> TextGenerationResponse:
        """Generate a health science popularization article."""
        if prompt_config:
            # Build optional sections
            reference_section = ""
            if reference_content:
                reference_section = (
                    "\n\n【核心参考资料 - 必须严格遵循】\n"
                    "以下是用户提供的原始参考资料，你必须:\n"
                    "1. 以参考资料的核心观点和论据为基础进行撰写\n"
                    "2. 保留原文的关键数据、结论和专业观点\n"
                    "3. 可以调整表达方式使其更通俗易懂，但不得偏离原文核心思想\n"
                    "4. 不要凭空添加原文中没有的观点或数据\n"
                    f"\n参考资料原文:\n{reference_content}"
                )
            user_notes_section = ""
            if user_notes:
                user_notes_section = f"\n\n作者要求融入的观点和角度:\n{user_notes}"

            try:
                user_prompt = prompt_config.user_prompt_template.format(
                    topic=topic, style=style, language=language,
                    min_words=min_words, max_words=max_words,
                    reference_content=reference_section,
                    user_notes=user_notes_section,
                )
            except KeyError as e:
                logger.warning("Template variable error: %s, falling back to default", e)
                user_prompt = self._build_article_prompt(topic, style, language, min_words, max_words,
                                                          reference_content=reference_content, user_notes=user_notes)
            system_prompt = prompt_config.system_prompt
            temperature = prompt_config.temperature
            max_tokens = prompt_config.max_tokens
        else:
            user_prompt = self._build_article_prompt(topic, style, language, min_words, max_words,
                                                      reference_content=reference_content, user_notes=user_notes)
            system_prompt = self._get_article_system_prompt()
            temperature = 0.7
            max_tokens = 4096
        return await self.generate(TextGenerationRequest(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            language=language,
        ))

    async def generate_script(self, article: str, style: str = "conversational",
                               prompt_config=None) -> TextGenerationResponse:
        """Convert article into oral broadcast script."""
        if prompt_config:
            try:
                user_prompt = prompt_config.user_prompt_template.format(
                    article=article, style=style,
                )
            except KeyError as e:
                logger.warning("Template variable error: %s, falling back to default", e)
                user_prompt = self._build_script_prompt(article, style)
            system_prompt = prompt_config.system_prompt
            temperature = prompt_config.temperature
            max_tokens = prompt_config.max_tokens
        else:
            user_prompt = self._build_script_prompt(article, style)
            system_prompt = self._get_script_system_prompt()
            temperature = 0.5
            max_tokens = 4096
        return await self.generate(TextGenerationRequest(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        ))

    async def generate_segmented_script(self, segments: list[str],
                                         style: str = "conversational",
                                         prompt_config=None) -> TextGenerationResponse:
        """Generate oral broadcast script with per-segment markers."""
        if prompt_config:
            n = len(segments)
            numbered_segments = "\n\n".join(f"[段落{i+1}]:\n{seg}" for i, seg in enumerate(segments))
            markers = "、".join(f"[SEGMENT_{i+1}]" for i in range(n))
            try:
                user_prompt = prompt_config.user_prompt_template.format(
                    segment_count=n, numbered_segments=numbered_segments,
                    markers=markers, style=style,
                )
            except KeyError as e:
                logger.warning("Template variable error: %s, falling back to default", e)
                user_prompt = self._build_segmented_script_prompt(segments, style)
            system_prompt = prompt_config.system_prompt
            temperature = prompt_config.temperature
            max_tokens = prompt_config.max_tokens
        else:
            user_prompt = self._build_segmented_script_prompt(segments, style)
            system_prompt = self._get_script_system_prompt()
            temperature = 0.5
            max_tokens = 8192
        return await self.generate(TextGenerationRequest(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        ))

    async def generate_image_prompts(self, segments: list[str],
                                       language: str = "en",
                                       aspect_ratio: str = "16:9",
                                       prompt_config=None) -> list[str]:
        """Generate image prompts for each content segment."""
        if prompt_config:
            numbered_segments = "\n".join(f"[段落{i+1}]: {seg}" for i, seg in enumerate(segments))
            if language == "zh":
                lang_instruction = "使用中文"
                lang_label = "中文提示词"
            else:
                lang_instruction = "使用英文"
                lang_label = "英文提示词"
            ratio_hints = {
                "9:16": "竖版构图(9:16竖屏),画面内容应纵向排列,充分利用上下空间,采用从上到下的视觉动线,避免横向排列元素导致上下留白",
                "16:9": "横版构图(16:9宽屏),画面内容应横向展开,充分利用左右空间",
                "1:1": "方形构图(1:1),画面内容应居中均衡分布",
            }
            ratio_hint = ratio_hints.get(aspect_ratio, f"画面比例为{aspect_ratio},请根据此比例设计构图")
            try:
                user_prompt = prompt_config.user_prompt_template.format(
                    lang_label=lang_label, numbered_segments=numbered_segments,
                    lang_instruction=lang_instruction, ratio_hint=ratio_hint,
                )
            except KeyError as e:
                logger.warning("Template variable error: %s, falling back to default", e)
                user_prompt = self._build_image_prompt_generation(segments, language, aspect_ratio)
            system_prompt = prompt_config.system_prompt
            temperature = prompt_config.temperature
            max_tokens = prompt_config.max_tokens
        else:
            user_prompt = self._build_image_prompt_generation(segments, language, aspect_ratio)
            system_prompt = self._get_image_prompt_system_prompt()
            temperature = 0.6
            max_tokens = 8192
        response = await self.generate(TextGenerationRequest(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        ))
        prompts = self._parse_image_prompts(response.content, len(segments))
        logger.info(
            "Image prompt generation: expected=%d, parsed=%d",
            len(segments), len(prompts),
        )
        if len(prompts) < len(segments):
            logger.warning(
                "Fewer prompts than segments. Raw response (first 500 chars): %s",
                response.content[:500],
            )
        return prompts

    def _build_article_prompt(self, topic: str, style: str, language: str,
                               min_words: int, max_words: int,
                               reference_content: str | None = None,
                               user_notes: str | None = None) -> str:
        prompt = (
            f"请围绕以下主题撰写一篇健康科普文章:\n"
            f"主题: {topic}\n\n"
            f"要求:\n"
            f"- 字数: {min_words}-{max_words}字\n"
            f"- 风格: {style}\n"
            f"- 语言: {language}\n"
            f"- 分成3-8个自然段落\n"
            f"- 包含实用的健康建议\n"
            f"- 【重要】输出纯文本,不要使用Markdown格式(不要用#标题、**加粗**、- 列表等标记)\n"
            f"- 用空行分隔段落即可,不需要任何格式标记"
        )
        if reference_content:
            prompt += (
                "\n\n【核心参考资料 - 必须严格遵循】\n"
                "以下是用户提供的原始参考资料，你必须:\n"
                "1. 以参考资料的核心观点和论据为基础进行撰写\n"
                "2. 保留原文的关键数据、结论和专业观点\n"
                "3. 可以调整表达方式使其更通俗易懂，但不得偏离原文核心思想\n"
                "4. 不要凭空添加原文中没有的观点或数据\n"
                f"\n参考资料原文:\n{reference_content}"
            )
        if user_notes:
            prompt += f"\n\n作者要求融入的观点和角度:\n{user_notes}"
        return prompt

    def _get_article_system_prompt(self) -> str:
        return (
            "你是一位专业的健康科普作家,擅长将复杂的医学知识转化为通俗易懂的科普文章。\n"
            "你的文章应该:\n"
            "- 科学准确,引用可靠的医学来源\n"
            "- 通俗易懂,避免过多专业术语\n"
            "- 结构清晰,用空行分段\n"
            "- 适合大众阅读的健康科普内容\n"
            "- 输出纯文本,绝对不使用任何Markdown格式标记"
        )

    def _build_script_prompt(self, article: str, style: str) -> str:
        return (
            f"请将以下科普文章改写为口播稿:\n\n{article}\n\n"
            f"要求:\n"
            f"- 口语化表达,适合朗读\n"
            f"- 保持专业性但更加亲切\n"
            f"- 适当添加过渡词和语气词\n"
            f"- 风格: {style}\n"
            f"- 【重要】输出纯文本,不要使用任何Markdown格式(如**加粗**、# 标题、- 列表等)\n"
            f"- 【重要】不要添加任何括号注释或舞台指导(如「（轻松开场）」「（停顿）」等),直接输出可朗读的文字"
        )

    def _build_segmented_script_prompt(self, segments: list[str], style: str) -> str:
        n = len(segments)
        numbered = "\n\n".join(f"[段落{i+1}]:\n{seg}" for i, seg in enumerate(segments))
        markers = "、".join(f"[SEGMENT_{i+1}]" for i in range(n))
        return (
            f"请将以下{n}个内容段落分别改写为口播稿。\n\n"
            f"{numbered}\n\n"
            f"要求:\n"
            f"- 严格输出{n}个段落,每个段落前用标记 {markers} 标识\n"
            f"- 第一个段落需要有自然的开场（如问候听众）,最后一个段落需要有收尾总结\n"
            f"- 相邻段落之间要有自然的过渡衔接\n"
            f"- 口语化表达,适合朗读\n"
            f"- 保持专业性但更加亲切\n"
            f"- 适当添加过渡词和语气词\n"
            f"- 风格: {style}\n"
            f"- 【重要】输出纯文本,不要使用任何Markdown格式\n"
            f"- 【重要】不要添加任何括号注释或舞台指导,直接输出可朗读的文字"
        )

    @staticmethod
    def parse_segmented_script(content: str, expected_count: int) -> list[str]:
        """Parse LLM output with [SEGMENT_N] markers into a list of segment texts."""
        parts = re.split(r'\[SEGMENT_\d+\]\s*:?\s*', content)
        # First element is text before any marker (usually empty), skip it
        segments = [p.strip() for p in parts[1:] if p.strip()]

        if len(segments) == expected_count:
            return segments

        # Fallback: split by double newlines and distribute evenly
        paragraphs = [p.strip() for p in re.split(r'\n\s*\n', content) if p.strip()]
        # Remove any marker lines
        paragraphs = [re.sub(r'\[SEGMENT_\d+\]\s*:?\s*', '', p).strip()
                       for p in paragraphs]
        paragraphs = [p for p in paragraphs if p]

        if len(paragraphs) <= expected_count:
            return paragraphs

        # Greedy merge by character count
        total_chars = sum(len(p) for p in paragraphs)
        target = total_chars / expected_count
        merged = []
        group, chars = [], 0
        for p in paragraphs:
            group.append(p)
            chars += len(p)
            remaining_segs = expected_count - len(merged) - 1
            remaining_paras = len(paragraphs) - (sum(len(g) for g in merged) + len(group)) if merged else len(paragraphs) - len(group)
            if remaining_segs > 0 and chars >= target:
                merged.append('\n'.join(group))
                group, chars = [], 0
        if group:
            merged.append('\n'.join(group))
        return merged

    def _get_script_system_prompt(self) -> str:
        return (
            "你是一位专业的口播稿撰写专家,擅长将科普文章改写为适合口播的稿件。\n"
            "你的输出将直接发送给TTS语音合成系统朗读,因此:\n"
            "- 只输出纯文本,绝对不要使用Markdown格式(不要用**、#、-等标记)\n"
            "- 不要添加任何括号内的注释、舞台指导或情绪提示\n"
            "- 直接输出可以朗读的自然文字"
        )

    def _build_image_prompt_generation(self, segments: list[str],
                                        language: str = "en",
                                        aspect_ratio: str = "16:9") -> str:
        numbered = "\n".join(f"[段落{i+1}]: {seg}" for i, seg in enumerate(segments))
        if language == "zh":
            lang_instruction = "使用中文"
            lang_label = "中文提示词"
        else:
            lang_instruction = "使用英文"
            lang_label = "英文提示词"

        # Build aspect ratio composition guidance
        ratio_hints = {
            "9:16": "竖版构图(9:16竖屏),画面内容应纵向排列,充分利用上下空间,采用从上到下的视觉动线,避免横向排列元素导致上下留白",
            "16:9": "横版构图(16:9宽屏),画面内容应横向展开,充分利用左右空间",
            "1:1": "方形构图(1:1),画面内容应居中均衡分布",
        }
        ratio_hint = ratio_hints.get(aspect_ratio, f"画面比例为{aspect_ratio},请根据此比例设计构图")

        return (
            f"请为以下每个段落生成一个用于AI绘图的{lang_label}:\n\n{numbered}\n\n"
            f"要求:\n"
            f"- {lang_instruction}\n"
            f"- 风格: 专业医学科普插图,现代扁平风格\n"
            f"- 避免出现人脸特写\n"
            f"- 如果画面中需要出现文字或标注,请确保文字内容准确无误,使用简体中文\n"
            f"- 【重要】构图要求: {ratio_hint}\n"
            f"- 每个提示词中必须明确描述画面元素的空间布局方向\n"
            f"- 用 [PROMPT_1], [PROMPT_2]... 标记每个提示词"
        )

    def _get_image_prompt_system_prompt(self) -> str:
        return "你是一位AI绘画提示词专家。请为每个段落生成适合的图片描述提示词。"

    def _parse_image_prompts(self, content: str, expected_count: int) -> list[str]:
        """Parse AI response to extract image prompts."""
        pattern = r'\[PROMPT_\d+\]\s*:?\s*(.+?)(?=\[PROMPT_|\Z)'
        matches = re.findall(pattern, content, re.DOTALL)
        prompts = [m.strip() for m in matches if m.strip()]
        if len(prompts) < expected_count:
            lines = [l.strip() for l in content.split('\n') if l.strip() and not l.strip().startswith('[')]
            prompts.extend(lines[len(prompts):expected_count])
        return prompts[:expected_count]

    # --- Publish copy (multi-platform titles, descriptions, tags) ---

    async def generate_publish_copy(self, title: str, article: str,
                                      topic: str, prompt_config=None) -> dict[str, dict]:
        """Generate viral titles, descriptions and tags for 5 platforms."""
        if prompt_config:
            article_excerpt = article[:2000] if len(article) > 2000 else article
            try:
                user_prompt = prompt_config.user_prompt_template.format(
                    topic=topic, title=title, article_excerpt=article_excerpt,
                )
            except KeyError as e:
                logger.warning("Template variable error: %s, falling back to default", e)
                user_prompt = self._build_publish_copy_prompt(title, article, topic)
            system_prompt = prompt_config.system_prompt
            temperature = prompt_config.temperature
            max_tokens = prompt_config.max_tokens
        else:
            user_prompt = self._build_publish_copy_prompt(title, article, topic)
            system_prompt = self._get_publish_copy_system_prompt()
            temperature = 0.7
            max_tokens = 4096
        response = await self.generate(TextGenerationRequest(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        ))
        return self._parse_publish_copy(response.content)

    async def generate_cover_prompt(self, topic: str, title: str,
                                      aspect_ratio: str = "3:4",
                                      prompt_config=None) -> str:
        """Generate an image prompt for a video cover."""
        ratio_hints = {
            "3:4": "竖版构图(3:4),主体居中偏上,下方留空",
            "16:9": "横版宽屏构图(16:9),主体居中,左右充分利用",
        }
        ratio_hint = ratio_hints.get(aspect_ratio, f"画面比例{aspect_ratio}")

        if prompt_config:
            try:
                user_prompt = prompt_config.user_prompt_template.format(
                    topic=topic, title=title, ratio_hint=ratio_hint,
                )
            except KeyError as e:
                logger.warning("Template variable error: %s, falling back to default", e)
                user_prompt = (
                    f"请为以下健康科普短视频生成一个封面背景图的AI绘图提示词:\n\n"
                    f"视频主题: {topic}\n"
                    f"视频标题: {title}\n\n"
                    f"要求:\n"
                    f"- 使用英文提示词\n"
                    f"- 画面明亮、专业、现代感强\n"
                    f"- 适合健康/医学科普类视频封面\n"
                    f"- 色彩鲜明,视觉冲击力强\n"
                    f"- 不包含任何文字\n"
                    f"- {ratio_hint}\n"
                    f"- 避免出现人脸特写\n"
                    f"- 只输出提示词本身,不要任何额外说明"
                )
            system_prompt = prompt_config.system_prompt
            temperature = prompt_config.temperature
        else:
            user_prompt = (
                f"请为以下健康科普短视频生成一个封面背景图的AI绘图提示词:\n\n"
                f"视频主题: {topic}\n"
                f"视频标题: {title}\n\n"
                f"要求:\n"
                f"- 使用英文提示词\n"
                f"- 画面明亮、专业、现代感强\n"
                f"- 适合健康/医学科普类视频封面\n"
                f"- 色彩鲜明,视觉冲击力强\n"
                f"- 不包含任何文字\n"
                f"- {ratio_hint}\n"
                f"- 避免出现人脸特写\n"
                f"- 只输出提示词本身,不要任何额外说明"
            )
            system_prompt = "你是一位AI绘画提示词专家,擅长设计短视频封面。只输出英文提示词。"
            temperature = 0.6
        response = await self.generate(TextGenerationRequest(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=temperature,
        ))
        return response.content.strip()

    def _build_publish_copy_prompt(self, title: str, article: str, topic: str) -> str:
        # Truncate article to avoid token overflow
        article_excerpt = article[:2000] if len(article) > 2000 else article
        return (
            f"请根据以下健康科普视频内容,为5个平台生成爆款标题、摘要和标签。\n\n"
            f"视频主题: {topic}\n"
            f"文章标题: {title}\n"
            f"文章内容:\n{article_excerpt}\n\n"
            f"为以下每个平台各生成一组:\n\n"
            f"1. 微信视频号(weixin) - 标题≤30字, 摘要≤1000字\n"
            f"2. 小红书(xiaohongshu) - 标题≤20字, 摘要200-600字, 种草风格, 适当使用emoji\n"
            f"3. 抖音(douyin) - 标题≤30字, 摘要≤300字, 短视频风格\n"
            f"4. 腾讯视频(tencent_video) - 标题10-30字, 摘要≤200字, 正式风格\n"
            f"5. 今日头条(toutiao) - 标题≤30字, 摘要≤400字, 不要夸张\n\n"
            f"要求:\n"
            f"- 标题要有吸引力,能引发点击\n"
            f"- 摘要要包含核心信息,引发观看欲望\n"
            f"- 每个平台生成3-5个推荐标签(带#号)\n"
            f"- 不同平台的标题和摘要风格要有差异,符合各平台用户习惯\n\n"
            f"请严格按以下格式输出(每个平台一个区块):\n\n"
            f"[PLATFORM_weixin]\n"
            f"title: 标题内容\n"
            f"description: 摘要内容\n"
            f"tags: #标签1 #标签2 #标签3\n\n"
            f"[PLATFORM_xiaohongshu]\n"
            f"title: 标题内容\n"
            f"description: 摘要内容\n"
            f"tags: #标签1 #标签2 #标签3\n\n"
            f"[PLATFORM_douyin]\n"
            f"title: 标题内容\n"
            f"description: 摘要内容\n"
            f"tags: #标签1 #标签2 #标签3\n\n"
            f"[PLATFORM_tencent_video]\n"
            f"title: 标题内容\n"
            f"description: 摘要内容\n"
            f"tags: #标签1 #标签2 #标签3\n\n"
            f"[PLATFORM_toutiao]\n"
            f"title: 标题内容\n"
            f"description: 摘要内容\n"
            f"tags: #标签1 #标签2 #标签3"
        )

    def _get_publish_copy_system_prompt(self) -> str:
        return (
            "你是一位资深的短视频运营专家,精通微信视频号、小红书、抖音、腾讯视频和今日头条的内容运营。\n"
            "你擅长撰写高点击率的标题和摘要,了解各平台的用户特点和推荐算法偏好。\n"
            "请严格按照指定格式输出,每个平台一个[PLATFORM_xxx]区块。"
        )

    def _parse_publish_copy(self, content: str) -> dict[str, dict]:
        """Parse AI response into per-platform dicts.

        Returns: {"weixin": {"title": ..., "description": ..., "tags": ...}, ...}
        """
        platforms = ["weixin", "xiaohongshu", "douyin", "tencent_video", "toutiao"]
        result: dict[str, dict] = {}

        for platform in platforms:
            pattern = (
                rf'\[PLATFORM_{platform}\]\s*\n'
                rf'title:\s*(.+?)\n'
                rf'description:\s*(.+?)\n'
                rf'tags:\s*(.+?)(?=\n\[PLATFORM_|\Z)'
            )
            match = re.search(pattern, content, re.DOTALL)
            if match:
                result[platform] = {
                    "title": match.group(1).strip(),
                    "description": match.group(2).strip(),
                    "tags": match.group(3).strip(),
                }
            else:
                # Fallback: provide empty data
                result[platform] = {
                    "title": "",
                    "description": "",
                    "tags": "",
                }

        return result
