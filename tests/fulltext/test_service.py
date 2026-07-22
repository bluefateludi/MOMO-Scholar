from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from paper_agent.fulltext import (
    AcquisitionOutcome,
    DocumentAcquirer,
    DocumentPage,
    DocumentRecord,
    DownloadedPdf,
    PaperDocument,
    PdfDownloadError,
    PdfParseError,
)
from paper_agent.schemas import Paper


DOWNLOAD_ERROR_CODES = [
    "pdf_url_missing",
    "pdf_download_timeout",
    "pdf_not_found",
    "pdf_http_error",
    "pdf_redirect_rejected",
    "pdf_too_large",
    "pdf_content_invalid",
]
PARSE_ERROR_CODES = [
    "pdf_corrupt",
    "pdf_encrypted",
    "pdf_too_many_pages",
    "pdf_text_empty",
]


def _paper(*, abstract: str = "A useful abstract.") -> Paper:
    return Paper(
        paper_id="arxiv:2401.00001",
        title="Test paper",
        abstract=abstract,
        url="https://arxiv.org/abs/2401.00001",
        pdf_url="https://arxiv.org/pdf/2401.00001",
        source="arxiv",
    )


class FakeDownloader:
    def __init__(self, result: DownloadedPdf | Exception) -> None:
        self.result = result
        self.calls: list[Paper] = []

    def download(self, paper: Paper) -> DownloadedPdf:
        self.calls.append(paper)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeParser:
    def __init__(self, result: PaperDocument | Exception) -> None:
        self.result = result
        self.calls: list[tuple[str, bytes]] = []

    def parse(self, *, paper_id: str, pdf_bytes: bytes) -> PaperDocument:
        self.calls.append((paper_id, pdf_bytes))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _pdf_document() -> PaperDocument:
    return PaperDocument(
        paper_id="arxiv:2401.00001",
        content_source="pdf",
        pages=[DocumentPage(page_number=1, text="PDF body")],
        content_sha256=hashlib.sha256(b"%PDF-test").hexdigest(),
    )


def _acquirer(
    *,
    download: DownloadedPdf | Exception | None = None,
    parse: PaperDocument | Exception | None = None,
) -> tuple[DocumentAcquirer, FakeDownloader, FakeParser]:
    downloader = FakeDownloader(
        download
        if download is not None
        else DownloadedPdf(
            content=b"%PDF-test",
            source_url="https://arxiv.org/pdf/2401.00001",
            content_type="application/pdf",
        )
    )
    parser = FakeParser(parse if parse is not None else _pdf_document())
    return DocumentAcquirer(downloader=downloader, parser=parser), downloader, parser


def test_explicit_no_pdf_normalizes_and_hashes_the_stored_abstract() -> None:
    acquirer, downloader, parser = _acquirer()

    outcome = acquirer.acquire(
        _paper(abstract="  A  normalized\r\n abstract.  \n\n  With detail.  "),
        no_pdf=True,
    )

    expected = "Abstract\nA normalized\nabstract.\n\nWith detail."
    assert outcome.document is not None
    assert outcome.record is not None
    assert outcome.document.content_source == "abstract"
    assert outcome.document.pages == [DocumentPage(page_number=1, text=expected)]
    assert outcome.document.content_sha256 == hashlib.sha256(expected.encode("utf-8")).hexdigest()
    assert outcome.record == DocumentRecord.from_document(outcome.document)
    assert outcome.record.fallback_code is None
    assert outcome.degradations == []
    assert outcome.excluded_code is None
    assert downloader.calls == []
    assert parser.calls == []


def test_pdf_success_records_pdf_without_fallback_or_degradation() -> None:
    acquirer, downloader, parser = _acquirer()

    outcome = acquirer.acquire(_paper(), no_pdf=False)

    assert outcome.document == _pdf_document()
    assert outcome.record == DocumentRecord.from_document(_pdf_document())
    assert outcome.record is not None
    assert outcome.record.content_source == "pdf"
    assert outcome.record.fallback_code is None
    assert outcome.degradations == []
    assert outcome.excluded_code is None
    assert downloader.calls == [_paper()]
    assert parser.calls == [("arxiv:2401.00001", b"%PDF-test")]


@pytest.mark.parametrize("abstract", ["", " ", "\r\n\t"])
def test_empty_abstract_in_explicit_mode_is_an_excluded_degradation(abstract: str) -> None:
    acquirer, downloader, parser = _acquirer()

    outcome = acquirer.acquire(_paper(abstract=abstract), no_pdf=True)

    assert outcome.document is None
    assert outcome.record is None
    assert outcome.excluded_code == "abstract_text_empty"
    assert [issue.model_dump() for issue in outcome.degradations] == [
        {
            "stage": "acquisition",
            "code": "abstract_text_empty",
            "paper_id": "arxiv:2401.00001",
            "message": "paper abstract contains no usable text",
        }
    ]
    assert downloader.calls == []
    assert parser.calls == []


@pytest.mark.parametrize("code", DOWNLOAD_ERROR_CODES)
def test_typed_download_failure_falls_back_to_abstract(code: str) -> None:
    acquirer, _, parser = _acquirer(download=PdfDownloadError(code, "safe failure"))

    outcome = acquirer.acquire(_paper(), no_pdf=False)

    assert outcome.document is not None
    assert outcome.record is not None
    assert outcome.document.content_source == "abstract"
    assert outcome.record.fallback_code == code
    assert outcome.excluded_code is None
    assert [issue.model_dump() for issue in outcome.degradations] == [
        {
            "stage": "acquisition",
            "code": code,
            "paper_id": "arxiv:2401.00001",
            "message": "safe failure",
        }
    ]
    assert parser.calls == []


@pytest.mark.parametrize("code", PARSE_ERROR_CODES)
def test_typed_parse_failure_falls_back_to_abstract(code: str) -> None:
    acquirer, _, _ = _acquirer(parse=PdfParseError(code, "safe failure"))

    outcome = acquirer.acquire(_paper(), no_pdf=False)

    assert outcome.document is not None
    assert outcome.record is not None
    assert outcome.document.content_source == "abstract"
    assert outcome.record.fallback_code == code
    assert outcome.excluded_code is None
    assert outcome.degradations[0].code == code
    assert outcome.degradations[0].message == "safe failure"


@pytest.mark.parametrize(
    "failure",
    [
        *[PdfDownloadError(code, "safe failure") for code in DOWNLOAD_ERROR_CODES],
        *[PdfParseError(code, "safe failure") for code in PARSE_ERROR_CODES],
    ],
)
def test_typed_pdf_failure_without_abstract_excludes_the_paper(failure: Exception) -> None:
    if isinstance(failure, PdfDownloadError):
        acquirer, _, _ = _acquirer(download=failure)
    else:
        acquirer, _, _ = _acquirer(parse=failure)

    outcome = acquirer.acquire(_paper(abstract=" \n\t"), no_pdf=False)

    assert outcome.document is None
    assert outcome.record is None
    assert outcome.excluded_code == failure.code
    assert outcome.degradations[0].code == failure.code
    assert outcome.degradations[0].paper_id == "arxiv:2401.00001"


@pytest.mark.parametrize("boundary", ["downloader", "parser"])
def test_unexpected_programming_errors_propagate(boundary: str) -> None:
    if boundary == "downloader":
        acquirer, _, _ = _acquirer(download=RuntimeError("programming error"))
    else:
        acquirer, _, _ = _acquirer(parse=RuntimeError("programming error"))

    with pytest.raises(RuntimeError, match="programming error"):
        acquirer.acquire(_paper(), no_pdf=False)


def test_acquisition_outcome_requires_document_and_record_together() -> None:
    with pytest.raises(ValidationError):
        AcquisitionOutcome(document=_pdf_document(), record=None)


def test_acquisition_outcome_forbids_exclusion_for_a_document() -> None:
    document = _pdf_document()
    with pytest.raises(ValidationError):
        AcquisitionOutcome(
            document=document,
            record=DocumentRecord.from_document(document),
            excluded_code="pdf_corrupt",
        )


def test_acquisition_outcome_requires_exclusion_without_a_document() -> None:
    with pytest.raises(ValidationError):
        AcquisitionOutcome(document=None, record=None)
