"""Provider schemas for API request/response."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ProviderConfigCreate(BaseModel):
    name: str = Field(..., min_length=1)
    provider_type: str
    provider_key: str
    api_key: str | None = None
    api_base_url: str | None = None
    model_id: str | None = None
    config: dict[str, Any] | None = None
    is_default: bool = False


class ProviderConfigUpdate(BaseModel):
    name: str | None = None
    api_key: str | None = None
    api_base_url: str | None = None
    model_id: str | None = None
    config: dict[str, Any] | None = None
    is_default: bool | None = None
    is_active: bool | None = None


class ProviderConfigResponse(BaseModel):
    id: str
    name: str
    provider_type: str
    provider_key: str
    api_base_url: str | None
    model_id: str | None
    config: dict[str, Any] | None = None
    is_default: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime
    # Never expose api_key in responses

    model_config = {"from_attributes": True}


class ProviderTypeInfo(BaseModel):
    key: str
    name: str
    provider_type: str
    description: str
    supported_models: list[str]
    requires_api_key: bool


class ProviderTestResult(BaseModel):
    success: bool
    message: str
