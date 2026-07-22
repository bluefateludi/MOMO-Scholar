from __future__ import annotations

import re
from dataclasses import dataclass

from paper_agent.fulltext.models import PaperDocument
from paper_agent.schemas import Chunk


_CANONICAL_SECTIONS = {
    "abstract": "Abstract",
    "introduction": "Introduction",
    "method": "Method",
    "methods": "Methods",
    "results": "Results",
    "discussion": "Discussion",
    "limitations": "Limitations",
    "conclusion": "Conclusion",
    "references": "References",
}
_NUMBERED_HEADING = re.compile(
    r"^\s*\d+(?:\.\d+)*\.?\s+([A-Z][^.!?]{0,79})\s*$"
)


@dataclass(frozen=True, slots=True)
class ChunkingOutcome:
    chunks: tuple[Chunk, ...]
    warnings: tuple[str, ...] = ()


def _heading(line: str) -> str | None:
    stripped = line.strip()
    canonical = _CANONICAL_SECTIONS.get(stripped.casefold())
    if canonical is not None:
        return canonical

    match = _NUMBERED_HEADING.fullmatch(stripped)
    if match is None:
        return None
    title = match.group(1).strip()
    return _CANONICAL_SECTIONS.get(title.casefold(), title)


def _validate_window(max_words: int, overlap_words: int) -> None:
    if max_words < 1:
        raise ValueError("max_words must be at least 1")
    if overlap_words < 1:
        raise ValueError("overlap_words must be at least 1")
    if overlap_words >= max_words:
        raise ValueError("overlap_words must be less than max_words")


def chunk_document(
    document: PaperDocument,
    *,
    max_words: int = 180,
    overlap_words: int = 30,
) -> ChunkingOutcome:
    _validate_window(max_words, overlap_words)

    recognized_heading = any(
        _heading(line) is not None
        for page in document.pages
        for line in page.text.splitlines()
    )
    warnings: list[str] = []
    if not recognized_heading:
        warnings.append("section_detection_failed")

    sections: list[tuple[str | None, list[tuple[str, int]]]] = []
    active_section: str | None = None
    active_words: list[tuple[str, int]] = []
    references_excluded = False

    def flush() -> None:
        nonlocal active_words
        if active_words:
            sections.append((active_section, active_words))
            active_words = []

    for page in document.pages:
        if references_excluded:
            break
        for line in page.text.splitlines():
            heading = _heading(line)
            if heading is not None:
                flush()
                active_section = heading
                if heading.casefold() == "references":
                    references_excluded = True
                    warnings.append("reference_section_excluded")
                    break
                continue
            active_words.extend((word, page.page_number) for word in line.split())
    flush()

    chunks: list[Chunk] = []
    step = max_words - overlap_words
    for section, words_with_pages in sections:
        offset = 0
        while offset < len(words_with_pages):
            window = words_with_pages[offset : offset + max_words]
            sequence = len(chunks) + 1
            chunks.append(
                Chunk(
                    chunk_id=f"{document.paper_id}:chunk:{sequence:03d}",
                    paper_id=document.paper_id,
                    section=section if recognized_heading else None,
                    page=window[0][1],
                    text=" ".join(word for word, _page in window),
                    token_count=len(window),
                )
            )
            if offset + max_words >= len(words_with_pages):
                break
            offset += step

    return ChunkingOutcome(chunks=tuple(chunks), warnings=tuple(warnings))


# Controlled legacy format: each non-empty block is "heading\nbody".
def _sections(text: str) -> list[tuple[str | None, str]]:
    blocks = [block.strip() for block in text.split("\n\n") if block.strip()]
    sections: list[tuple[str | None, str]] = []
    for block in blocks:
        lines = block.splitlines()
        if len(lines) > 1:
            sections.append((lines[0].strip() or None, " ".join(lines[1:]).strip()))
        else:
            sections.append((None, block))
    return sections


def chunk_text(paper_id: str, text: str, max_words: int = 180) -> list[Chunk]:
    """Deprecated compatibility wrapper retained until the Task 16 migration."""
    if max_words < 1:
        raise ValueError("max_words must be at least 1")

    chunks: list[Chunk] = []
    for section, body in _sections(text):
        words = body.split()
        for offset in range(0, len(words), max_words):
            chunk_words = words[offset : offset + max_words]
            if not chunk_words:
                continue
            number = len(chunks) + 1
            chunks.append(
                Chunk(
                    chunk_id=f"{paper_id}:chunk:{number:03d}",
                    paper_id=paper_id,
                    section=section,
                    page=None,
                    text=" ".join(chunk_words),
                    token_count=len(chunk_words),
                )
            )
    return chunks
