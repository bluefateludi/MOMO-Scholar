import pytest
from pydantic import ValidationError

from paper_agent.fulltext.models import DocumentPage, DocumentRecord, PaperDocument


def _document(**updates: object) -> PaperDocument:
    values: dict[str, object] = {
        "paper_id": "arxiv:2401.00001",
        "content_source": "pdf",
        "pages": [DocumentPage(page_number=1, text="Introduction\nBody")],
        "content_sha256": "a" * 64,
    }
    values.update(updates)
    return PaperDocument(**values)


def test_document_record_omits_page_text() -> None:
    record = DocumentRecord.from_document(_document())

    assert record.page_count == 1
    assert "pages" not in record.model_dump()


def test_document_record_copies_metadata_and_fallback_code() -> None:
    document = _document(warnings=["blank_page:2"])

    record = DocumentRecord.from_document(document, fallback_code="pdf_text_empty")

    assert record.warnings == ["blank_page:2"]
    assert record.warnings is not document.warnings
    assert record.fallback_code == "pdf_text_empty"


@pytest.mark.parametrize("page_number", [0, -1])
def test_document_page_number_is_positive_and_one_based(page_number: int) -> None:
    with pytest.raises(ValidationError):
        DocumentPage(page_number=page_number, text="Body")


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_document_page_rejects_blank_text(text: str) -> None:
    with pytest.raises(ValidationError):
        DocumentPage(page_number=1, text=text)


@pytest.mark.parametrize(
    "digest",
    ["a" * 63, "a" * 65, "A" * 64, "g" * 64],
)
def test_document_hash_requires_lowercase_sha256(digest: str) -> None:
    with pytest.raises(ValidationError):
        _document(content_sha256=digest)


def test_document_requires_at_least_one_page() -> None:
    with pytest.raises(ValidationError):
        _document(pages=[])


def test_document_warning_defaults_are_isolated() -> None:
    first = _document()
    second = _document()

    first.warnings.append("first-only")

    assert second.warnings == []


def test_fulltext_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        DocumentPage(page_number=1, text="Body", unexpected=True)
