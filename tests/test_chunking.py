"""Chunking must preserve structure and respect size bounds."""

import pytest

from app.services.chunking import split_text


def test_splits_on_blank_lines():
    text = "Section one content here.\n\nSection two content here.\n\nSection three."
    chunks = split_text(text, chunk_size=40, overlap=5)
    assert len(chunks) >= 2
    assert all(chunk.strip() for chunk in chunks)


def test_packs_small_blocks_together():
    text = "Alpha line.\n\nBeta line.\n\nGamma line."
    chunks = split_text(text, chunk_size=500, overlap=50)
    assert len(chunks) == 1
    assert "Alpha" in chunks[0] and "Gamma" in chunks[0]


def test_hard_splits_oversized_block():
    text = "x" * 2500
    chunks = split_text(text, chunk_size=500, overlap=50)
    assert len(chunks) > 1
    assert all(len(chunk) <= 500 for chunk in chunks)


def test_empty_input_returns_empty_list():
    assert split_text("   \n\n  ", chunk_size=500, overlap=50) == []


def test_rejects_invalid_chunk_size():
    with pytest.raises(ValueError):
        split_text("content", chunk_size=0, overlap=0)
