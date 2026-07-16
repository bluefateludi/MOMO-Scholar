"""Offline lexical, vector, and hybrid retrieval evaluation."""

import json
from pathlib import Path

from pydantic import ValidationError

from paper_agent.eval.metrics import mrr_at_k, ndcg_at_k, precision_at_k, recall_at_k
from paper_agent.evidence.fusion import fuse_candidates
from paper_agent.evidence.models import RetrievalCandidate
from paper_agent.evidence.retriever import LexicalCandidateSource
from paper_agent.schemas import Chunk


_REQUIRED_CASE_FIELDS = (
    "case_id",
    "query",
    "chunks",
    "relevance_by_chunk_id",
    "vector_ranked_chunk_ids",
)
_MODES = ("lexical", "vector", "hybrid")
_METRICS = {
    "recall_at_k": recall_at_k,
    "precision_at_k": precision_at_k,
    "mrr_at_k": mrr_at_k,
    "ndcg_at_k": ndcg_at_k,
}


def _parse_case(raw_case: object, index: int, seen_case_ids: set[str]) -> dict[str, object]:
    if not isinstance(raw_case, dict):
        raise ValueError(f"case {index}: case must be an object")
    for field in _REQUIRED_CASE_FIELDS:
        if field not in raw_case:
            raise ValueError(f"case {index}: missing required field {field}")

    case_id = raw_case["case_id"]
    if not isinstance(case_id, str) or not case_id.strip():
        raise ValueError(f"case {index}: case_id must be a non-blank string")
    if case_id in seen_case_ids:
        raise ValueError(f"duplicate case_id: {case_id}")
    seen_case_ids.add(case_id)

    query = raw_case["query"]
    if not isinstance(query, str) or not query.strip():
        raise ValueError(f"case {case_id}: query must be a non-blank string")

    raw_chunks = raw_case["chunks"]
    if not isinstance(raw_chunks, list):
        raise ValueError(f"case {case_id}: chunks must be a list")
    chunks: list[Chunk] = []
    chunk_ids: set[str] = set()
    for chunk_index, raw_chunk in enumerate(raw_chunks):
        try:
            chunk = Chunk.model_validate(raw_chunk)
        except ValidationError as error:
            location = ".".join(str(part) for part in error.errors()[0]["loc"])
            raise ValueError(
                f"case {case_id}: chunks[{chunk_index}].{location} is invalid"
            ) from error
        if chunk.chunk_id in chunk_ids:
            raise ValueError(
                f"case {case_id}: chunks contain duplicate chunk_id {chunk.chunk_id}"
            )
        chunk_ids.add(chunk.chunk_id)
        chunks.append(chunk)

    relevance = raw_case["relevance_by_chunk_id"]
    if not isinstance(relevance, dict):
        raise ValueError(f"case {case_id}: relevance_by_chunk_id must be an object")
    if any(chunk_id not in chunk_ids for chunk_id in relevance):
        raise ValueError(
            f"case {case_id}: relevance_by_chunk_id contains an unknown chunk ID"
        )
    if any(type(grade) is not int or grade < 0 for grade in relevance.values()):
        raise ValueError(
            f"case {case_id}: relevance_by_chunk_id grades must be non-negative integers"
        )

    vector_ids = raw_case["vector_ranked_chunk_ids"]
    if not isinstance(vector_ids, list):
        raise ValueError(f"case {case_id}: vector_ranked_chunk_ids must be a list")
    if len(vector_ids) != len(set(vector_ids)):
        raise ValueError(f"case {case_id}: vector_ranked_chunk_ids must be unique")
    if any(chunk_id not in chunk_ids for chunk_id in vector_ids):
        raise ValueError(
            f"case {case_id}: vector_ranked_chunk_ids contains an unknown chunk ID"
        )

    return {
        "case_id": case_id,
        "query": query,
        "chunks": chunks,
        "relevance_by_chunk_id": relevance,
        "vector_ranked_chunk_ids": vector_ids,
    }


def _metrics(
    ranked_chunk_ids: list[str], relevance_by_chunk_id: dict[str, int], k: int
) -> dict[str, float]:
    return {
        name: metric(ranked_chunk_ids, relevance_by_chunk_id, k)
        for name, metric in _METRICS.items()
    }


def evaluate_retrieval_fixture(
    path: str | Path, *, k: int = 8
) -> dict[str, object]:
    """Evaluate three retrieval modes from a deterministic offline fixture."""
    if type(k) is not int or k < 1:
        raise ValueError("k must be a positive integer")

    raw_cases = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw_cases, list):
        raise ValueError("fixture top level must be a list")

    seen_case_ids: set[str] = set()
    parsed_cases = [
        _parse_case(raw_case, index, seen_case_ids)
        for index, raw_case in enumerate(raw_cases)
    ]
    lexical_source = LexicalCandidateSource()
    cases: list[dict[str, object]] = []

    for case in parsed_cases:
        chunks = case["chunks"]
        query = case["query"]
        relevance = case["relevance_by_chunk_id"]
        vector_ids = case["vector_ranked_chunk_ids"]
        chunk_by_id = {chunk.chunk_id: chunk for chunk in chunks}

        lexical = lexical_source.retrieve(query, chunks, max(k, len(chunks)))
        vector = [
            RetrievalCandidate(
                chunk_id=chunk_id,
                paper_id=chunk_by_id[chunk_id].paper_id,
                text=chunk_by_id[chunk_id].text,
                section=chunk_by_id[chunk_id].section,
                page=chunk_by_id[chunk_id].page,
                retrieval_sources=("vector",),
                lexical_score=None,
                lexical_rank=None,
                vector_score=1.0 / rank,
                vector_rank=rank,
                fusion_score=None,
            )
            for rank, chunk_id in enumerate(vector_ids, start=1)
        ]
        hybrid = fuse_candidates(
            lexical,
            vector,
            rrf_k=60,
            active_sources=("lexical", "vector"),
        )
        rankings = {
            "lexical": [candidate.chunk_id for candidate in lexical[:k]],
            "vector": [candidate.chunk_id for candidate in vector[:k]],
            "hybrid": [candidate.chunk_id for candidate in hybrid[:k]],
        }
        cases.append(
            {
                "case_id": case["case_id"],
                "modes": {
                    mode: {
                        "ranked_chunk_ids": rankings[mode],
                        "metrics": _metrics(rankings[mode], relevance, k),
                    }
                    for mode in _MODES
                },
            }
        )

    summary = {
        mode: {
            metric: (
                sum(case["modes"][mode]["metrics"][metric] for case in cases)
                / len(cases)
                if cases
                else 0.0
            )
            for metric in _METRICS
        }
        for mode in _MODES
    }
    return {"k": k, "cases": cases, "summary": summary}
