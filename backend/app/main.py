"""FastAPI application entry point."""

import importlib.util
import logging
import os
import platform
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response

# Configure logging so all app loggers output to console
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
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
    # Seed default prompt templates
    from .services.prompt_template_service import PromptTemplateService
    from .database import async_session_factory
    async with async_session_factory() as db:
        await PromptTemplateService.seed_defaults(db)
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

# 主系统只需探测本机是否满足运行条件。仅给这个不含业务数据的端点开放跨域，
# 绝不把 /api/v1/projects、素材或模型密钥暴露给远端主站脚本。
_CAPABILITY_PROBE_ORIGINS = {
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "http://localhost:5186",
    "http://127.0.0.1:5186",
    "https://app.banxiaoshi.top",
}


@app.middleware("http")
async def capability_probe_cors(request: Request, call_next):
    origin = request.headers.get("origin", "")
    is_probe = request.url.path == "/health/capabilities"
    if is_probe and request.method == "OPTIONS" and origin in _CAPABILITY_PROBE_ORIGINS:
        return Response(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Methods": "GET, OPTIONS",
                "Access-Control-Allow-Headers": "Accept, Content-Type",
                "Vary": "Origin",
            },
        )
    response = await call_next(request)
    if is_probe and origin in _CAPABILITY_PROBE_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
    return response

# API routes
app.include_router(api_router, prefix="/api/v1")

# Serve static files (images, audio, video)
data_dir = Path(settings.storage.base_dir)
if data_dir.exists():
    app.mount("/data", StaticFiles(directory=str(data_dir)), name="data")


@app.get("/health")
async def health_check():
    return {"status": "ok", "version": settings.app_version}


def _total_memory_gb() -> float | None:
    """Best-effort physical memory detection without adding a dependency."""
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        page_count = os.sysconf("SC_PHYS_PAGES")
        return round((page_size * page_count) / (1024 ** 3), 1)
    except (AttributeError, OSError, ValueError):
        return None


@app.get("/health/capabilities")
async def capability_check():
    """Report whether this local workstation meets the companion requirements."""
    data_dir = Path(settings.storage.base_dir).resolve()
    memory_gb = _total_memory_gb()
    disk_free_gb = round(shutil.disk_usage(data_dir).free / (1024 ** 3), 1)
    cpu_cores = os.cpu_count() or 0
    ffmpeg_path = shutil.which("ffmpeg")
    asr_available = importlib.util.find_spec("faster_whisper") is not None
    configured_soffice = Path(settings.soffice_path) if settings.soffice_path else None
    bundled_soffice = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
    soffice_path = (
        str(configured_soffice)
        if configured_soffice and configured_soffice.exists()
        else shutil.which("soffice")
        or (str(bundled_soffice) if bundled_soffice.exists() else None)
    )
    pdftoppm_path = shutil.which("pdftoppm")

    checks = [
        {
            "key": "memory",
            "label": "内存",
            "ok": memory_gb is not None and memory_gb >= 16,
            "required": True,
            "actual": f"{memory_gb} GB" if memory_gb is not None else "无法检测",
            "message": (
                f"当前 {memory_gb} GB，最低 16 GB"
                if memory_gb is not None
                else "无法读取内存信息"
            ),
        },
        {
            "key": "disk",
            "label": "可用磁盘",
            "ok": disk_free_gb >= 20,
            "required": True,
            "actual": f"{disk_free_gb} GB",
            "message": f"当前可用 {disk_free_gb} GB，最低 20 GB",
        },
        {
            "key": "cpu",
            "label": "处理器",
            "ok": cpu_cores >= 4,
            "required": True,
            "actual": f"{cpu_cores} 核 / {platform.machine()}",
            "message": f"检测到 {cpu_cores} 核 {platform.machine()}，最低 4 核",
        },
        {
            "key": "ffmpeg",
            "label": "FFmpeg 视频组件",
            "ok": bool(ffmpeg_path),
            "required": True,
            "actual": ffmpeg_path or "未安装",
            "message": ffmpeg_path or "未找到 ffmpeg，无法合成视频",
        },
        {
            "key": "asr",
            "label": "语音识别组件",
            "ok": asr_available,
            "required": True,
            "actual": "已安装" if asr_available else "未安装",
            "message": "faster-whisper 已就绪" if asr_available else "未找到 faster-whisper",
        },
        {
            "key": "libreoffice",
            "label": "PPT 导入组件",
            "ok": bool(soffice_path and pdftoppm_path),
            "required": False,
            "actual": "已安装" if soffice_path and pdftoppm_path else "未完整安装",
            "message": (
                "LibreOffice 与 Poppler 已就绪"
                if soffice_path and pdftoppm_path
                else "仅导入 PPT 时需要 LibreOffice 与 Poppler，可稍后安装"
            ),
        },
    ]
    return {
        "status": "ok",
        "version": settings.app_version,
        "ready": all(item["ok"] for item in checks if item["required"]),
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "checks": checks,
    }
