"""AI provider plugin system with auto-discovery."""

import importlib
import pkgutil
from pathlib import Path


def discover_providers():
    """Import all provider modules to trigger @register decorators."""
    package_dir = Path(__file__).parent
    for subdir in ["text", "image", "tts", "video"]:
        subpackage_dir = package_dir / subdir
        if not subpackage_dir.exists():
            continue
        for _, module_name, _ in pkgutil.iter_modules([str(subpackage_dir)]):
            if module_name == "base" or module_name.startswith("_"):
                continue
            importlib.import_module(f".{subdir}.{module_name}", package=__name__)
