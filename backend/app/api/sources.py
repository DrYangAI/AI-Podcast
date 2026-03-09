"""Content source management API routes."""

import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import ContentSource, FetchedTopic, Project, PipelineStep
from ..schemas.source import (
    ContentSourceCreate, ContentSourceUpdate, ContentSourceResponse,
    FetchedTopicResponse, UrlExtractRequest, UrlExtractResponse,
    HotTopicRequest, HotTopicResponse, HotTopicItem, HotTopicProjectCreate,
)
from ..schemas.project import ProjectResponse
from ..utils.rss_parser import parse_feed
from ..utils.url_extractor import extract_article

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("", response_model=list[ContentSourceResponse])
async def list_sources(db: AsyncSession = Depends(get_db)):
    """List all content sources."""
    result = await db.execute(select(ContentSource).order_by(ContentSource.created_at.desc()))
    return [ContentSourceResponse.model_validate(s) for s in result.scalars().all()]


@router.post("", response_model=ContentSourceResponse, status_code=201)
async def create_source(data: ContentSourceCreate, db: AsyncSession = Depends(get_db)):
    """Add RSS feed or scrape target."""
    source = ContentSource(
        name=data.name,
        source_type=data.source_type,
        url=data.url,
        category=data.category,
        fetch_interval=data.fetch_interval,
        config_json=json.dumps(data.config) if data.config else None,
    )
    db.add(source)
    await db.flush()
    return ContentSourceResponse.model_validate(source)


@router.put("/{source_id}", response_model=ContentSourceResponse)
async def update_source(source_id: str, data: ContentSourceUpdate,
                         db: AsyncSession = Depends(get_db)):
    """Update source configuration."""
    result = await db.execute(select(ContentSource).where(ContentSource.id == source_id))
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    update_data = data.model_dump(exclude_unset=True)
    if "config" in update_data:
        update_data["config_json"] = json.dumps(update_data.pop("config"))

    for field, value in update_data.items():
        setattr(source, field, value)

    await db.flush()
    return ContentSourceResponse.model_validate(source)


@router.delete("/{source_id}", status_code=204)
async def delete_source(source_id: str, db: AsyncSession = Depends(get_db)):
    """Remove source."""
    result = await db.execute(select(ContentSource).where(ContentSource.id == source_id))
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    await db.delete(source)


@router.get("/{source_id}/topics", response_model=list[FetchedTopicResponse])
async def list_topics(source_id: str, db: AsyncSession = Depends(get_db)):
    """List fetched topics from a source."""
    result = await db.execute(
        select(FetchedTopic)
        .where(FetchedTopic.source_id == source_id)
        .order_by(FetchedTopic.fetched_at.desc())
    )
    return [FetchedTopicResponse.model_validate(t) for t in result.scalars().all()]


@router.post("/topics/{topic_id}/create-project", response_model=ProjectResponse, status_code=201)
async def create_project_from_topic(topic_id: str, db: AsyncSession = Depends(get_db)):
    """Create a project from a fetched topic."""
    result = await db.execute(select(FetchedTopic).where(FetchedTopic.id == topic_id))
    topic = result.scalar_one_or_none()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    project = Project(
        title=topic.title,
        topic=topic.title,
        source_type="rss",
        source_url=topic.url,
    )
    db.add(project)
    await db.flush()

    for i, step_name in enumerate(PipelineStep.STEP_NAMES):
        step = PipelineStep(
            project_id=project.id,
            step_name=step_name,
            step_order=i,
            status="completed" if step_name == "topic_input" else "pending",
        )
        db.add(step)

    topic.is_used = True
    topic.project_id = project.id

    await db.flush()
    return ProjectResponse.model_validate(project)


@router.post("/{source_id}/fetch", response_model=list[FetchedTopicResponse])
async def fetch_source(source_id: str, db: AsyncSession = Depends(get_db)):
    """Manually trigger fetching topics from an RSS source."""
    result = await db.execute(select(ContentSource).where(ContentSource.id == source_id))
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    try:
        items = await parse_feed(source.url)
    except Exception as e:
        logger.error(f"Failed to fetch feed {source.url}: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to fetch feed: {str(e)}")

    # Get existing topic URLs to avoid duplicates
    existing_result = await db.execute(
        select(FetchedTopic.url).where(FetchedTopic.source_id == source_id)
    )
    existing_urls = {row[0] for row in existing_result.all() if row[0]}

    new_topics = []
    for item in items:
        if item.url in existing_urls:
            continue
        topic = FetchedTopic(
            source_id=source_id,
            title=item.title,
            url=item.url,
            summary=item.summary,
        )
        db.add(topic)
        new_topics.append(topic)

    source.last_fetched_at = datetime.now()
    await db.flush()

    # Refresh to get generated IDs
    for t in new_topics:
        await db.refresh(t)

    return [FetchedTopicResponse.model_validate(t) for t in new_topics]


@router.post("/extract-url", response_model=UrlExtractResponse)
async def extract_url_content(data: UrlExtractRequest):
    """Extract article content from a URL."""
    try:
        article = await extract_article(data.url)
        return UrlExtractResponse(
            title=article.title,
            content=article.content,
            url=article.url,
        )
    except Exception as e:
        logger.error(f"Failed to extract content from {data.url}: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to extract content: {str(e)}")


# ---- Hot topic recommendations ----

@router.post("/hotlist/recommend", response_model=HotTopicResponse)
async def get_hot_topic_recommendations(data: HotTopicRequest | None = None):
    """Scrape Chinese hot lists and filter health-related topics using AI."""
    from ..services.hotlist_service import HotlistService

    if data is None:
        data = HotTopicRequest()

    service = HotlistService()
    try:
        recommendations, total_scraped = await service.get_health_recommendations(
            sources=data.sources,
            max_results=data.max_results,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Hot topic recommendation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"推荐获取失败: {str(e)}")

    return HotTopicResponse(
        items=[HotTopicItem(
            title=r.title,
            source=r.source,
            source_name=r.source_name,
            url=r.url,
            rank=r.rank,
            heat=r.heat,
            relevance_score=r.relevance_score,
            health_angle=r.health_angle,
            category=r.category,
        ) for r in recommendations],
        total_scraped=total_scraped,
        ai_filtered=len(recommendations),
    )


@router.post("/hotlist/create-project", response_model=ProjectResponse, status_code=201)
async def create_project_from_hotlist(
    data: HotTopicProjectCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a project from a hot topic recommendation."""
    topic = f"{data.title}\n\n切入角度：{data.health_angle}" if data.health_angle else data.title

    project = Project(
        title=data.title,
        topic=topic,
        source_type="hotlist",
        source_url=data.source_url,
    )
    db.add(project)
    await db.flush()

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
