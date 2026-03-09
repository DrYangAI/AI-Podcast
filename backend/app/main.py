"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .database import init_db
from .api.router import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    settings = get_settings()
    # Create data directories
    for dir_path in [settings.storage.output_dir, settings.storage.temp_dir, settings.storage.assets_dir,
                     Path(settings.storage.base_dir) / "db"]:
        Path(dir_path).mkdir(parents=True, exist_ok=True)
    # Initialize database tables
    await init_db()
    # Discover AI providers
    from .providers import discover_providers
    discover_providers()
    yield


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(api_router, prefix="/api/v1")

# Serve static files (images, audio, video)
data_dir = Path(settings.storage.base_dir)
if data_dir.exists():
    app.mount("/data", StaticFiles(directory=str(data_dir)), name="data")


@app.get("/health")
async def health_check():
    return {"status": "ok", "version": settings.app_version}
