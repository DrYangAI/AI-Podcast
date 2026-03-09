"""Base class for OpenAI API-compatible text providers.

Many Chinese AI providers (DeepSeek, Doubao, Qwen, Zhipu, MiniMax, etc.)
offer OpenAI-compatible API endpoints. This base class eliminates code
duplication: subclasses only need to set `metadata` and override nothing.
"""

import openai

from .base import TextProvider, TextGenerationRequest, TextGenerationResponse


class OpenAICompatibleTextProvider(TextProvider):
    """
    Reusable base for any provider whose chat completions endpoint
    follows the OpenAI format (POST /v1/chat/completions).

    Subclasses only need to define `metadata` (with key, name,
    provider_type, supported_models, default_api_base) and register
    themselves with @ProviderRegistry.register.
    """

    async def generate(self, request: TextGenerationRequest) -> TextGenerationResponse:
        client = openai.AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.api_base_url or self.metadata.default_api_base,
        )

        messages: list[dict] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.prompt})

        default_model = self.metadata.supported_models[0] if self.metadata.supported_models else "default"

        response = await client.chat.completions.create(
            model=self.model_id or default_model,
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
            client = openai.AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.api_base_url or self.metadata.default_api_base,
            )
            default_model = self.metadata.supported_models[0] if self.metadata.supported_models else "default"
            await client.chat.completions.create(
                model=self.model_id or default_model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5,
            )
            return True
        except Exception:
            return False
