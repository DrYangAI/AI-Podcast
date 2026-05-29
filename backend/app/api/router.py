"""Central API router aggregation."""

from fastapi import APIRouter

from .projects import router as projects_router
from .pipeline import router as pipeline_router
from .providers import router as providers_router
from .sources import router as sources_router
from .utils import router as utils_router
from .voices import router as voices_router
from .prompt_templates import router as prompt_templates_router
from .settings import router as settings_router

api_router = APIRouter()

api_router.include_router(projects_router, prefix="/projects", tags=["Projects"])
api_router.include_router(pipeline_router, tags=["Pipeline"])
api_router.include_router(providers_router, prefix="/providers", tags=["Providers"])
api_router.include_router(voices_router, prefix="/voices", tags=["Voices"])
api_router.include_router(sources_router, prefix="/sources", tags=["Content Sources"])
api_router.include_router(utils_router, prefix="/utils", tags=["Utilities"])
api_router.include_router(prompt_templates_router, prefix="/prompt-templates", tags=["Prompt Templates"])
api_router.include_router(settings_router, prefix="/settings", tags=["Settings"])
