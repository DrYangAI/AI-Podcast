"""Text splitting utilities for content segmentation."""


def split_by_paragraph(content: str, min_length: int = 10) -> list[str]:
    """Split content into paragraphs, filtering very short ones."""
    lines = content.split("\n")
    paragraphs = []
    current = []

    for line in lines:
        stripped = line.strip()
        if stripped:
            current.append(stripped)
        elif current:
            paragraphs.append("\n".join(current))
            current = []

    if current:
        paragraphs.append("\n".join(current))

    return [p for p in paragraphs if len(p) >= min_length]


def split_by_sentence(content: str) -> list[str]:
    """Split content into sentences (Chinese-aware)."""
    import re
    sentences = re.split(r'(?<=[。！？.!?])\s*', content)
    return [s.strip() for s in sentences if s.strip()]
