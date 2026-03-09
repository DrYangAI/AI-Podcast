"""Claude (Anthropic) text generation provider."""

import anthropic

from ..base import ProviderMetadata, ProviderType
from ..registry import ProviderRegistry
from .base import TextProvider, TextGenerationRequest, TextGenerationResponse


@ProviderRegistry.register
class ClaudeProvider(TextProvider):
    metadata = ProviderMetadata(
        key="claude",
        name="Claude (Anthropic)",
        provider_type=ProviderType.TEXT,
        description="Anthropic Claude models for text generation",
        supported_models=["claude-sonnet-4-20250514", "claude-opus-4-20250514", "claude-haiku-4-5-20251001"],
        default_api_base="https://api.anthropic.com",
        requires_api_key=True,
    )

    async def generate(self, request: TextGenerationRequest) -> TextGenerationResponse:
        client = anthropic.AsyncAnthropic(api_key=self.api_key)
        message = await client.messages.create(
            model=self.model_id or "claude-sonnet-4-20250514",
            max_tokens=request.max_tokens,
            system=request.system_prompt,
            messages=[{"role": "user", "content": request.prompt}],
            temperature=request.temperature,
        )
        return TextGenerationResponse(
            content=message.content[0].text,
            model_used=message.model,
            token_usage={
                "input": message.usage.input_tokens,
                "output": message.usage.output_tokens,
            },
        )

    async def validate_connection(self) -> bool:
        try:
            client = anthropic.AsyncAnthropic(api_key=self.api_key)
            await client.messages.create(
                model=self.model_id or "claude-sonnet-4-20250514",
                max_tokens=10,
                messages=[{"role": "user", "content": "ping"}],
            )
            return True
        except Exception:
            return False
