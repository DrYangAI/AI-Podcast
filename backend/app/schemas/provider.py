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
    api_key_masked: str | None = None
    api_base_url: str | None
    model_id: str | None
    config: dict[str, Any] | None = None
    is_default: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def model_validate(cls, obj, **kwargs):
        """Override to generate masked api_key from the ORM object."""
        instance = super().model_validate(obj, **kwargs)
        # Generate mask from the real api_key
        raw_key = getattr(obj, "api_key", None)
        if raw_key:
            if len(raw_key) <= 8:
                instance.api_key_masked = "****" + raw_key[-2:]
            else:
                instance.api_key_masked = raw_key[:3] + "****" + raw_key[-4:]
        return instance


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
