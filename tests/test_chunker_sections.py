from pathlib import Path

import pytest

from paper_agent.text.chunker import chunk_text


def test_chunk_text_reads_fixture_and_preserves_sections():
    text = Path("tests/fixtures/sample_paper_text.txt").read_text(encoding="utf-8")
    chunks = chunk_text("arxiv:2401.00001", text, max_words=50)
    assert [chunk.section for chunk in chunks] == [
        "Abstract",
        "Method",
        "Limitations",
    ]
    assert all(chunk.page is None for chunk in chunks)


def test_chunk_text_preserves_section_across_multiple_chunks_and_stable_ids():
    kwargs = {
        "paper_id": "p1",
        "text": "Method\none two three four five",
        "max_words": 2,
    }
    first = chunk_text(**kwargs)
    second = chunk_text(**kwargs)
    assert [chunk.section for chunk in first] == ["Method", "Method", "Method"]
    assert [chunk.chunk_id for chunk in first] == [
        "p1:chunk:001",
        "p1:chunk:002",
        "p1:chunk:003",
    ]
    assert [chunk.chunk_id for chunk in first] == [chunk.chunk_id for chunk in second]


def test_chunk_text_returns_empty_for_blank_text():
    assert chunk_text("p1", "   ") == []


def test_chunk_text_rejects_non_positive_max_words():
    with pytest.raises(ValueError, match="max_words must be at least 1"):
        chunk_text("p1", "Abstract\nText", max_words=0)
