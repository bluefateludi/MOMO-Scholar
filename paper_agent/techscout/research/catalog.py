from __future__ import annotations

from paper_agent.techscout.models import Candidate

from .models import CandidateSourcePolicy


def hero_case_policy(candidate: Candidate) -> CandidateSourcePolicy:
    """Return the fixed Python 3.11 Chroma/Qdrant Local showcase policy."""

    name = candidate.name.casefold()
    version = candidate.resolved_version or candidate.requested_version
    if "chroma" in name:
        return CandidateSourcePolicy(
            candidate_id=candidate.candidate_id,
            version=version,
            official_domains=("docs.trychroma.com",),
            official_queries=(
                "Chroma Python persistent client metadata filtering",
            ),
            repository_url="https://github.com/chroma-core/chroma",
        )
    if "qdrant" in name:
        return CandidateSourcePolicy(
            candidate_id=candidate.candidate_id,
            version=version,
            official_domains=("qdrant.tech",),
            official_queries=(
                "Qdrant Local Python persistence metadata filtering",
            ),
            repository_url="https://github.com/qdrant/qdrant-client",
        )
    if "pgvector" in name:
        return CandidateSourcePolicy(
            candidate_id=candidate.candidate_id,
            version=version,
            official_domains=(),
            official_queries=(),
            repository_url="https://github.com/pgvector/pgvector-python",
            research_only=True,
        )
    raise ValueError(f"candidate is outside the fixed hero case: {candidate.name}")
