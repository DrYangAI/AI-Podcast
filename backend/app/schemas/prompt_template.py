"""Prompt template schemas."""

from datetime import datetime
from pydantic import BaseModel


class PromptTemplateResponse(BaseModel):
    id: str
    step_name: str
    description: str
    system_prompt: str
    user_prompt_template: str
    temperature: float
    max_tokens: int
    variables: list[str]
    variable_descriptions: dict[str, str] = {}
    extra_config: dict | None = None
    updated_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class PromptTemplateUpdate(BaseModel):
    system_prompt: str | None = None
    user_prompt_template: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    extra_config: dict | None = None


class PromptTemplateHistoryResponse(BaseModel):
    id: str
    template_id: str
    step_name: str
    version: int
    system_prompt: str
    user_prompt_template: str
    temperature: float
    max_tokens: int
    extra_config: dict | None = None
    change_source: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ProjectPromptOverride(BaseModel):
    """Per-project prompt override for a single step."""
    system_prompt: str | None = None
    user_prompt_template: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None


class ResolvedPromptConfig(BaseModel):
    """Fully resolved prompt config (system default + project override merged)."""
    step_name: str
    system_prompt: str
    user_prompt_template: str
    temperature: float
    max_tokens: int
    variables: list[str]
    variable_descriptions: dict[str, str] = {}
    is_override: bool  # True if project has overrides for this step
    description: str = ""
