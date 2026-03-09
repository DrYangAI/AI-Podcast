"""Text generation provider interface."""

import re
from dataclasses import dataclass, field
from typing import AsyncIterator

from ..base import BaseProvider


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
                                min_words: int = 300, max_words: int = 1500) -> TextGenerationResponse:
        """Generate a health science popularization article."""
        prompt = self._build_article_prompt(topic, style, language, min_words, max_words)
        return await self.generate(TextGenerationRequest(
            prompt=prompt,
            system_prompt=self._get_article_system_prompt(),
            temperature=0.7,
            language=language,
        ))

    async def generate_script(self, article: str, style: str = "conversational") -> TextGenerationResponse:
        """Convert article into oral broadcast script."""
        prompt = self._build_script_prompt(article, style)
        return await self.generate(TextGenerationRequest(
            prompt=prompt,
            system_prompt=self._get_script_system_prompt(),
            temperature=0.5,
        ))

    async def generate_image_prompts(self, segments: list[str],
                                       language: str = "en") -> list[str]:
        """Generate image prompts for each content segment."""
        prompt = self._build_image_prompt_generation(segments, language)
        response = await self.generate(TextGenerationRequest(
            prompt=prompt,
            system_prompt=self._get_image_prompt_system_prompt(),
            temperature=0.6,
        ))
        return self._parse_image_prompts(response.content, len(segments))

    def _build_article_prompt(self, topic: str, style: str, language: str,
                               min_words: int, max_words: int) -> str:
        return (
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

    def _get_script_system_prompt(self) -> str:
        return (
            "你是一位专业的口播稿撰写专家,擅长将科普文章改写为适合口播的稿件。\n"
            "你的输出将直接发送给TTS语音合成系统朗读,因此:\n"
            "- 只输出纯文本,绝对不要使用Markdown格式(不要用**、#、-等标记)\n"
            "- 不要添加任何括号内的注释、舞台指导或情绪提示\n"
            "- 直接输出可以朗读的自然文字"
        )

    def _build_image_prompt_generation(self, segments: list[str],
                                        language: str = "en") -> str:
        numbered = "\n".join(f"[段落{i+1}]: {seg}" for i, seg in enumerate(segments))
        if language == "zh":
            lang_instruction = "使用中文"
            lang_label = "中文提示词"
        else:
            lang_instruction = "使用英文"
            lang_label = "英文提示词"
        return (
            f"请为以下每个段落生成一个用于AI绘图的{lang_label}:\n\n{numbered}\n\n"
            f"要求:\n"
            f"- {lang_instruction}\n"
            f"- 风格: 专业医学科普插图,现代扁平风格\n"
            f"- 避免出现人脸特写\n"
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
