"""Pipeline execution API routes."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Project, PipelineStep
from ..schemas.project import PipelineStepResponse, PipelineRunRequest
from ..services.pipeline_service import PipelineService

router = APIRouter()


async def _ensure_portrait_step(db: AsyncSession, project_id: str) -> None:
    """旧项目兼容：若缺少 portrait_composite 步骤则自动补充。"""
    result = await db.execute(
        select(PipelineStep)
        .where(PipelineStep.project_id == project_id, PipelineStep.step_name == "portrait_composite")
    )
    if result.scalar_one_or_none() is None:
        project = await db.get(Project, project_id)
        portrait_enabled = getattr(project, "portrait_composite_enabled", True) if project else True
        new_step = PipelineStep(
            project_id=project_id,
            step_name="portrait_composite",
            step_order=7,
            status="pending" if portrait_enabled else "skipped",
        )
        db.add(new_step)
        await db.commit()


@router.get("/projects/{project_id}/pipeline", response_model=list[PipelineStepResponse])
async def get_pipeline_status(project_id: str, db: AsyncSession = Depends(get_db)):
    """Get all pipeline step statuses for a project."""
    result = await db.execute(
        select(PipelineStep)
        .where(PipelineStep.project_id == project_id)
        .order_by(PipelineStep.step_order)
    )
    steps = list(result.scalars().all())
    if not steps:
        raise HTTPException(status_code=404, detail="Project not found")

    # 旧项目兼容
    step_names = {s.step_name for s in steps}
    if "portrait_composite" not in step_names:
        await _ensure_portrait_step(db, project_id)
        # 重新查询以获取最新数据
        result = await db.execute(
            select(PipelineStep)
            .where(PipelineStep.project_id == project_id)
            .order_by(PipelineStep.step_order)
        )
        steps = list(result.scalars().all())

    return [PipelineStepResponse.model_validate(s) for s in sorted(steps, key=lambda s: s.step_order)]


@router.post("/projects/{project_id}/pipeline/run", status_code=202)
async def run_pipeline(
    project_id: str,
    data: PipelineRunRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Run full pipeline or from a specific step."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    service = PipelineService()
    background_tasks.add_task(
        service.run_pipeline, project_id, data.from_step, data.provider_overrides
    )

    return {"message": "Pipeline started", "project_id": project_id, "from_step": data.from_step}


@router.post("/projects/{project_id}/pipeline/steps/{step_name}/run", status_code=202)
async def run_single_step(
    project_id: str,
    step_name: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Run a single pipeline step."""
    # 旧项目兼容：确保 portrait_composite 步骤存在
    if step_name == "portrait_composite":
        await _ensure_portrait_step(db, project_id)

    result = await db.execute(
        select(PipelineStep)
        .where(PipelineStep.project_id == project_id, PipelineStep.step_name == step_name)
    )
    step = result.scalar_one_or_none()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")

    service = PipelineService()
    background_tasks.add_task(service.run_step, project_id, step_name)

    return {"message": f"Step '{step_name}' started", "project_id": project_id}


@router.post("/projects/{project_id}/pipeline/steps/{step_name}/retry", status_code=202)
async def retry_step(
    project_id: str,
    step_name: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Retry a failed step."""
    # 旧项目兼容
    if step_name == "portrait_composite":
        await _ensure_portrait_step(db, project_id)

    result = await db.execute(
        select(PipelineStep)
        .where(PipelineStep.project_id == project_id, PipelineStep.step_name == step_name)
    )
    step = result.scalar_one_or_none()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")
    if step.status != "failed":
        raise HTTPException(status_code=400, detail="Only failed steps can be retried")

    # Reset step status
    step.status = "pending"
    step.error_message = None
    step.started_at = None
    step.completed_at = None
    await db.commit()

    service = PipelineService()
    background_tasks.add_task(service.run_step, project_id, step_name)

    return {"message": f"Step '{step_name}' retry started", "project_id": project_id}
