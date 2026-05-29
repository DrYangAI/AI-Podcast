"""PDF content extraction utility - extracts text from PDF files."""

import logging
from dataclasses import dataclass
from io import BytesIO

import pdfplumber

logger = logging.getLogger(__name__)


@dataclass
class ExtractedPDF:
    title: str
    content: str


def extract_pdf(file_bytes: bytes) -> ExtractedPDF:
    """Extract title and text content from a PDF file.

    Args:
        file_bytes: Raw bytes of the PDF file.

    Returns:
        ExtractedPDF with title and concatenated text content.
    """
    pages_text: list[str] = []

    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        # Try to get title from PDF metadata
        metadata = pdf.metadata or {}
        title = (metadata.get("Title") or "").strip()

        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages_text.append(text.strip())

    content = "\n\n".join(pages_text)

    # Fallback: use first non-empty line as title
    if not title and content:
        for line in content.split("\n"):
            line = line.strip()
            if len(line) > 2:
                title = line[:200]  # cap title length
                break

    if not content:
        raise ValueError("无法从 PDF 中提取文本内容，可能是扫描件或图片格式的 PDF")

    return ExtractedPDF(title=title, content=content)
