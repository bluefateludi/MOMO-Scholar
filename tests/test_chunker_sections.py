import hashlib
from pathlib import Path

import pytest

from paper_agent.fulltext.models import DocumentPage, PaperDocument
from paper_agent.text.chunker import chunk_document, chunk_text


def _document(*pages: str) -> PaperDocument:
    normalized = "\n".join(pages).encode("utf-8")
    return PaperDocument(
        paper_id="p1",
        content_source="pdf",
        pages=[
            DocumentPage(page_number=index, text=text)
            for index, text in enumerate(pages, start=1)
        ],
        content_sha256=hashlib.sha256(normalized).hexdigest(),
    )


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


def test_chunk_document_recognizes_canonical_and_numbered_headings():
    outcome = chunk_document(
        _document(
            "Abstract\nsummary words\n1. Introduction\nintro words",
            "continued introduction\n2.1 Proposed Method\nmethod words",
        ),
        max_words=20,
        overlap_words=2,
    )

    assert [chunk.section for chunk in outcome.chunks] == [
        "Abstract",
        "Introduction",
        "Proposed Method",
    ]
    assert [chunk.page for chunk in outcome.chunks] == [1, 1, 2]
    assert outcome.chunks[1].text == "intro words continued introduction"
    assert [chunk.chunk_id for chunk in outcome.chunks] == [
        "p1:chunk:001",
        "p1:chunk:002",
        "p1:chunk:003",
    ]


def test_chunk_document_never_crosses_recognized_section_boundary():
    outcome = chunk_document(
        _document("Methods\none two three four\nResults\nfive six seven eight"),
        max_words=6,
        overlap_words=2,
    )

    assert [chunk.section for chunk in outcome.chunks] == ["Methods", "Results"]
    assert [chunk.text for chunk in outcome.chunks] == [
        "one two three four",
        "five six seven eight",
    ]


def test_chunk_document_excludes_reference_section():
    outcome = chunk_document(
        _document("Introduction\nbody text\nReferences\n[1] cited work"),
        max_words=20,
        overlap_words=2,
    )

    assert [chunk.text for chunk in outcome.chunks] == ["body text"]
    assert outcome.warnings == ("reference_section_excluded",)


def test_references_in_body_prose_is_not_a_heading():
    outcome = chunk_document(
        _document("Introduction\nThe paper references prior work in this sentence."),
        max_words=20,
        overlap_words=2,
    )

    assert len(outcome.chunks) == 1
    assert outcome.chunks[0].section == "Introduction"
    assert "references prior work" in outcome.chunks[0].text
    assert outcome.warnings == ()


def test_chunk_document_is_deterministic_for_identical_input_and_settings():
    document = _document("Methods\n" + " ".join(f"w{i}" for i in range(12)))

    first = chunk_document(document, max_words=5, overlap_words=2)
    second = chunk_document(document, max_words=5, overlap_words=2)

    assert first == second
