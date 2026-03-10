"""Voice clone management API routes.

Uses Volcano Engine V3 voice_clone training API:
  POST https://openspeech.bytedance.com/api/v3/tts/voice_clone  (train)
  POST https://openspeech.bytedance.com/api/v3/tts/get_voice    (status query)

After training, the speaker_id is used in the TTS WebSocket API with
X-Api-Resource-Id set to seed-icl-1.0 / seed-icl-2.0.
"""

import base64
import json
import uuid
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_db
from ..models import VoiceClone, ProviderConfig
from ..providers.base import ProviderType
from ..providers.registry import ProviderRegistry
from ..schemas.voice import (
    VoiceCloneResponse, VoiceCloneUpdate, VoicePreviewResponse,
)

router = APIRouter()

VOICE_CLONE_API = "https://openspeech.bytedance.com/api/v3/tts/voice_clone"
GET_VOICE_API = "https://openspeech.bytedance.com/api/v3/tts/get_voice"


async def _get_doubao_tts_credentials(db: AsyncSession) -> tuple[str, str]:
    """Get Doubao TTS app_id and api_key from provider config."""
    result = await db.execute(
        select(ProviderConfig).where(
            ProviderConfig.provider_type == "tts",
            ProviderConfig.provider_key == "doubao_tts",
            ProviderConfig.is_active == True,
        )
    )
    provider_config = result.scalars().first()
    if not provider_config:
        raise HTTPException(status_code=400, detail="未找到可用的豆包 TTS 配置，请先在 Provider 设置中配置")

    extra_config = json.loads(provider_config.config_json) if provider_config.config_json else {}
    app_id = extra_config.get("app_id", "")

    settings = get_settings()
    api_key = provider_config.api_key or getattr(settings, "doubao_api_key", "")

    if not app_id:
        raise HTTPException(status_code=400, detail="豆包 TTS 缺少 APP ID 配置")
    if not api_key:
        raise HTTPException(status_code=400, detail="豆包 TTS 缺少 API Key 配置")

    return app_id, api_key


@router.get("", response_model=list[VoiceCloneResponse])
async def list_voice_clones(db: AsyncSession = Depends(get_db)):
    """List all cloned voices."""
    result = await db.execute(
        select(VoiceClone).order_by(VoiceClone.created_at.desc())
    )
    return [VoiceCloneResponse.model_validate(v) for v in result.scalars().all()]


@router.get("/{voice_id}", response_model=VoiceCloneResponse)
async def get_voice_clone(voice_id: str, db: AsyncSession = Depends(get_db)):
    """Get a specific cloned voice."""
    voice = await db.get(VoiceClone, voice_id)
    if not voice:
        raise HTTPException(status_code=404, detail="Voice clone not found")
    return VoiceCloneResponse.model_validate(voice)


@router.post("/clone", response_model=VoiceCloneResponse, status_code=201)
async def create_voice_clone(
    name: str = Form(...),
    speaker_id: str = Form(..., description="从火山引擎控制台获取的音色 ID"),
    provider_key: str = Form(default="doubao_tts"),
    reference_text: str = Form(default=None),
    is_default: bool = Form(default=False),
    audio_file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload reference audio, call Volcano Engine training API, create cloned voice.

    Flow:
    1. Save audio locally
    2. Call POST /api/v3/tts/voice_clone to start training
    3. Store speaker_id + training status
    """
    # Validate file type
    ext = (audio_file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ("mp3", "wav", "ogg", "flac", "m4a", "aac", "pcm"):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的音频格式: {ext}。支持 mp3/wav/ogg/flac/m4a/aac/pcm"
        )

    # Save reference audio file locally
    settings = get_settings()
    voice_dir = Path(settings.storage.base_dir) / "voices"
    voice_dir.mkdir(parents=True, exist_ok=True)

    file_id = uuid.uuid4().hex[:12]
    filename = f"ref_{file_id}.{ext}"
    file_path = voice_dir / filename

    content = await audio_file.read()
    file_path.write_bytes(content)

    # Get credentials
    app_id, api_key = await _get_doubao_tts_credentials(db)

    # Call Volcano Engine voice_clone training API
    audio_b64 = base64.b64encode(content).decode()
    train_payload = {
        "speaker_id": speaker_id,
        "audio": {
            "data": audio_b64,
            "format": ext if ext != "mp3" else "mp3",
        },
        "language": 0,  # 中文
    }
    if reference_text:
        train_payload["audio"]["text"] = reference_text

    train_headers = {
        "Content-Type": "application/json",
        "X-Api-App-Key": app_id,
        "X-Api-Access-Key": api_key,
        "X-Api-Request-Id": str(uuid.uuid4()),
    }

    training_status = 0
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                VOICE_CLONE_API,
                json=train_payload,
                headers=train_headers,
            )
            resp_data = resp.json()

            if resp.status_code == 200:
                training_status = resp_data.get("status", 2)
            else:
                error_code = resp_data.get("code", resp.status_code)
                error_msg = resp_data.get("message", resp.text)
                raise HTTPException(
                    status_code=400,
                    detail=f"火山引擎声音训练失败 ({error_code}): {error_msg}"
                )
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail=f"声音训练请求失败: {e}")

    # If setting as default, unset others
    if is_default:
        result = await db.execute(
            select(VoiceClone).where(VoiceClone.is_default == True)
        )
        for existing in result.scalars().all():
            existing.is_default = False

    voice = VoiceClone(
        name=name,
        provider_key=provider_key,
        speaker_id=speaker_id,
        reference_audio_path=str(file_path),
        reference_text=reference_text if reference_text else None,
        training_status=training_status,
        is_default=is_default,
    )
    db.add(voice)
    await db.flush()
    return VoiceCloneResponse.model_validate(voice)


@router.post("/{voice_id}/refresh-status", response_model=VoiceCloneResponse)
async def refresh_training_status(voice_id: str, db: AsyncSession = Depends(get_db)):
    """Query Volcano Engine for the latest training status of a cloned voice."""
    voice = await db.get(VoiceClone, voice_id)
    if not voice:
        raise HTTPException(status_code=404, detail="Voice clone not found")

    app_id, api_key = await _get_doubao_tts_credentials(db)

    headers = {
        "Content-Type": "application/json",
        "X-Api-App-Key": app_id,
        "X-Api-Access-Key": api_key,
        "X-Api-Request-Id": str(uuid.uuid4()),
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                GET_VOICE_API,
                json={"speaker_id": voice.speaker_id},
                headers=headers,
            )
            resp_data = resp.json()

            if resp.status_code == 200:
                voice.training_status = resp_data.get("status", voice.training_status)
            else:
                error_code = resp_data.get("code", resp.status_code)
                error_msg = resp_data.get("message", "")
                raise HTTPException(
                    status_code=400,
                    detail=f"查询训练状态失败 ({error_code}): {error_msg}"
                )
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail=f"查询训练状态请求失败: {e}")

    await db.flush()
    return VoiceCloneResponse.model_validate(voice)


@router.put("/{voice_id}", response_model=VoiceCloneResponse)
async def update_voice_clone(
    voice_id: str,
    data: VoiceCloneUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a cloned voice (name, reference_text, is_default)."""
    voice = await db.get(VoiceClone, voice_id)
    if not voice:
        raise HTTPException(status_code=404, detail="Voice clone not found")

    update_fields = data.model_dump(exclude_unset=True)

    # If setting as default, unset others
    if update_fields.get("is_default"):
        result = await db.execute(
            select(VoiceClone).where(
                VoiceClone.is_default == True,
                VoiceClone.id != voice_id,
            )
        )
        for existing in result.scalars().all():
            existing.is_default = False

    for field, value in update_fields.items():
        setattr(voice, field, value)

    await db.flush()
    return VoiceCloneResponse.model_validate(voice)


@router.delete("/{voice_id}", status_code=204)
async def delete_voice_clone(voice_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a cloned voice and its reference audio file."""
    voice = await db.get(VoiceClone, voice_id)
    if not voice:
        raise HTTPException(status_code=404, detail="Voice clone not found")

    # Delete reference audio file
    ref_path = Path(voice.reference_audio_path)
    if ref_path.exists():
        ref_path.unlink(missing_ok=True)

    await db.delete(voice)


@router.post("/{voice_id}/preview", response_model=VoicePreviewResponse)
async def preview_voice_clone(voice_id: str, db: AsyncSession = Depends(get_db)):
    """Synthesize a short preview using the cloned voice's speaker_id.

    Uses the trained speaker_id via the normal TTS WebSocket with ICL resource.
    """
    voice = await db.get(VoiceClone, voice_id)
    if not voice:
        raise HTTPException(status_code=404, detail="Voice clone not found")

    if voice.training_status not in (2, 4):
        raise HTTPException(
            status_code=400,
            detail=f"声音尚未训练完成（当前状态: {voice.training_status}）。请先等待训练完成或刷新状态。"
        )

    if not voice.speaker_id:
        raise HTTPException(status_code=400, detail="缺少 speaker_id")

    # Find the TTS provider config
    result = await db.execute(
        select(ProviderConfig).where(
            ProviderConfig.provider_type == "tts",
            ProviderConfig.provider_key == voice.provider_key,
            ProviderConfig.is_active == True,
        )
    )
    provider_config = result.scalars().first()
    if not provider_config:
        result = await db.execute(
            select(ProviderConfig).where(
                ProviderConfig.provider_type == "tts",
                ProviderConfig.is_active == True,
            )
        )
        provider_config = result.scalars().first()

    if not provider_config:
        raise HTTPException(status_code=400, detail="未找到可用的 TTS 提供商，请先配置")

    settings = get_settings()
    api_key = provider_config.api_key
    if not api_key:
        key_map = {
            "doubao_tts": getattr(settings, "doubao_api_key", ""),
            "openai_tts": getattr(settings, "openai_api_key", ""),
            "minimax_tts": getattr(settings, "minimax_api_key", ""),
        }
        api_key = key_map.get(provider_config.provider_key, "")

    extra_config = json.loads(provider_config.config_json) if provider_config.config_json else {}

    try:
        provider_type = ProviderType(provider_config.provider_type)
        tts_provider = ProviderRegistry.instantiate(
            provider_type=provider_type,
            key=provider_config.provider_key,
            api_key=api_key or "",
            api_base_url=provider_config.api_base_url or "",
            model_id=provider_config.model_id or "",
            config=extra_config,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS 提供商初始化失败: {e}")

    # Synthesize preview using the trained speaker_id
    from ..providers.tts.base import TTSRequest

    preview_text = "这是一段声音克隆的预览测试，用来确认声音效果是否满意。"
    output_dir = Path(settings.storage.base_dir) / "voices" / "previews"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"preview_{voice_id[:8]}_{uuid.uuid4().hex[:6]}.mp3"

    # Use speaker_id as voice_id; the provider will use ICL resource_id
    request = TTSRequest(
        text=preview_text,
        voice_id=voice.speaker_id,
        use_icl=True,
    )

    try:
        response = await tts_provider.synthesize(request, output_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"语音合成预览失败: {e}")

    rel_path = str(response.file_path)

    return VoicePreviewResponse(
        audio_path=rel_path,
        duration=response.duration,
    )
