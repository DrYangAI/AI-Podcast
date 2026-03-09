"""FFmpeg command builder and executor."""

import asyncio
import re
from pathlib import Path


class FFmpegBuilder:
    """Builds and executes FFmpeg commands with progress tracking."""

    async def execute(self, args: list[str],
                      progress_callback=None) -> tuple[int, str, str]:
        """Execute FFmpeg command asynchronously."""
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stderr_lines = []
        while True:
            line = await process.stderr.readline()
            if not line:
                break
            decoded = line.decode("utf-8", errors="replace")
            stderr_lines.append(decoded)

            if progress_callback and "time=" in decoded:
                time_val = self._parse_time(decoded)
                if time_val is not None:
                    await progress_callback(time_val)

        await process.wait()
        stdout = (await process.stdout.read()).decode()
        return process.returncode, stdout, "".join(stderr_lines)

    @staticmethod
    def _parse_time(line: str) -> float | None:
        match = re.search(r"time=(\d{2}):(\d{2}):(\d{2})\.(\d{2})", line)
        if match:
            h, m, s, cs = match.groups()
            return int(h) * 3600 + int(m) * 60 + int(s) + int(cs) / 100
        return None

    @staticmethod
    async def get_duration(file_path: Path) -> float:
        """Get media file duration using ffprobe."""
        process = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "csv=p=0", str(file_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await process.communicate()
        try:
            return float(stdout.decode().strip())
        except (ValueError, AttributeError):
            return 0.0
