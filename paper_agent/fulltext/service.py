from __future__ import annotations

import hashlib
import re
import unicodedata

from pydantic import Field, model_validator

from paper_agent.fulltext.downloader import FullTextDownloader, PdfDownloadError
from paper_agent.fulltext.models import DocumentPage, DocumentRecord, PaperDocument
from paper_agent.fulltext.parser import PdfParseError, PdfParser
from paper_agent.modeling import StrictModel
from paper_agent.observability.models import RunIssue
from paper_agent.schemas import Paper


class AcquisitionOutcome(StrictModel):
    document: PaperDocument | None
    record: DocumentRecord | None
    degradations: list[RunIssue] = Field(default_factory=list)
    excluded_code: str | None = None

    @model_validator(mode="after")
    def validate_result(self) -> AcquisitionOutcome:
        if (self.document is None) != (self.record is None):
            raise ValueError("document and record must be present together")
        if self.document is None and self.excluded_code is None:
            raise ValueError("excluded outcome requires an exclusion code")
        if self.document is not None and self.excluded_code is not None:
            raise ValueError("document outcome cannot have an exclusion code")
        return self


class DocumentAcquirer:
    def __init__(
        self,
        *,
        downloader: FullTextDownloader,
        parser: PdfParser,
    ) -> None:
        self._downloader = downloader
        self._parser = parser

    def acquire(self, paper: Paper, *, no_pdf: bool) -> AcquisitionOutcome:
        if no_pdf:
            return _abstract_outcome(paper)

        try:
            downloaded = self._downloader.download(paper)
            document = self._parser.parse(
                paper_id=paper.paper_id,
                pdf_bytes=downloaded.content,
            )
        except (PdfDownloadError, PdfParseError) as error:
            issue = _issue(paper, code=error.code, message=error.message)
            return _abstract_outcome(
                paper,
                fallback_code=error.code,
                degradation=issue,
            )

        return AcquisitionOutcome(
            document=document,
            record=DocumentRecord.from_document(document),
        )


def _abstract_outcome(
    paper: Paper,
    *,
    fallback_code: str | None = None,
    degradation: RunIssue | None = None,
) -> AcquisitionOutcome:
    normalized_abstract = _normalize_abstract(paper.abstract)
    if not normalized_abstract:
        code = fallback_code or "abstract_text_empty"
        issue = degradation or _issue(
            paper,
            code=code,
            message="paper abstract contains no usable text",
        )
        return AcquisitionOutcome(
            document=None,
            record=None,
            degradations=[issue],
            excluded_code=code,
        )

    text = f"Abstract\n{normalized_abstract}"
    document = PaperDocument(
        paper_id=paper.paper_id,
        content_source="abstract",
        pages=[DocumentPage(page_number=1, text=text)],
        content_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )
    return AcquisitionOutcome(
        document=document,
        record=DocumentRecord.from_document(document, fallback_code=fallback_code),
        degradations=[] if degradation is None else [degradation],
    )


def _normalize_abstract(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(
        character
        for character in text
        if character in "\n\t" or not unicodedata.category(character).startswith("C")
    )

    normalized: list[str] = []
    previous_blank = False
    for raw_line in text.split("\n"):
        line = re.sub(r"[^\S\n]+", " ", raw_line).strip()
        if not line:
            if normalized and not previous_blank:
                normalized.append("")
            previous_blank = True
            continue
        normalized.append(line)
        previous_blank = False

    while normalized and not normalized[-1]:
        normalized.pop()
    return "\n".join(normalized)


def _issue(paper: Paper, *, code: str, message: str) -> RunIssue:
    return RunIssue(
        stage="acquisition",
        code=code,
        paper_id=paper.paper_id,
        message=message,
    )
