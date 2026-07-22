from __future__ import annotations

import hashlib

import pymupdf
import pytest

from paper_agent.fulltext.models import DocumentRecord
from paper_agent.fulltext.parser import PdfParseError, PdfParser


def _pdf_bytes(pages: list[str | None]) -> bytes:
    document = pymupdf.open()
    try:
        for text in pages:
            page = document.new_page()
            if text is not None:
                page.insert_textbox(page.rect + (36, 36, -36, -36), text, fontsize=10)
        return document.tobytes()
    finally:
        document.close()


def _encrypted_pdf_bytes() -> bytes:
    document = pymupdf.open()
    try:
        page = document.new_page()
        page.insert_text((72, 72), "Protected content")
        return document.tobytes(
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            owner_pw="owner-secret",
            user_pw="user-secret",
        )
    finally:
        document.close()


def _useful_text(label: str = "Useful") -> str:
    return f"{label} grounded retrieval evidence and reproducible analysis. " * 8


def test_parser_preserves_page_order_and_hash() -> None:
    pdf_bytes = _pdf_bytes(
        [
            "Abstract\n" + _useful_text("This paper studies"),
            "1 Introduction\n" + _useful_text("The method uses"),
        ]
    )

    document = PdfParser(max_pages=200).parse(
        paper_id="arxiv:2401.00001",
        pdf_bytes=pdf_bytes,
    )

    assert [page.page_number for page in document.pages] == [1, 2]
    assert document.content_source == "pdf"
    assert document.content_sha256 == hashlib.sha256(pdf_bytes).hexdigest()
    assert document.pages[0].text.startswith("Abstract\n")
    assert document.pages[1].text.startswith("1 Introduction\n")


def test_parser_normalizes_line_endings_whitespace_controls_and_blank_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Page:
        def get_text(self) -> str:
            return "Heading\r\nalpha\t beta\x00\x07\n \n\nbody   text " + _useful_text()

    class Document:
        needs_pass = False
        page_count = 1

        def __enter__(self) -> Document:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def load_page(self, page_number: int) -> Page:
            assert page_number == 0
            return Page()

    monkeypatch.setattr(pymupdf, "open", lambda **kwargs: Document())

    document = PdfParser(max_pages=1).parse(paper_id="paper", pdf_bytes=b"raw")

    assert "\r" not in document.pages[0].text
    assert "\x00" not in document.pages[0].text
    assert "\x07" not in document.pages[0].text
    assert "alpha beta" in document.pages[0].text
    assert "body text" in document.pages[0].text
    assert "\n\n\n" not in document.pages[0].text


def test_blank_page_is_omitted_with_original_page_warning_and_record_count() -> None:
    pdf_bytes = _pdf_bytes([_useful_text("First"), None, _useful_text("Third")])

    document = PdfParser(max_pages=3).parse(paper_id="paper", pdf_bytes=pdf_bytes)

    assert [page.page_number for page in document.pages] == [1, 3]
    assert document.warnings == ["page_text_empty:2"]
    assert DocumentRecord.from_document(document).page_count == 2


def test_repeated_page_edge_lines_on_more_than_half_the_pages_are_removed() -> None:
    pdf_bytes = _pdf_bytes(
        [
            f"Shared Header\n{_useful_text(f'Page {number}')}\nShared Footer"
            for number in range(1, 4)
        ]
    )

    document = PdfParser(max_pages=3).parse(paper_id="paper", pdf_bytes=pdf_bytes)

    assert all("Shared Header" not in page.text for page in document.pages)
    assert all("Shared Footer" not in page.text for page in document.pages)


def test_page_edge_line_on_exactly_half_the_pages_is_retained() -> None:
    pdf_bytes = _pdf_bytes(
        [
            f"Half Header\n{_useful_text('First')}",
            f"Half Header\n{_useful_text('Second')}",
            _useful_text("Third"),
            _useful_text("Fourth"),
        ]
    )

    document = PdfParser(max_pages=4).parse(paper_id="paper", pdf_bytes=pdf_bytes)

    assert document.pages[0].text.startswith("Half Header\n")
    assert document.pages[1].text.startswith("Half Header\n")


@pytest.mark.parametrize("pdf_bytes", [b"not a pdf", b"%PDF-1.7\ntruncated"])
def test_corrupt_or_truncated_pdf_uses_exact_error_code(pdf_bytes: bytes) -> None:
    with pytest.raises(PdfParseError, match="pdf_corrupt") as caught:
        PdfParser(max_pages=200).parse(paper_id="paper", pdf_bytes=pdf_bytes)

    assert caught.value.code == "pdf_corrupt"
    assert "MuPDF" not in caught.value.message


@pytest.mark.parametrize("failure_point", ["load_page", "get_text"])
def test_page_data_errors_are_mapped_without_leaking_library_error(
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    class Page:
        def get_text(self) -> str:
            if failure_point == "get_text":
                raise pymupdf.FileDataError("sensitive library detail")
            return _useful_text()

    class Document:
        needs_pass = False
        page_count = 1

        def __enter__(self) -> Document:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def load_page(self, page_number: int) -> Page:
            if failure_point == "load_page":
                raise pymupdf.FileDataError("sensitive library detail")
            return Page()

    monkeypatch.setattr(pymupdf, "open", lambda **kwargs: Document())

    with pytest.raises(PdfParseError) as caught:
        PdfParser(max_pages=1).parse(paper_id="paper", pdf_bytes=b"raw")

    assert caught.value.code == "pdf_corrupt"
    assert "sensitive library detail" not in caught.value.message


def test_unknown_extraction_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    class Document:
        needs_pass = False
        page_count = 1

        def __enter__(self) -> Document:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def load_page(self, page_number: int) -> object:
            raise ValueError("unexpected")

    monkeypatch.setattr(pymupdf, "open", lambda **kwargs: Document())

    with pytest.raises(ValueError, match="unexpected"):
        PdfParser(max_pages=1).parse(paper_id="paper", pdf_bytes=b"raw")


def test_encrypted_pdf_uses_exact_error_code() -> None:
    with pytest.raises(PdfParseError, match="pdf_encrypted") as caught:
        PdfParser(max_pages=1).parse(
            paper_id="paper",
            pdf_bytes=_encrypted_pdf_bytes(),
        )

    assert caught.value.code == "pdf_encrypted"


def test_exact_page_limit_succeeds_and_one_over_fails() -> None:
    exact = _pdf_bytes([_useful_text("First"), _useful_text("Second")])
    over = _pdf_bytes(
        [_useful_text("First"), _useful_text("Second"), _useful_text("Third")]
    )

    assert len(PdfParser(max_pages=2).parse(paper_id="paper", pdf_bytes=exact).pages) == 2
    with pytest.raises(PdfParseError, match="pdf_too_many_pages") as caught:
        PdfParser(max_pages=2).parse(paper_id="paper", pdf_bytes=over)
    assert caught.value.code == "pdf_too_many_pages"


@pytest.mark.parametrize(
    "text",
    [None, "x" * 199, "x " * 199],
)
def test_document_with_fewer_than_200_non_whitespace_characters_is_rejected(
    text: str | None,
) -> None:
    with pytest.raises(PdfParseError, match="pdf_text_empty") as caught:
        PdfParser(max_pages=1).parse(
            paper_id="paper",
            pdf_bytes=_pdf_bytes([text]),
        )

    assert caught.value.code == "pdf_text_empty"


def test_exactly_200_non_whitespace_characters_is_useful() -> None:
    document = PdfParser(max_pages=1).parse(
        paper_id="paper",
        pdf_bytes=_pdf_bytes(["x" * 200]),
    )

    assert len(document.pages[0].text.replace(" ", "").replace("\n", "")) == 200
