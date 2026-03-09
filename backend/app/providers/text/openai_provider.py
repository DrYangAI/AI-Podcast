"""OpenAI GPT text generation provider."""

import openai

from ..base import ProviderMetadata, ProviderType
from ..registry import ProviderRegistry
from .base import TextProvider, TextGenerationRequest, TextGenerationResponse


@ProviderRegistry.register
class OpenAITextProvider(TextProvider):
    metadata = ProviderMetadata(
        key="openai",
        name="GPT (OpenAI)",
        provider_type=ProviderType.TEXT,
        description="OpenAI GPT models for text generation",
        supported_models=["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
        default_api_base="https://api.openai.com/v1",
        requires_api_key=True,
    )

    async def generate(self, request: TextGenerationRequest) -> TextGenerationResponse:
        client = openai.AsyncOpenAI(api_key=self.api_key, base_url=self.api_base_url or None)
        messages = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.prompt})

        response = await client.chat.completions.create(
            model=self.model_id or "gpt-4o",
            messages=messages,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
        )
        choice = response.choices[0]
        return TextGenerationResponse(
            content=choice.message.content or "",
            model_used=response.model,
            token_usage={
                "input": response.usage.prompt_tokens if response.usage else 0,
                "output": response.usage.completion_tokens if response.usage else 0,
            },
        )

    async def validate_connection(self) -> bool:
        try:
            client = openai.AsyncOpenAI(api_key=self.api_key, base_url=self.api_base_url or None)
            await client.chat.completions.create(
                model=self.model_id or "gpt-4o",
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=10,
            )
            return True
        except Exception:
            return False
