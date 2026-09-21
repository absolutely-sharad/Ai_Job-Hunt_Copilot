"""Structure-aware chunking for resume and project documents."""

from __future__ import annotations

import re

_SECTION_PATTERN = re.compile(r"\n(?=[A-Z][A-Za-z /&-]{2,40}\n)|\n{2,}")


def split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split on paragraph/section boundaries, then pack to ~chunk_size characters.

    Resume content is short and highly structured, so respecting blank-line and
    heading boundaries keeps bullets intact and avoids splitting a project's
    tech stack away from its description.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    overlap = max(0, min(overlap, chunk_size // 2))

    blocks = [b.strip() for b in _SECTION_PATTERN.split(text.strip()) if b and b.strip()]
    if not blocks:
        return []

    chunks: list[str] = []
    current = ""
    for block in blocks:
        if len(block) > chunk_size:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_hard_split(block, chunk_size, overlap))
            continue
        candidate = f"{current}\n\n{block}".strip() if current else block
        if len(candidate) <= chunk_size:
            current = candidate
        else:
            chunks.append(current)
            current = _carry_overlap(current, overlap) + block if overlap else block
    if current:
        chunks.append(current)
    return [c.strip() for c in chunks if c.strip()]


def _hard_split(block: str, chunk_size: int, overlap: int) -> list[str]:
    """Fall back to a sliding window for blocks longer than one chunk."""
    step = max(1, chunk_size - overlap)
    return [block[i : i + chunk_size] for i in range(0, len(block), step)]


def _carry_overlap(text: str, overlap: int) -> str:
    tail = text[-overlap:]
    return tail[tail.find(" ") + 1 :] + "\n\n" if " " in tail else ""
