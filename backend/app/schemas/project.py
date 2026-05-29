"""Project schemas for API request/response."""

from datetime import datetime

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    topic: str = Field(..., min_length=1)
    source_type: str = Field(default="manual")
    source_url: str | None = None
    aspect_ratio: str = Field(default="16:9")
    video_template: str = Field(default="slideshow")
    image_prompt_language: str = Field(default="zh")
    image_width: int | None = None
    image_height: int | None = None
    image_quality: str = Field(default="standard")
    image_style: str = Field(default="natural")
    image_negative_prompt: str | None = None
    subtitle_enabled: bool = Field(default=True)
    subtitle_font_size: int = Field(default=18)
    subtitle_font_color: str = Field(default="#FFFFFF")
    subtitle_outline_width: int = Field(default=1)
    subtitle_position: str = Field(default="bottom")
    subtitle_margin_bottom: int = Field(default=30)
    portrait_composite_enabled: bool = Field(default=True)
    portrait_bg_color: str = Field(default="#1A1A2E")
    portrait_title_text: str | None = None
    portrait_title_font_size: int = Field(default=36)
    portrait_title_y: int = Field(default=82)
    portrait_video_y: int = Field(default=480)
    portrait_subtitle_font_size: int = Field(default=38)
    portrait_subtitle_margin_v: int = Field(default=550)
    portrait_title_color: str = Field(default="#FFFFFF")
    portrait_title_outline_color: str = Field(default="#000000")
    portrait_title_outline_width: int = Field(default=2)
    portrait_title_shadow_enabled: bool = Field(default=True)
    portrait_title_shadow_color: str = Field(default="#000000")
    portrait_title_shadow_opacity: float = Field(default=0.5)
    portrait_title_shadow_x: int = Field(default=2)
    portrait_title_shadow_y: int = Field(default=2)
    portrait_sub_title_text: str | None = None
    portrait_sub_title_font_size: int = Field(default=24)
    portrait_sub_title_color: str = Field(default="#CCCCCC")
    portrait_sub_title_y: int = Field(default=130)
    portrait_title_bg_enabled: bool = Field(default=False)
    portrait_title_bg_color: str = Field(default="#000000")
    portrait_title_bg_opacity: float = Field(default=0.5)
    portrait_title_bg_padding: int = Field(default=20)
    portrait_title_bg_shape: str = Field(default="rect")
    portrait_title_bg_radius: int = Field(default=16)
    portrait_title_bg_skew: int = Field(default=10)
    tts_voice_id: str | None = None
    tts_voice_clone_id: str | None = None
    intro_text: str | None = None
    outro_text: str | None = None
    reference_content: str | None = None
    use_reference_content: bool = Field(default=True)
    user_notes: str | None = None


class ProjectUpdate(BaseModel):
    title: str | None = None
    topic: str | None = None
    aspect_ratio: str | None = None
    video_template: str | None = None
    image_prompt_language: str | None = None
    output_format: str | None = None
    image_width: int | None = None
    image_height: int | None = None
    image_quality: str | None = None
    image_style: str | None = None
    image_negative_prompt: str | None = None
    subtitle_enabled: bool | None = None
    subtitle_font_size: int | None = None
    subtitle_font_color: str | None = None
    subtitle_outline_width: int | None = None
    subtitle_position: str | None = None
    subtitle_margin_bottom: int | None = None
    portrait_composite_enabled: bool | None = None
    portrait_bg_color: str | None = None
    portrait_title_text: str | None = None
    portrait_title_font_size: int | None = None
    portrait_title_y: int | None = None
    portrait_video_y: int | None = None
    portrait_subtitle_font_size: int | None = None
    portrait_subtitle_margin_v: int | None = None
    portrait_title_color: str | None = None
    portrait_title_outline_color: str | None = None
    portrait_title_outline_width: int | None = None
    portrait_title_shadow_enabled: bool | None = None
    portrait_title_shadow_color: str | None = None
    portrait_title_shadow_opacity: float | None = None
    portrait_title_shadow_x: int | None = None
    portrait_title_shadow_y: int | None = None
    portrait_sub_title_text: str | None = None
    portrait_sub_title_font_size: int | None = None
    portrait_sub_title_color: str | None = None
    portrait_sub_title_y: int | None = None
    portrait_title_bg_enabled: bool | None = None
    portrait_title_bg_color: str | None = None
    portrait_title_bg_opacity: float | None = None
    portrait_title_bg_padding: int | None = None
    portrait_title_bg_shape: str | None = None
    portrait_title_bg_radius: int | None = None
    portrait_title_bg_skew: int | None = None
    tts_voice_id: str | None = None
    tts_voice_clone_id: str | None = None
    intro_text: str | None = None
    outro_text: str | None = None
    reference_content: str | None = None
    use_reference_content: bool | None = None
    user_notes: str | None = None


class ProjectResponse(BaseModel):
    id: str
    title: str
    topic: str
    source_type: str
    source_url: str | None
    aspect_ratio: str
    video_template: str
    image_prompt_language: str
    output_format: str
    image_width: int | None = None
    image_height: int | None = None
    image_quality: str = "standard"
    image_style: str = "natural"
    image_negative_prompt: str | None = None
    subtitle_enabled: bool = True
    subtitle_font_size: int = 18
    subtitle_font_color: str = "#FFFFFF"
    subtitle_outline_width: int = 1
    subtitle_position: str = "bottom"
    subtitle_margin_bottom: int = 30
    portrait_composite_enabled: bool = True
    portrait_bg_color: str = "#1A1A2E"
    portrait_title_text: str | None = None
    portrait_title_font_size: int = 36
    portrait_title_y: int = 82
    portrait_video_y: int = 480
    portrait_subtitle_font_size: int = 38
    portrait_subtitle_margin_v: int = 550
    portrait_title_color: str = "#FFFFFF"
    portrait_title_outline_color: str = "#000000"
    portrait_title_outline_width: int = 2
    portrait_title_shadow_enabled: bool = True
    portrait_title_shadow_color: str = "#000000"
    portrait_title_shadow_opacity: float = 0.5
    portrait_title_shadow_x: int = 2
    portrait_title_shadow_y: int = 2
    portrait_sub_title_text: str | None = None
    portrait_sub_title_font_size: int = 24
    portrait_sub_title_color: str = "#CCCCCC"
    portrait_sub_title_y: int = 130
    portrait_title_bg_enabled: bool = False
    portrait_title_bg_color: str = "#000000"
    portrait_title_bg_opacity: float = 0.5
    portrait_title_bg_padding: int = 20
    portrait_title_bg_shape: str = "rect"
    portrait_title_bg_radius: int = 16
    portrait_title_bg_skew: int = 10
    tts_voice_id: str | None = None
    tts_voice_clone_id: str | None = None
    intro_text: str | None = None
    outro_text: str | None = None
    reference_content: str | None = None
    use_reference_content: bool = True
    user_notes: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectDetailResponse(ProjectResponse):
    pipeline_steps: list["PipelineStepResponse"] = []
    article: "ArticleResponse | None" = None
    script: "ScriptResponse | None" = None

    model_config = {"from_attributes": True}


class PipelineStepResponse(BaseModel):
    id: str
    step_name: str
    step_order: int
    status: str
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class ArticleResponse(BaseModel):
    id: str
    title: str
    content: str
    word_count: int | None
    language: str
    is_manual: bool
    version: int
    created_at: datetime

    model_config = {"from_attributes": True}


class ArticleUpdate(BaseModel):
    title: str | None = None
    content: str | None = None


class SegmentResponse(BaseModel):
    id: str
    segment_order: int
    content: str
    image_prompt: str | None
    duration_hint: float | None
    chapter_title: str | None = None

    model_config = {"from_attributes": True}


class SegmentUpdate(BaseModel):
    content: str | None = None
    image_prompt: str | None = None
    chapter_title: str | None = None


class ImageAssetResponse(BaseModel):
    id: str
    segment_id: str
    file_path: str
    prompt_used: str | None
    width: int | None
    height: int | None
    is_manual: bool
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ImageRegenerateRequest(BaseModel):
    prompt: str | None = None


class ScriptResponse(BaseModel):
    id: str
    content: str
    style: str | None
    is_manual: bool
    version: int
    created_at: datetime

    model_config = {"from_attributes": True}


class ScriptUpdate(BaseModel):
    content: str | None = None
    style: str | None = None


class AudioAssetResponse(BaseModel):
    id: str
    file_path: str
    duration: float | None
    voice_id: str | None
    is_manual: bool
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AudioChunkResponse(BaseModel):
    index: int
    text: str
    file: str          # filename: chunk_000.mp3
    file_url: str      # playable URL: /data/audio/{pid}/chunks/chunk_000.mp3
    duration: float
    speed: float       # chars per second
    chars: int


class AudioChunksListResponse(BaseModel):
    chunks: list[AudioChunkResponse]
    voice_id: str
    use_icl: bool


class VideoOutputResponse(BaseModel):
    id: str
    file_path: str
    file_name: str
    aspect_ratio: str
    template_used: str
    duration: float | None
    resolution: str | None
    file_size: int | None
    has_subtitles: bool
    video_type: str = "standard"
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PipelineRunRequest(BaseModel):
    from_step: str | None = None
    provider_overrides: dict[str, str] | None = None


class PaginatedResponse(BaseModel):
    items: list[ProjectResponse]
    total: int
    page: int
    page_size: int
