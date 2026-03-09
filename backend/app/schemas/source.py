"""Content source schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ContentSourceCreate(BaseModel):
    name: str = Field(..., min_length=1)
    source_type: str
    url: str
    category: str | None = None
    fetch_interval: int = 3600
    config: dict[str, Any] | None = None


class ContentSourceUpdate(BaseModel):
    name: str | None = None
    url: str | None = None
    category: str | None = None
    fetch_interval: int | None = None
    is_active: bool | None = None
    config: dict[str, Any] | None = None


class ContentSourceResponse(BaseModel):
    id: str
    name: str
    source_type: str
    url: str
    category: str | None
    fetch_interval: int
    last_fetched_at: datetime | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class FetchedTopicResponse(BaseModel):
    id: str
    source_id: str
    title: str
    url: str | None
    summary: str | None
    fetched_at: datetime
    is_used: bool

    model_config = {"from_attributes": True}


class UrlExtractRequest(BaseModel):
    url: str = Field(..., min_length=1)


class UrlExtractResponse(BaseModel):
    title: str
    content: str
    url: str


class HotTopicRequest(BaseModel):
    sources: list[str] | None = None
    max_results: int = Field(default=15, ge=1, le=50)


class HotTopicItem(BaseModel):
    title: str
    source: str
    source_name: str
    url: str | None
    rank: int
    heat: str
    relevance_score: float
    health_angle: str
    category: str


class HotTopicResponse(BaseModel):
    items: list[HotTopicItem]
    total_scraped: int
    ai_filtered: int


class HotTopicProjectCreate(BaseModel):
    title: str = Field(..., min_length=1)
    health_angle: str = ""
    source_url: str | None = None
