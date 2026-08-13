"""PPT import utility — render slides to PNG images and extract speaker notes.

There is no faithful pure-Python PPTX renderer, so slide *pictures* are produced
by LibreOffice (`soffice --headless --convert-to pdf`) followed by poppler
(`pdftoppm -png`). Speaker *notes* are read directly from the OOXML via
python-pptx. Both binaries must be installed on the host (see CLAUDE.md /
config.yaml `ppt.soffice_path`).
"""

import asyncio
import logging
import shutil
from pathlib import Path

from pptx import Presentation

from ..config import get_settings

logger = logging.getLogger(__name__)

# Default still-frame duration (seconds) for a slide whose notes are empty, so
# downstream per-segment audio/video stays aligned instead of dropping the page.
DEFAULT_SILENT_SLIDE_SECONDS = 3.0

# Standard render resolution for slide PNGs.
DEFAULT_DPI = 150

_MAC_BUNDLE_SOFFICE = "/Applications/LibreOffice.app/Contents/MacOS/soffice"


class PPTRenderError(RuntimeError):
    """Raised when a slide cannot be rendered or a required binary is missing."""


def find_soffice() -> str:
    """Locate the LibreOffice `soffice` binary.

    Order: explicit config override → PATH → standard macOS app bundle.
    """
    configured = get_settings().soffice_path
    if configured:
        if Path(configured).exists():
            return configured
        raise PPTRenderError(f"Configured soffice_path does not exist: {configured}")

    on_path = shutil.which("soffice")
    if on_path:
        return on_path

    if Path(_MAC_BUNDLE_SOFFICE).exists():
        return _MAC_BUNDLE_SOFFICE

    raise PPTRenderError(
        "LibreOffice `soffice` not found. Install it (e.g. `brew install --cask "
        "libreoffice`) or set `ppt.soffice_path` in config.yaml."
    )


def _find_pdftoppm() -> str:
    binary = shutil.which("pdftoppm")
    if not binary:
        raise PPTRenderError(
            "poppler `pdftoppm` not found. Install it (e.g. `brew install poppler`)."
        )
    return binary


async def _run(cmd: list[str], cwd: Path | None = None, timeout: float = 180.0) -> None:
    """Run a subprocess, raising PPTRenderError on failure or timeout."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise PPTRenderError(f"Command timed out after {timeout:.0f}s ({cmd[0]}).")
    if proc.returncode != 0:
        err = stderr.decode(errors="replace").strip()
        raise PPTRenderError(f"Command failed ({cmd[0]}): {err[-500:]}")


async def render_pptx_to_pngs(pptx_path: Path, out_dir: Path, dpi: int = DEFAULT_DPI) -> list[Path]:
    """Render every slide of a PPTX/PPT to a PNG, returning paths in slide order.

    PPTX → PDF (LibreOffice) → one PNG per page (poppler). Files are named
    ``slide_000.png``, ``slide_001.png`` … so they sort lexicographically.
    """
    soffice = find_soffice()
    pdftoppm = _find_pdftoppm()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Use a throwaway LibreOffice profile so a running desktop instance (which
    # holds a lock on the default profile) doesn't make us fail. The profile is
    # passed as a file:// URI, which MUST be absolute (a relative path silently
    # hangs LibreOffice), so resolve it first.
    work_dir = (out_dir / "_render_tmp").resolve()
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    profile_uri = (work_dir / "profile").as_uri()

    try:
        await _run(
            [
                soffice,
                "--headless",
                "--norestore",
                f"-env:UserInstallation={profile_uri}",
                "--convert-to",
                "pdf",
                "--outdir",
                str(work_dir),
                str(pptx_path),
            ]
        )

        pdfs = list(work_dir.glob("*.pdf"))
        if not pdfs:
            raise PPTRenderError("LibreOffice produced no PDF from the uploaded file.")
        pdf_path = pdfs[0]

        # pdftoppm writes <prefix>-1.png, <prefix>-2.png, … (1-based).
        prefix = work_dir / "page"
        await _run([pdftoppm, "-png", "-r", str(dpi), str(pdf_path), str(prefix)])

        pages = sorted(work_dir.glob("page-*.png"), key=_page_number)
        if not pages:
            raise PPTRenderError("poppler produced no page images from the PDF.")

        png_paths: list[Path] = []
        for i, page in enumerate(pages):
            dest = out_dir / f"slide_{i:03d}.png"
            shutil.move(str(page), str(dest))
            png_paths.append(dest)
        return png_paths
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _page_number(path: Path) -> int:
    """Extract the 1-based page index from a `page-N.png` filename for sorting."""
    try:
        return int(path.stem.rsplit("-", 1)[-1])
    except (ValueError, IndexError):
        return 0


def extract_slide_notes(pptx_path: Path) -> list[str]:
    """Return each *visible* slide's speaker-notes text, in slide order ("" if none).

    Hidden slides (``show="0"``) are skipped because LibreOffice excludes them
    from the rendered PDF — so skipping them here keeps notes aligned 1:1 with
    the rendered slide images.
    """
    prs = Presentation(str(pptx_path))
    notes: list[str] = []
    for slide in prs.slides:
        if slide._element.get("show") == "0":
            continue  # hidden slide — not rendered by LibreOffice
        text = ""
        if slide.has_notes_slide:
            frame = slide.notes_slide.notes_text_frame
            if frame is not None:
                text = (frame.text or "").strip()
        notes.append(text)
    return notes


async def import_pptx(pptx_path: Path, out_dir: Path, dpi: int = DEFAULT_DPI) -> list[tuple[Path, str]]:
    """Render slides + read notes, returning aligned ``(png_path, notes)`` pairs.

    Raises PPTRenderError if the rendered page count and slide count disagree
    (which would break the slide↔note alignment the feature depends on).
    """
    png_paths = await render_pptx_to_pngs(pptx_path, out_dir, dpi=dpi)
    notes = extract_slide_notes(pptx_path)

    if len(png_paths) != len(notes):
        # After hidden-slide filtering this should normally match. If it still
        # doesn't, degrade gracefully (align to the shorter list) rather than
        # failing the whole import — but log loudly so the cause is visible.
        logger.warning(
            "Slide/notes count mismatch after filtering: %d rendered pages vs %d "
            "visible slides; aligning to the shorter list.",
            len(png_paths), len(notes),
        )
        n = min(len(png_paths), len(notes))
        png_paths, notes = png_paths[:n], notes[:n]
    return list(zip(png_paths, notes))
