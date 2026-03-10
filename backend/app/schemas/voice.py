"""Voice clone schemas for API request/response."""

from datetime import datetime

from pydantic import BaseModel, Field


class VoiceCloneCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    provider_key: str = Field(default="doubao_tts")
    speaker_id: str = Field(..., min_length=1, description="从火山引擎控制台获取的音色 ID (如 S_xxxxxxx)")
    reference_text: str | None = None
    is_default: bool = False


class VoiceCloneUpdate(BaseModel):
    name: str | None = None
    reference_text: str | None = None
    is_default: bool | None = None


class VoiceCloneResponse(BaseModel):
    id: str
    name: str
    provider_key: str
    speaker_id: str
    reference_audio_path: str
    reference_text: str | None
    training_status: int  # 0=NotFound, 1=Training, 2=Success, 3=Failed, 4=Active
    is_default: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class VoicePreviewResponse(BaseModel):
    audio_path: str
    duration: float


class PresetVoice(BaseModel):
    """Predefined voice from a TTS provider."""
    id: str
    name: str
    gender: str | None = None
    language: str | None = None
    provider_key: str | None = None
