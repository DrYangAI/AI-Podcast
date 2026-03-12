"""Publish asset schemas for API request/response."""

from datetime import datetime

from pydantic import BaseModel


class PublishAssetResponse(BaseModel):
    id: str
    platform: str
    cover_path: str | None = None
    cover_width: int | None = None
    cover_height: int | None = None
    cover_status: str = "pending"
    title: str
    description: str
    tags: str | None = None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PublishAssetUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    tags: str | None = None


class CoverRegenerateRequest(BaseModel):
    """Request to regenerate cover images with optional custom prompt."""
    prompt: str | None = None


class CoverPromptResponse(BaseModel):
    """Response containing the cover prompt."""
    prompt: str | None = None


class CoverPromptUpdate(BaseModel):
    """Request to update the cover prompt."""
    prompt: str
