from __future__ import annotations

from paper_agent.schemas import Chunk


# Controlled format: each non-empty block is "heading\nbody"; a one-line block is body-only.
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
