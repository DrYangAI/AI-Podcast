"""Project CRUD API routes."""

import json
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import get_settings
from ..database import get_db
from ..models import Project, PipelineStep, Article, Segment, ImageAsset, Script, AudioAsset, VideoOutput
from ..schemas.project import (
    ProjectCreate, ProjectUpdate, ProjectResponse, ProjectDetailResponse,
    PipelineStepResponse, ArticleResponse, ArticleUpdate,
    SegmentResponse, SegmentUpdate, ImageAssetResponse, ImageRegenerateRequest,
    ScriptResponse, ScriptUpdate, AudioAssetResponse, VideoOutputResponse,
    PaginatedResponse,
)

router = APIRouter()


@router.get("", response_model=PaginatedResponse)
async def list_projects(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List all projects with pagination."""
    query = select(Project).order_by(Project.created_at.desc())
    if status:
        query = query.where(Project.status == status)

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Paginate
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    projects = result.scalars().all()

    return PaginatedResponse(
        items=[ProjectResponse.model_validate(p) for p in projects],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(data: ProjectCreate, db: AsyncSession = Depends(get_db)):
    """Create a new project and initialize pipeline steps."""
    project = Project(
        title=data.title,
        topic=data.topic,
        source_type=data.source_type,
        source_url=data.source_url,
        aspect_ratio=data.aspect_ratio,
        video_template=data.video_template,
    )
    db.add(project)
    await db.flush()

    # Initialize pipeline steps
    for i, step_name in enumerate(PipelineStep.STEP_NAMES):
        step = PipelineStep(
            project_id=project.id,
            step_name=step_name,
            step_order=i,
            status="completed" if step_name == "topic_input" else "pending",
        )
        db.add(step)

    await db.flush()
    return ProjectResponse.model_validate(project)


@router.get("/{project_id}", response_model=ProjectDetailResponse)
async def get_project(project_id: str, db: AsyncSession = Depends(get_db)):
    """Get project detail with all related data."""
    result = await db.execute(
        select(Project)
        .where(Project.id == project_id)
        .options(
            selectinload(Project.pipeline_steps),
            selectinload(Project.article),
            selectinload(Project.script),
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectDetailResponse.model_validate(project)


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(project_id: str, data: ProjectUpdate, db: AsyncSession = Depends(get_db)):
    """Update project settings."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(project, field, value)

    await db.flush()
    await db.refresh(project)
    return ProjectResponse.model_validate(project)


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: str, db: AsyncSession = Depends(get_db)):
    """Delete project and all associated data."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    await db.delete(project)


@router.post("/{project_id}/duplicate", response_model=ProjectResponse, status_code=201)
async def duplicate_project(project_id: str, db: AsyncSession = Depends(get_db)):
    """Clone a project."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    original = result.scalar_one_or_none()
    if not original:
        raise HTTPException(status_code=404, detail="Project not found")

    new_project = Project(
        title=f"{original.title} (copy)",
        topic=original.topic,
        source_type=original.source_type,
        aspect_ratio=original.aspect_ratio,
        video_template=original.video_template,
    )
    db.add(new_project)
    await db.flush()

    for i, step_name in enumerate(PipelineStep.STEP_NAMES):
        step = PipelineStep(
            project_id=new_project.id,
            step_name=step_name,
            step_order=i,
            status="completed" if step_name == "topic_input" else "pending",
        )
        db.add(step)

    await db.flush()
    return ProjectResponse.model_validate(new_project)


# --- Article endpoints ---

@router.get("/{project_id}/article", response_model=ArticleResponse)
async def get_article(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Article).where(Article.project_id == project_id))
    article = result.scalar_one_or_none()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return ArticleResponse.model_validate(article)


@router.put("/{project_id}/article", response_model=ArticleResponse)
async def update_article(project_id: str, data: ArticleUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Article).where(Article.project_id == project_id))
    article = result.scalar_one_or_none()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(article, field, value)
    article.is_manual = True
    article.version += 1
    if data.content:
        article.word_count = len(data.content)

    await db.flush()
    return ArticleResponse.model_validate(article)


# --- Segment endpoints ---

@router.get("/{project_id}/segments", response_model=list[SegmentResponse])
async def list_segments(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Segment)
        .where(Segment.project_id == project_id)
        .order_by(Segment.segment_order)
    )
    return [SegmentResponse.model_validate(s) for s in result.scalars().all()]


@router.put("/{project_id}/segments/{segment_id}", response_model=SegmentResponse)
async def update_segment(project_id: str, segment_id: str, data: SegmentUpdate,
                          db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Segment).where(Segment.id == segment_id, Segment.project_id == project_id)
    )
    segment = result.scalar_one_or_none()
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(segment, field, value)

    await db.flush()
    return SegmentResponse.model_validate(segment)


# --- Image endpoints ---

@router.get("/{project_id}/images", response_model=list[ImageAssetResponse])
async def list_images(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ImageAsset).where(ImageAsset.project_id == project_id)
    )
    return [ImageAssetResponse.model_validate(i) for i in result.scalars().all()]


@router.post("/{project_id}/segments/{segment_id}/image/regenerate", response_model=ImageAssetResponse)
async def regenerate_segment_image(
    project_id: str,
    segment_id: str,
    data: ImageRegenerateRequest | None = None,
    background_tasks: BackgroundTasks = None,
    db: AsyncSession = Depends(get_db),
):
    """Regenerate a single image for a segment with optional custom prompt."""
    # Validate segment exists
    result = await db.execute(
        select(Segment).where(Segment.id == segment_id, Segment.project_id == project_id)
    )
    segment = result.scalar_one_or_none()
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")

    # Update prompt if provided (immediately visible)
    custom_prompt = data.prompt if data else None
    if custom_prompt is not None:
        segment.image_prompt = custom_prompt
        await db.flush()

    # Mark existing image as generating
    img_result = await db.execute(
        select(ImageAsset).where(ImageAsset.segment_id == segment_id)
    )
    image_asset = img_result.scalars().first()
    if image_asset:
        image_asset.status = "generating"
        await db.flush()

    await db.commit()

    # Run regeneration in background
    from ..services.image_service import ImageService
    service = ImageService()
    background_tasks.add_task(service.regenerate_single_image, project_id, segment_id, custom_prompt)

    return ImageAssetResponse.model_validate(image_asset) if image_asset else ImageAssetResponse(
        id="", segment_id=segment_id, file_path="", prompt_used=custom_prompt,
        width=None, height=None, is_manual=False, status="generating",
        created_at=datetime.now(),
    )


@router.post("/{project_id}/segments/{segment_id}/image/upload", response_model=ImageAssetResponse)
async def upload_segment_image(
    project_id: str,
    segment_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload a custom image for a segment."""
    # Validate segment exists
    result = await db.execute(
        select(Segment).where(Segment.id == segment_id, Segment.project_id == project_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Segment not found")

    # Validate file type
    allowed_types = {"image/png", "image/jpeg", "image/webp", "image/gif"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {file.content_type}")

    # Save file
    settings = get_settings()
    output_dir = Path(settings.storage.base_dir) / "images" / project_id
    output_dir.mkdir(parents=True, exist_ok=True)

    ext = file.filename.rsplit(".", 1)[-1] if file.filename and "." in file.filename else "png"
    filename = f"{segment_id}_manual_{uuid.uuid4().hex[:8]}.{ext}"
    file_path = output_dir / filename

    content = await file.read()
    file_path.write_bytes(content)

    # Update or create ImageAsset
    result = await db.execute(
        select(ImageAsset).where(ImageAsset.segment_id == segment_id)
    )
    image_asset = result.scalars().first()

    rel_path = str(file_path.relative_to(Path(settings.storage.base_dir).parent))

    if image_asset:
        image_asset.file_path = rel_path
        image_asset.is_manual = True
        image_asset.status = "completed"
        image_asset.file_size = len(content)
        image_asset.prompt_used = None
        image_asset.provider_id = None
    else:
        image_asset = ImageAsset(
            segment_id=segment_id,
            project_id=project_id,
            file_path=rel_path,
            is_manual=True,
            status="completed",
            file_size=len(content),
        )
        db.add(image_asset)

    await db.flush()
    await db.refresh(image_asset)
    return ImageAssetResponse.model_validate(image_asset)


# --- Script endpoints ---

@router.get("/{project_id}/script", response_model=ScriptResponse)
async def get_script(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Script).where(Script.project_id == project_id))
    script = result.scalar_one_or_none()
    if not script:
        raise HTTPException(status_code=404, detail="Script not found")
    return ScriptResponse.model_validate(script)


@router.put("/{project_id}/script", response_model=ScriptResponse)
async def update_script(project_id: str, data: ScriptUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Script).where(Script.project_id == project_id))
    script = result.scalar_one_or_none()
    if not script:
        raise HTTPException(status_code=404, detail="Script not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(script, field, value)
    script.is_manual = True
    script.version += 1

    await db.flush()
    return ScriptResponse.model_validate(script)


# --- Audio endpoints ---

@router.get("/{project_id}/audio", response_model=AudioAssetResponse)
async def get_audio(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AudioAsset).where(AudioAsset.project_id == project_id))
    audio = result.scalar_one_or_none()
    if not audio:
        raise HTTPException(status_code=404, detail="Audio not found")
    return AudioAssetResponse.model_validate(audio)


# --- Video endpoints ---

@router.get("/{project_id}/videos", response_model=list[VideoOutputResponse])
async def list_videos(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(VideoOutput).where(VideoOutput.project_id == project_id)
    )
    return [VideoOutputResponse.model_validate(v) for v in result.scalars().all()]
