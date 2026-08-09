from datetime import datetime, timezone

from paper_agent.evidence.hybrid import HybridEvidenceRetriever
from paper_agent.evidence.retriever import LexicalCandidateSource
from paper_agent.techscout.context import ContextEngine, ContextStage, HybridContextRetriever
from paper_agent.techscout.models import (
    Candidate,
    CandidateEvidence,
    EnvironmentSpec,
    EvidenceKind,
    ResearchRequest,
    SourceChunk,
    SourceDocument,
    SourceType,
)
from paper_agent.techscout.runtime_skills import fixed_skill_registry


def _request() -> ResearchRequest:
    return ResearchRequest(
        run_id="run:context-test",
        question="Which vector store supports filtering?",
        project_context="Local RAG",
        environment=EnvironmentSpec(
            python_version="3.11", operating_system="linux", deployment="local"
        ),
        hard_constraints=("metadata filtering", "persistence"),
        candidates=(
            Candidate(candidate_id="candidate:a", name="Alpha"),
            Candidate(candidate_id="candidate:b", name="Beta"),
        ),
    )


def _source(candidate: str, suffix: str) -> SourceDocument:
    return SourceDocument(
        source_id=f"source:{suffix}",
        candidate_id=candidate,
        source_type=SourceType.OFFICIAL_DOCUMENTATION,
        url=f"https://docs.example.com/{suffix}",
        title=f"Docs {suffix}",
        as_of=datetime(2026, 8, 9, tzinfo=timezone.utc),
        content_sha256="a" * 64,
    )


def _engine() -> ContextEngine:
    service = HybridEvidenceRetriever(
        lexical_source=LexicalCandidateSource(),
        vector_source=None,
        requested_mode="lexical",
        candidate_k=8,
        top_k=8,
        rrf_k=60,
    )
    return ContextEngine(HybridContextRetriever(service))


def test_planning_packet_contains_summaries_but_loads_no_research_data() -> None:
    packet = _engine().build(
        packet_id="context:planning",
        stage=ContextStage.INTAKE_PLANNING,
        request=_request(),
        skills=fixed_skill_registry().all(),
        documents=(_source("candidate:a", "a"),),
    )

    assert len(packet.skill_summaries) == 4
    assert packet.sources == ()
    assert packet.chunks == ()
    assert packet.evidence == ()


def test_research_packet_excludes_other_candidates_and_unrelated_full_content() -> None:
    source_a = _source("candidate:a", "a")
    source_b = _source("candidate:b", "b")
    relevant = SourceChunk(
        chunk_id="chunk:a:filtering",
        source_id=source_a.source_id,
        text="Alpha supports metadata filtering and persistence.",
        ordinal=0,
        content_sha256="b" * 64,
    )
    unrelated = SourceChunk(
        chunk_id="chunk:b:full-page",
        source_id=source_b.source_id,
        text="UNRELATED_FULL_PAGE " * 500,
        ordinal=0,
        content_sha256="c" * 64,
    )

    packet = _engine().build(
        packet_id="context:research:a",
        stage=ContextStage.RESEARCH,
        request=_request(),
        candidate_id="candidate:a",
        documents=(source_a, source_b),
        chunks=(relevant, unrelated),
    )

    assert packet.candidate_id == "candidate:a"
    assert packet.sources == (source_a,)
    assert packet.chunks == (relevant,)
    assert "UNRELATED_FULL_PAGE" not in packet.model_dump_json()


def test_validation_packet_uses_structured_evidence_not_raw_chunks() -> None:
    source = _source("candidate:a", "a")
    chunk = SourceChunk(
        chunk_id="chunk:a:filtering",
        source_id=source.source_id,
        text="Raw source excerpt",
        ordinal=0,
        content_sha256="b" * 64,
    )
    evidence = CandidateEvidence(
        evidence_id="evidence:a:filtering",
        candidate_id="candidate:a",
        constraint="metadata filtering",
        claim="Alpha supports filtering.",
        source_ids=(source.source_id,),
        chunk_ids=(chunk.chunk_id,),
        kind=EvidenceKind.RETRIEVED_FACT,
    )

    packet = _engine().build(
        packet_id="context:validation:a",
        stage=ContextStage.VALIDATION,
        request=_request(),
        candidate_id="candidate:a",
        documents=(source,),
        chunks=(chunk,),
        evidence=(evidence,),
        poc_result={"status": "passed"},
        gate_rules=("cover every hard constraint",),
    )

    assert packet.evidence == (evidence,)
    assert packet.chunks == ()
    assert packet.poc_result == {"status": "passed"}
