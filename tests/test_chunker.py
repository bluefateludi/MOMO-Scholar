import hashlib

import pytest

from paper_agent.fulltext.models import DocumentPage, PaperDocument
from paper_agent.schemas import Paper
from paper_agent.text.chunker import chunk_document
from paper_agent.text.loader import load_paper_text


def _paper() -> Paper:
    return Paper(
        paper_id="arxiv:2401.00001",
        title="Example",
        authors=[],
        year=2024,
        abstract="Evidence-grounded paper agents cite source text.",
        url="https://arxiv.org/abs/2401.00001",
        source="arxiv",
    )


def test_load_paper_text_uses_abstract_in_no_pdf_mode():
    assert load_paper_text(_paper(), no_pdf=True) == (
        "Abstract\nEvidence-grounded paper agents cite source text."
    )


def test_load_paper_text_falls_back_when_primary_loader_fails():
    def failing_loader(paper: Paper) -> str:
        raise OSError("PDF unavailable")

    assert load_paper_text(_paper(), primary_loader=failing_loader) == (
        "Abstract\nEvidence-grounded paper agents cite source text."
    )


def _document(*pages: str) -> PaperDocument:
    normalized = "\n".join(pages).encode("utf-8")
    return PaperDocument(
        paper_id="arxiv:2401.00001",
        content_source="pdf",
        pages=[
            DocumentPage(page_number=index, text=text)
            for index, text in enumerate(pages, start=1)
        ],
        content_sha256=hashlib.sha256(normalized).hexdigest(),
    )


def test_chunk_document_uses_v1_window_defaults_and_exact_overlap():
    words = [f"word{index}" for index in range(181)]
    outcome = chunk_document(_document("Methods\n" + " ".join(words)))

    assert [chunk.token_count for chunk in outcome.chunks] == [180, 31]
    assert outcome.chunks[0].text.split()[-30:] == outcome.chunks[1].text.split()[:30]


@pytest.mark.parametrize(
    ("max_words", "overlap_words", "message"),
    [
        (0, 0, "max_words must be at least 1"),
        (10, 0, "overlap_words must be at least 1"),
        (10, 10, "overlap_words must be less than max_words"),
    ],
)
def test_chunk_document_validates_window_settings(max_words, overlap_words, message):
    with pytest.raises(ValueError, match=message):
        chunk_document(
            _document("Abstract\ntext"),
            max_words=max_words,
            overlap_words=overlap_words,
        )


def test_chunk_document_cross_page_window_uses_starting_page():
    outcome = chunk_document(
        _document("Methods\npage one words", "continue on page two"),
        max_words=20,
        overlap_words=2,
    )

    assert len(outcome.chunks) == 1
    assert outcome.chunks[0].page == 1
    assert "page two" in outcome.chunks[0].text


def test_chunk_document_without_heading_falls_back_with_warning():
    outcome = chunk_document(
        _document("plain page one", "plain page two"),
        max_words=4,
        overlap_words=1,
    )

    assert outcome.warnings == ("section_detection_failed",)
    assert [chunk.page for chunk in outcome.chunks] == [1, 2]
    assert all(chunk.section is None for chunk in outcome.chunks)
