from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Literal

import pymupdf

from paper_agent.fulltext.models import DocumentPage, PaperDocument


PdfParseErrorCode = Literal[
    "pdf_corrupt",
    "pdf_encrypted",
    "pdf_too_many_pages",
    "pdf_text_empty",
]


@dataclass(frozen=True, slots=True)
class PdfParseError(RuntimeError):
    code: PdfParseErrorCode
    message: str

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


class PdfParser:
    def __init__(self, *, max_pages: int, min_useful_characters: int = 200) -> None:
        self._max_pages = max_pages
        self._min_useful_characters = min_useful_characters

    def parse(self, *, paper_id: str, pdf_bytes: bytes) -> PaperDocument:
        try:
            document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        except (pymupdf.EmptyFileError, pymupdf.FileDataError) as exc:
            raise _corrupt_error() from exc

        with document:
            if document.needs_pass:
                raise PdfParseError("pdf_encrypted", "PDF requires a password")

            try:
                page_count = document.page_count
            except (pymupdf.EmptyFileError, pymupdf.FileDataError) as exc:
                raise _corrupt_error() from exc

            if page_count > self._max_pages:
                raise PdfParseError(
                    "pdf_too_many_pages",
                    f"PDF has more than the allowed {self._max_pages} pages",
                )

            normalized_pages: list[list[str]] = []
            for page_index in range(page_count):
                try:
                    page = document.load_page(page_index)
                    raw_text = page.get_text()
                except (pymupdf.EmptyFileError, pymupdf.FileDataError) as exc:
                    raise _corrupt_error() from exc
                normalized_pages.append(_normalize_lines(raw_text))

        repeated_edges = _repeated_edge_lines(normalized_pages)
        pages: list[DocumentPage] = []
        warnings: list[str] = []
        for page_index, lines in enumerate(normalized_pages):
            cleaned_lines = _remove_repeated_edges(lines, repeated_edges)
            text = "\n".join(cleaned_lines).strip()
            page_number = page_index + 1
            if not text:
                warnings.append(f"page_text_empty:{page_number}")
                continue
            pages.append(DocumentPage(page_number=page_number, text=text))

        useful_character_count = sum(
            1 for page in pages for character in page.text if not character.isspace()
        )
        if useful_character_count < self._min_useful_characters:
            raise PdfParseError(
                "pdf_text_empty",
                "PDF contains too little extractable text",
            )

        return PaperDocument(
            paper_id=paper_id,
            content_source="pdf",
            pages=pages,
            content_sha256=hashlib.sha256(pdf_bytes).hexdigest(),
            warnings=warnings,
        )


def _corrupt_error() -> PdfParseError:
    return PdfParseError("pdf_corrupt", "PDF data could not be parsed")


def _normalize_lines(text: str) -> list[str]:
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
    return normalized


def _edge_indexes(lines: list[str]) -> set[int]:
    non_empty_indexes = [index for index, line in enumerate(lines) if line]
    return set(non_empty_indexes[:3] + non_empty_indexes[-3:])


def _repeated_edge_lines(pages: list[list[str]]) -> set[str]:
    counts: Counter[str] = Counter()
    for lines in pages:
        counts.update({lines[index] for index in _edge_indexes(lines)})
    return {
        line
        for line, count in counts.items()
        if count > 1 and count > len(pages) / 2
    }


def _remove_repeated_edges(lines: list[str], repeated_edges: set[str]) -> list[str]:
    edge_indexes = _edge_indexes(lines)
    return [
        line
        for index, line in enumerate(lines)
        if index not in edge_indexes or line not in repeated_edges
    ]
