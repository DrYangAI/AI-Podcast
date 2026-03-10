"""Provider configuration API routes."""

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import ProviderConfig
from ..providers.base import ProviderType
from ..providers.registry import ProviderRegistry
from ..schemas.provider import (
    ProviderConfigCreate, ProviderConfigUpdate, ProviderConfigResponse,
    ProviderTypeInfo, ProviderTestResult,
)
from ..schemas.voice import PresetVoice

router = APIRouter()


@router.get("", response_model=list[ProviderConfigResponse])
async def list_providers(
    provider_type: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List all configured providers."""
    query = select(ProviderConfig)
    if provider_type:
        query = query.where(ProviderConfig.provider_type == provider_type)
    query = query.order_by(ProviderConfig.provider_type, ProviderConfig.name)
    result = await db.execute(query)
    return [ProviderConfigResponse.model_validate(p) for p in result.scalars().all()]


@router.get("/types", response_model=list[ProviderTypeInfo])
async def list_provider_types():
    """List available provider types and their implementations."""
    providers = ProviderRegistry.list_providers()
    return [
        ProviderTypeInfo(
            key=p.key,
            name=p.name,
            provider_type=p.provider_type.value,
            description=p.description,
            supported_models=p.supported_models,
            requires_api_key=p.requires_api_key,
        )
        for p in providers
    ]


@router.post("", response_model=ProviderConfigResponse, status_code=201)
async def create_provider(data: ProviderConfigCreate, db: AsyncSession = Depends(get_db)):
    """Add a new provider configuration."""
    provider = ProviderConfig(
        name=data.name,
        provider_type=data.provider_type,
        provider_key=data.provider_key,
        api_key=data.api_key,
        api_base_url=data.api_base_url,
        model_id=data.model_id,
        config_json=json.dumps(data.config) if data.config else None,
        is_default=data.is_default,
    )

    # If setting as default, unset other defaults of same type
    if data.is_default:
        result = await db.execute(
            select(ProviderConfig)
            .where(ProviderConfig.provider_type == data.provider_type, ProviderConfig.is_default == True)
        )
        for existing in result.scalars().all():
            existing.is_default = False

    db.add(provider)
    await db.flush()
    return ProviderConfigResponse.model_validate(provider)


@router.put("/{provider_id}", response_model=ProviderConfigResponse)
async def update_provider(provider_id: str, data: ProviderConfigUpdate,
                           db: AsyncSession = Depends(get_db)):
    """Update provider configuration."""
    result = await db.execute(select(ProviderConfig).where(ProviderConfig.id == provider_id))
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    update_data = data.model_dump(exclude_unset=True)
    if "config" in update_data:
        update_data["config_json"] = json.dumps(update_data.pop("config"))

    # If setting as default, unset other defaults
    if update_data.get("is_default"):
        existing_result = await db.execute(
            select(ProviderConfig)
            .where(
                ProviderConfig.provider_type == provider.provider_type,
                ProviderConfig.is_default == True,
                ProviderConfig.id != provider_id,
            )
        )
        for existing in existing_result.scalars().all():
            existing.is_default = False

    for field, value in update_data.items():
        setattr(provider, field, value)

    await db.flush()
    return ProviderConfigResponse.model_validate(provider)


@router.delete("/{provider_id}", status_code=204)
async def delete_provider(provider_id: str, db: AsyncSession = Depends(get_db)):
    """Remove provider configuration."""
    result = await db.execute(select(ProviderConfig).where(ProviderConfig.id == provider_id))
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    await db.delete(provider)


@router.get("/{provider_id}/voices", response_model=list[PresetVoice])
async def list_provider_voices(provider_id: str, db: AsyncSession = Depends(get_db)):
    """List available preset voices for a TTS provider."""
    result = await db.execute(select(ProviderConfig).where(ProviderConfig.id == provider_id))
    provider_config = result.scalar_one_or_none()
    if not provider_config:
        raise HTTPException(status_code=404, detail="Provider not found")

    if provider_config.provider_type != "tts":
        raise HTTPException(status_code=400, detail="This provider is not a TTS provider")

    try:
        provider_type = ProviderType(provider_config.provider_type)
        config = json.loads(provider_config.config_json) if provider_config.config_json else None
        provider = ProviderRegistry.instantiate(
            provider_type=provider_type,
            key=provider_config.provider_key,
            api_key=provider_config.api_key or "",
            api_base_url=provider_config.api_base_url or "",
            model_id=provider_config.model_id or "",
            config=config,
        )
        voices = await provider.list_voices()
        return [
            PresetVoice(
                id=v["id"],
                name=v.get("name", v["id"]),
                gender=v.get("gender"),
                language=v.get("language"),
                provider_key=provider_config.provider_key,
            )
            for v in voices
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取声音列表失败: {e}")


@router.post("/{provider_id}/test", response_model=ProviderTestResult)
async def test_provider(provider_id: str, db: AsyncSession = Depends(get_db)):
    """Test provider connectivity."""
    result = await db.execute(select(ProviderConfig).where(ProviderConfig.id == provider_id))
    provider_config = result.scalar_one_or_none()
    if not provider_config:
        raise HTTPException(status_code=404, detail="Provider not found")

    try:
        provider_type = ProviderType(provider_config.provider_type)
        config = json.loads(provider_config.config_json) if provider_config.config_json else None
        provider = ProviderRegistry.instantiate(
            provider_type=provider_type,
            key=provider_config.provider_key,
            api_key=provider_config.api_key or "",
            api_base_url=provider_config.api_base_url or "",
            model_id=provider_config.model_id or "",
            config=config,
        )
        success = await provider.validate_connection()
        return ProviderTestResult(
            success=success,
            message="Connection successful" if success else "Connection failed",
        )
    except ValueError as e:
        return ProviderTestResult(success=False, message=str(e))
    except Exception as e:
        return ProviderTestResult(success=False, message=f"Error: {str(e)}")
