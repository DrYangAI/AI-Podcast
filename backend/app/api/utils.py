"""Utility API routes."""

import platform
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import get_settings

router = APIRouter()


class OpenFolderRequest(BaseModel):
    file_path: str  # Relative path like "data/images/xxx/img.png"


@router.post("/open-folder")
async def open_folder(req: OpenFolderRequest):
    """Open the folder containing a file in the system file manager."""
    settings = get_settings()
    base_dir = Path(settings.storage.base_dir).resolve().parent  # project root
    target = base_dir / req.file_path

    # Resolve to directory: if it's a file, use parent
    folder = target if target.is_dir() else target.parent

    if not folder.exists():
        raise HTTPException(status_code=404, detail=f"Directory not found: {folder}")

    # Security: ensure path is within the data directory
    data_root = Path(settings.storage.base_dir).resolve()
    try:
        folder.resolve().relative_to(data_root)
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied: path outside data directory")

    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.Popen(["open", str(folder)])
        elif system == "Windows":
            subprocess.Popen(["explorer", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to open folder: {e}")

    return {"message": "Folder opened", "path": str(folder)}
