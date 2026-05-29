"""Prompt template API routes."""

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.prompt_template import PromptTemplate
from ..schemas.prompt_template import (
    PromptTemplateResponse,
    PromptTemplateUpdate,
    PromptTemplateHistoryResponse,
)
from ..services.prompt_template_service import PromptTemplateService, VARIABLE_DESCRIPTIONS

router = APIRouter()


def _template_to_response(t: PromptTemplate) -> PromptTemplateResponse:
    variables = json.loads(t.variables) if t.variables else []
    variable_descs = {v: VARIABLE_DESCRIPTIONS.get(v, v) for v in variables}
    return PromptTemplateResponse(
        id=t.id,
        step_name=t.step_name,
        description=t.description,
        system_prompt=t.system_prompt,
        user_prompt_template=t.user_prompt_template,
        temperature=t.temperature,
        max_tokens=t.max_tokens,
        variables=variables,
        variable_descriptions=variable_descs,
        extra_config=json.loads(t.extra_config) if t.extra_config else None,
        updated_at=t.updated_at,
        created_at=t.created_at,
    )


# --- System-level template endpoints ---

@router.get("/", response_model=list[PromptTemplateResponse])
async def list_templates(db: AsyncSession = Depends(get_db)):
    """List all system prompt templates."""
    templates = await PromptTemplateService.list_all(db)
    return [_template_to_response(t) for t in templates]


@router.get("/{step_name}", response_model=PromptTemplateResponse)
async def get_template(step_name: str, db: AsyncSession = Depends(get_db)):
    """Get a template by step name."""
    template = await PromptTemplateService.get_by_step(db, step_name)
    if not template:
        raise HTTPException(status_code=404, detail=f"Template not found: {step_name}")
    return _template_to_response(template)


@router.put("/{step_name}", response_model=PromptTemplateResponse)
async def update_template(step_name: str, data: PromptTemplateUpdate,
                           db: AsyncSession = Depends(get_db)):
    """Update a system prompt template."""
    try:
        template = await PromptTemplateService.update_template(
            db, step_name, data.model_dump(exclude_none=True)
        )
        return _template_to_response(template)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{step_name}/reset", response_model=PromptTemplateResponse)
async def reset_template(step_name: str, db: AsyncSession = Depends(get_db)):
    """Reset template to default."""
    try:
        template = await PromptTemplateService.reset_to_default(db, step_name)
        return _template_to_response(template)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{step_name}/history", response_model=list[PromptTemplateHistoryResponse])
async def get_template_history(step_name: str, db: AsyncSession = Depends(get_db)):
    """Get version history for a template."""
    history = await PromptTemplateService.get_history(db, step_name)
    result = []
    for h in history:
        result.append(PromptTemplateHistoryResponse(
            id=h.id,
            template_id=h.template_id,
            step_name=h.step_name,
            version=h.version,
            system_prompt=h.system_prompt,
            user_prompt_template=h.user_prompt_template,
            temperature=h.temperature,
            max_tokens=h.max_tokens,
            extra_config=json.loads(h.extra_config) if h.extra_config else None,
            change_source=h.change_source,
            created_at=h.created_at,
        ))
    return result


@router.post("/{step_name}/restore/{version_id}", response_model=PromptTemplateResponse)
async def restore_version(step_name: str, version_id: str,
                           db: AsyncSession = Depends(get_db)):
    """Restore a template from a history version."""
    try:
        template = await PromptTemplateService.restore_version(db, step_name, version_id)
        return _template_to_response(template)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
