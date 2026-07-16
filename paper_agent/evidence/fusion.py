from collections.abc import Sequence

from paper_agent.evidence.models import RetrievalCandidate, RetrievalSource


_VALID_ACTIVE_SOURCES = {
    ("lexical",),
    ("vector",),
    ("lexical", "vector"),
}
_IDENTITY_FIELDS = ("paper_id", "text", "section", "page")


def fuse_candidates(
    lexical: Sequence[RetrievalCandidate],
    vector: Sequence[RetrievalCandidate],
    *,
    rrf_k: int,
    active_sources: tuple[RetrievalSource, ...],
) -> list[RetrievalCandidate]:
    if type(rrf_k) is not int or rrf_k < 1:
        raise ValueError("rrf_k must be a positive integer")
    if active_sources not in _VALID_ACTIVE_SOURCES:
        raise ValueError("active_sources must use a supported canonical shape")

    _validate_source_candidates(lexical, "lexical")
    _validate_source_candidates(vector, "vector")
    if "lexical" not in active_sources and lexical:
        raise ValueError("inactive lexical source must have no candidates")
    if "vector" not in active_sources and vector:
        raise ValueError("inactive vector source must have no candidates")

    lexical_by_id = _index_unique(lexical, "lexical")
    vector_by_id = _index_unique(vector, "vector")
    maximum_score = len(active_sources) / (rrf_k + 1)
    fused: list[RetrievalCandidate] = []

    for chunk_id in lexical_by_id.keys() | vector_by_id.keys():
        lexical_candidate = lexical_by_id.get(chunk_id)
        vector_candidate = vector_by_id.get(chunk_id)
        if lexical_candidate is not None and vector_candidate is not None:
            _validate_identity(lexical_candidate, vector_candidate)

        base = lexical_candidate or vector_candidate
        assert base is not None
        sources: tuple[RetrievalSource, ...] = tuple(
            source
            for source, candidate in (
                ("lexical", lexical_candidate),
                ("vector", vector_candidate),
            )
            if candidate is not None
        )
        raw_score = sum(
            1 / (rrf_k + candidate_rank)
            for candidate_rank in (
                lexical_candidate.lexical_rank if lexical_candidate else None,
                vector_candidate.vector_rank if vector_candidate else None,
            )
            if candidate_rank is not None
        )
        values = base.model_dump()
        values.update(
            retrieval_sources=sources,
            lexical_score=(
                lexical_candidate.lexical_score if lexical_candidate else None
            ),
            lexical_rank=(
                lexical_candidate.lexical_rank if lexical_candidate else None
            ),
            vector_score=vector_candidate.vector_score if vector_candidate else None,
            vector_rank=vector_candidate.vector_rank if vector_candidate else None,
            fusion_score=min(max(raw_score / maximum_score, 0.0), 1.0),
        )
        fused.append(RetrievalCandidate.model_validate(values))

    return sorted(fused, key=lambda candidate: (-candidate.fusion_score, candidate.chunk_id))


def _validate_source_candidates(
    candidates: Sequence[RetrievalCandidate], source: RetrievalSource
) -> None:
    expected = (source,)
    if any(candidate.retrieval_sources != expected for candidate in candidates):
        raise ValueError(f"{source} input candidates must contain only {source}")


def _index_unique(
    candidates: Sequence[RetrievalCandidate], source: RetrievalSource
) -> dict[str, RetrievalCandidate]:
    indexed: dict[str, RetrievalCandidate] = {}
    for candidate in candidates:
        if candidate.chunk_id in indexed:
            raise ValueError(f"duplicate chunk_id {candidate.chunk_id} in {source} input")
        indexed[candidate.chunk_id] = candidate
    return indexed


def _validate_identity(
    lexical: RetrievalCandidate, vector: RetrievalCandidate
) -> None:
    if any(
        getattr(lexical, field) != getattr(vector, field)
        for field in _IDENTITY_FIELDS
    ):
        raise ValueError(f"candidate identity conflict for chunk_id {lexical.chunk_id}")
