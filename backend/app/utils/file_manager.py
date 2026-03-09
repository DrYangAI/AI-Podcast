"""Output path and naming rules management."""

import re
from datetime import datetime
from pathlib import Path


class FileManager:
    """Manages output file paths and naming conventions."""

    def __init__(self, base_output_dir: str = "./data/output"):
        self.base_output_dir = Path(base_output_dir)

    def build_output_path(self, naming_rule: str, topic: str,
                          aspect_ratio: str, template: str,
                          project_id: str, fmt: str = "mp4") -> Path:
        """Build the output file path from naming rule template."""
        now = datetime.now()
        replacements = {
            "{date}": now.strftime("%Y%m%d"),
            "{timestamp}": now.strftime("%Y%m%d_%H%M%S"),
            "{topic}": self._sanitize(topic[:30]),
            "{aspect_ratio}": aspect_ratio.replace(":", "x"),
            "{template}": template,
            "{id}": project_id[:8],
        }
        filename = naming_rule
        for key, value in replacements.items():
            filename = filename.replace(key, value)

        self.base_output_dir.mkdir(parents=True, exist_ok=True)
        return self.base_output_dir / f"{filename}.{fmt}"

    @staticmethod
    def _sanitize(name: str) -> str:
        return re.sub(r'[<>:"/\\|?*\s]+', '_', name).strip('_')
