from __future__ import annotations

import re

from paper_agent.schemas import Chunk, Evidence


def _terms(text: str) -> set[str]:
    return {
        term
        for term in re.findall(r"[a-zA-Z][a-zA-Z0-9-]+", text.lower())
        if len(term) > 2
    }


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

    query_terms = _terms(question)
    if not query_terms or not chunks:
        return []

    scored: list[tuple[float, str, Chunk]] = []
    for chunk in chunks:
        overlap = len(query_terms & _terms(chunk.text))
        score = overlap / len(query_terms)
        if score > 0:
            scored.append((score, chunk.chunk_id, chunk))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [
        Evidence(
            evidence_id=f"{run_id}:ev_{index:03d}",
            paper_id=chunk.paper_id,
            chunk_id=chunk.chunk_id,
            claim_type="retrieved",
            quote=chunk.text,
            relevance_score=round(min(score, 1.0), 4),
        )
        for index, (score, _chunk_id, chunk) in enumerate(scored[:top_k], start=1)
    ]
