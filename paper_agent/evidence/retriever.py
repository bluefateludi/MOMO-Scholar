from __future__ import annotations

import re
from collections.abc import Sequence

from paper_agent.evidence.models import RetrievalCandidate
from paper_agent.schemas import Chunk, Evidence


def _terms(text: str) -> set[str]:
    return {
        term
        for term in re.findall(r"[a-zA-Z][a-zA-Z0-9-]+", text.lower())
        if len(term) > 2
    }


def retrieve_lexical_candidates(
    question: str,
    chunks: Sequence[Chunk],
    limit: int,
) -> list[RetrievalCandidate]:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    query_terms = _terms(question)
    if not query_terms or not chunks:
        return []
    scored: list[tuple[float, str, Chunk]] = []
    for chunk in chunks:
        score = len(query_terms & _terms(chunk.text)) / len(query_terms)
        if score > 0:
            scored.append((score, chunk.chunk_id, chunk))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [
        RetrievalCandidate(
            chunk_id=chunk.chunk_id,
            paper_id=chunk.paper_id,
            text=chunk.text,
            section=chunk.section,
            page=chunk.page,
            retrieval_sources=("lexical",),
            lexical_score=score,
            lexical_rank=rank,
        )
        for rank, (score, _chunk_id, chunk) in enumerate(
            scored[:limit], start=1
        )
    ]


def retrieve_evidence(
    question: str,
    chunks: list[Chunk],
    run_id: str,
    top_k: int = 8,
) -> list[Evidence]:
    if top_k < 1:
        raise ValueError("top_k must be at least 1")
    if not run_id.strip():
        raise ValueError("run_id must not be empty")

    candidates = retrieve_lexical_candidates(question, chunks, limit=top_k)
    return [
        Evidence(
            evidence_id=f"{run_id}:ev_{index:03d}",
            paper_id=item.paper_id,
            chunk_id=item.chunk_id,
            claim_type="retrieved",
            quote=item.text,
            relevance_score=round(min(item.lexical_score or 0.0, 1.0), 4),
        )
        for index, item in enumerate(candidates, start=1)
    ]
