"""Text splitting utilities for content segmentation."""

import re


def split_text_for_tts(text: str, max_chars: int = 500) -> list[str]:
    """Split text into chunks suitable for TTS synthesis.

    Splits at natural boundaries to keep each chunk under max_chars:
    1. Paragraph breaks (\\n\\n)
    2. Sentence endings (。！？.!?)
    3. Clause boundaries (，、；：,;:)
    4. Hard cut at max_chars (last resort)

    Adjacent small chunks are merged when their combined length fits.
    """
    if not text or not text.strip():
        return []

    text = text.strip()
    if len(text) <= max_chars:
        return [text]

    # Step 1: Split into paragraphs
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]

    # Step 2: Break oversized paragraphs into sentences
    raw_chunks: list[str] = []
    for para in paragraphs:
        if len(para) <= max_chars:
            raw_chunks.append(para)
        else:
            # Split at sentence boundaries
            sentences = re.split(r'(?<=[。！？.!?])', para)
            for sent in sentences:
                sent = sent.strip()
                if not sent:
                    continue
                if len(sent) <= max_chars:
                    raw_chunks.append(sent)
                else:
                    # Split at clause boundaries
                    clauses = re.split(r'(?<=[，、；：,;:])', sent)
                    for clause in clauses:
                        clause = clause.strip()
                        if not clause:
                            continue
                        if len(clause) <= max_chars:
                            raw_chunks.append(clause)
                        else:
                            # Hard split
                            for i in range(0, len(clause), max_chars):
                                piece = clause[i:i + max_chars]
                                if piece.strip():
                                    raw_chunks.append(piece)

    # Step 3: Merge adjacent small chunks to reduce fragment count
    merged: list[str] = []
    current = ""
    for chunk in raw_chunks:
        # Use \n to join paragraphs, space-free for within-paragraph merges
        separator = "\n" if current and chunk and (current.endswith(("。", "！", "？", ".", "!", "?")) or chunk[0].isupper()) else ""
        if not current:
            current = chunk
        elif len(current) + len(separator) + len(chunk) <= max_chars:
            current = current + separator + chunk
        else:
            merged.append(current)
            current = chunk
    if current:
        merged.append(current)

    return merged


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
    sentences = re.split(r'(?<=[。！？.!?])\s*', content)
    return [s.strip() for s in sentences if s.strip()]
