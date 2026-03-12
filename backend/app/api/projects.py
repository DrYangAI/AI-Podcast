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
from ..models import Project, PipelineStep, Article, Segment, ImageAsset, Script, AudioAsset, VideoOutput, PublishAsset
from ..schemas.project import (
    ProjectCreate, ProjectUpdate, ProjectResponse, ProjectDetailResponse,
    PipelineStepResponse, ArticleResponse, ArticleUpdate,
    SegmentResponse, SegmentUpdate, ImageAssetResponse, ImageRegenerateRequest,
    ScriptResponse, ScriptUpdate, AudioAssetResponse, VideoOutputResponse,
    PaginatedResponse,
)
from ..schemas.publish import (
    PublishAssetResponse, PublishAssetUpdate,
    CoverRegenerateRequest, CoverPromptResponse, CoverPromptUpdate,
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
        portrait_composite_enabled=data.portrait_composite_enabled,
        portrait_bg_color=data.portrait_bg_color,
        portrait_title_text=data.portrait_title_text,
    )
    db.add(project)
    await db.flush()

    # Initialize pipeline steps
    portrait_enabled = data.portrait_composite_enabled
    for i, step_name in enumerate(PipelineStep.STEP_NAMES):
        if step_name == "topic_input":
            initial_status = "completed"
        elif step_name == "portrait_composite" and not portrait_enabled:
            initial_status = "skipped"
        else:
            initial_status = "pending"

        step = PipelineStep(
            project_id=project.id,
            step_name=step_name,
            step_order=i,
            status=initial_status,
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

    update_fields = data.model_dump(exclude_unset=True)
    for field, value in update_fields.items():
        setattr(project, field, value)

    # 当切换竖屏合成开关时，同步更新 pipeline step 状态
    if "portrait_composite_enabled" in update_fields:
        step_result = await db.execute(
            select(PipelineStep).where(
                PipelineStep.project_id == project_id,
                PipelineStep.step_name == "portrait_composite",
            )
        )
        portrait_step = step_result.scalar_one_or_none()
        if portrait_step:
            if update_fields["portrait_composite_enabled"]:
                # 启用：从 skipped 恢复为 pending（仅当当前是 skipped 时）
                if portrait_step.status == "skipped":
                    portrait_step.status = "pending"
            else:
                # 禁用：标记为 skipped（除非正在运行）
                if portrait_step.status not in ("in_progress",):
                    portrait_step.status = "skipped"

    # 当更新了图片宽高时，自动同步 aspect_ratio
    if "image_width" in update_fields or "image_height" in update_fields:
        w = project.image_width
        h = project.image_height
        if w and h:
            ratio = w / h
            if abs(ratio - 16 / 9) < 0.05:
                project.aspect_ratio = "16:9"
            elif abs(ratio - 9 / 16) < 0.05:
                project.aspect_ratio = "9:16"
            elif abs(ratio - 1) < 0.05:
                project.aspect_ratio = "1:1"
            else:
                project.aspect_ratio = f"{w}:{h}"

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
        portrait_composite_enabled=getattr(original, "portrait_composite_enabled", True),
        portrait_bg_color=getattr(original, "portrait_bg_color", "#1A1A2E"),
        portrait_title_text=getattr(original, "portrait_title_text", None),
    )
    db.add(new_project)
    await db.flush()

    portrait_enabled = getattr(original, "portrait_composite_enabled", True)
    for i, step_name in enumerate(PipelineStep.STEP_NAMES):
        if step_name == "topic_input":
            initial_status = "completed"
        elif step_name == "portrait_composite" and not portrait_enabled:
            initial_status = "skipped"
        else:
            initial_status = "pending"

        step = PipelineStep(
            project_id=new_project.id,
            step_name=step_name,
            step_order=i,
            status=initial_status,
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


@router.post("/{project_id}/generate-prompts")
async def generate_image_prompts(project_id: str, db: AsyncSession = Depends(get_db)):
    """Generate image prompts for all segments without generating images."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    from ..services.image_service import ImageService
    service = ImageService()
    try:
        prompts = await service.generate_prompts_only(project_id)
        return {"status": "ok", "prompts": prompts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{project_id}/segments/{segment_id}/image/regenerate", response_model=ImageAssetResponse)
async def regenerate_segment_image(
    project_id: str,
    segment_id: str,
    data: ImageRegenerateRequest | None = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),
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


# --- Publish assets endpoints ---
# NOTE: Static path endpoints (regenerate-cover, cover-prompt, from-segment)
# MUST be defined before dynamic {platform} endpoints to avoid routing conflicts.

@router.get("/{project_id}/publish-assets", response_model=list[PublishAssetResponse])
async def list_publish_assets(project_id: str, db: AsyncSession = Depends(get_db)):
    """Get publish assets for all platforms."""
    result = await db.execute(
        select(PublishAsset).where(PublishAsset.project_id == project_id)
    )
    return [PublishAssetResponse.model_validate(a) for a in result.scalars().all()]


@router.post("/{project_id}/publish-assets/regenerate-cover")
async def regenerate_cover(
    project_id: str,
    data: CoverRegenerateRequest | None = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db),
):
    """Regenerate AI cover images for all platforms."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    custom_prompt = data.prompt if data else None
    from ..services.publish_service import PublishService
    service = PublishService()
    background_tasks.add_task(service.regenerate_covers, project_id, custom_prompt)

    return {"status": "ok", "message": "Cover regeneration started"}


@router.get("/{project_id}/publish-assets/cover-prompt")
async def get_cover_prompt(project_id: str, db: AsyncSession = Depends(get_db)):
    """Get the cover image generation prompt."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return CoverPromptResponse(prompt=project.cover_prompt)


@router.put("/{project_id}/publish-assets/cover-prompt")
async def update_cover_prompt(
    project_id: str,
    data: CoverPromptUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update the cover prompt without regenerating."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    project.cover_prompt = data.prompt
    await db.flush()
    return CoverPromptResponse(prompt=project.cover_prompt)


@router.post("/{project_id}/publish-assets/from-segment/{segment_id}")
async def use_segment_as_cover(
    project_id: str,
    segment_id: str,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db),
):
    """Use a segment image as cover base and re-derive all platform covers."""
    # Validate segment image exists
    result = await db.execute(
        select(ImageAsset).where(
            ImageAsset.segment_id == segment_id,
            ImageAsset.project_id == project_id,
        )
    )
    image_asset = result.scalar_one_or_none()
    if not image_asset or not image_asset.file_path:
        raise HTTPException(status_code=404, detail="No image found for this segment")

    from ..services.publish_service import PublishService
    service = PublishService()
    background_tasks.add_task(service.regenerate_from_segment, project_id, segment_id)

    return {"status": "ok", "message": "Cover re-generation started"}


@router.put("/{project_id}/publish-assets/{platform}", response_model=PublishAssetResponse)
async def update_publish_asset(
    project_id: str,
    platform: str,
    data: PublishAssetUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update title, description or tags for a platform."""
    result = await db.execute(
        select(PublishAsset).where(
            PublishAsset.project_id == project_id,
            PublishAsset.platform == platform,
        )
    )
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail=f"Publish asset not found for platform: {platform}")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(asset, field, value)

    await db.flush()
    await db.refresh(asset)
    return PublishAssetResponse.model_validate(asset)


@router.post("/{project_id}/publish-assets/{platform}/upload-cover", response_model=PublishAssetResponse)
async def upload_cover(
    project_id: str,
    platform: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload a custom cover image for a specific platform."""
    valid_platforms = {"weixin", "xiaohongshu", "douyin", "tencent_video", "toutiao"}
    if platform not in valid_platforms:
        raise HTTPException(status_code=400, detail=f"Invalid platform: {platform}")

    allowed_types = {"image/png", "image/jpeg", "image/webp"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {file.content_type}")

    content = await file.read()

    from ..services.publish_service import PublishService
    service = PublishService()
    await service.handle_cover_upload(project_id, platform, content, file.filename or "upload.png")

    # Return updated asset
    result = await db.execute(
        select(PublishAsset).where(
            PublishAsset.project_id == project_id,
            PublishAsset.platform == platform,
        )
    )
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Publish asset not found")
    await db.refresh(asset)
    return PublishAssetResponse.model_validate(asset)
