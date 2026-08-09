from __future__ import annotations

from datetime import datetime, timedelta, timezone

from paper_agent.web.event_cursor import encode_event_cursor
from paper_agent.web.techscout_api_models import (
    TechScoutApprovalProjection,
    TechScoutCandidateProjection,
    TechScoutConstraintProjection,
    TechScoutEnvironmentRequest,
    TechScoutEvidenceProjection,
    TechScoutPocProjection,
    TechScoutProgress,
    TechScoutRecoveryProjection,
    TechScoutReportProjection,
    TechScoutRunDetail,
    TraceEvent,
    TracePage,
)


SYNTHETIC_RUN_ID = "10000000-0000-4000-8000-000000000001"
FIXTURE_NOTICE = "Synthetic Wave 1 contract fixture — not live research or evaluation evidence."
AS_OF = datetime(2026, 8, 9, 4, 0, tzinfo=timezone.utc)

EVIDENCE = [
    TechScoutEvidenceProjection(
        evidence_id="ev-chroma-persistence", candidate_id="chroma",
        kind="retrieved_fact", claim="Chroma documents local persistent storage.",
        source_title="Synthetic Chroma persistence snapshot",
        source_type="official_documentation", source_url=None, as_of=AS_OF,
    ),
    TechScoutEvidenceProjection(
        evidence_id="ev-chroma-poc", candidate_id="chroma",
        kind="local_measurement", claim="The frozen allowlisted fixture passes persistence and metadata filtering checks.",
        source_title="Synthetic allowlisted PoC result", source_type="poc",
        source_url=None, as_of=AS_OF,
    ),
    TechScoutEvidenceProjection(
        evidence_id="ev-qdrant-local", candidate_id="qdrant-local",
        kind="retrieved_fact", claim="Qdrant documents an embedded local mode.",
        source_title="Synthetic Qdrant Local snapshot",
        source_type="official_documentation", source_url=None, as_of=AS_OF,
    ),
    TechScoutEvidenceProjection(
        evidence_id="ev-pgvector-research-only", candidate_id="pgvector",
        kind="retrieved_fact", claim="pgvector requires PostgreSQL; this fixture has no trusted PostgreSQL recipe.",
        source_title="Synthetic pgvector package snapshot",
        source_type="package_metadata", source_url=None, as_of=AS_OF,
    ),
]

CANDIDATES = [
    TechScoutCandidateProjection(
        candidate_id="chroma", name="Chroma", support_level="v1_supported",
        resolved_version="fixture-pinned", compatibility="compatible",
        verdict="recommended", evidence_ids=["ev-chroma-persistence", "ev-chroma-poc"],
    ),
    TechScoutCandidateProjection(
        candidate_id="qdrant-local", name="Qdrant Local", support_level="v1_supported",
        resolved_version="fixture-pinned", compatibility="compatible",
        verdict="not_recommended", evidence_ids=["ev-qdrant-local"],
    ),
    TechScoutCandidateProjection(
        candidate_id="pgvector", name="pgvector", support_level="research_only",
        compatibility="unknown", verdict="insufficient_evidence",
        evidence_ids=["ev-pgvector-research-only"],
    ),
]

DETAIL = TechScoutRunDetail(
    id=SYNTHETIC_RUN_ID, status="completed", synthetic=True,
    fixture_name="happy-path", question="Choose a local vector store for a Python 3.11 RAG service.",
    mode="fast", progress=TechScoutProgress(
        stage="terminal", completed_stages=["plan", "research", "verify", "decide"],
        elapsed_seconds=18.4,
    ), created_at=AS_OF, finished_at=AS_OF + timedelta(seconds=18.4),
    project_context="A single-node local service with no separately managed database.",
    environment=TechScoutEnvironmentRequest(
        python_version="3.11", operating_system="linux-container",
        deployment="single-node-local",
    ),
    hard_constraints=[
        "local persistence", "metadata equality filtering", "no separately managed database",
    ], candidates=CANDIDATES,
    recovery=TechScoutRecoveryProjection(
        attempted=False, outcome="not_needed", attempts_used=0,
    ),
    approval=TechScoutApprovalProjection(required=False, status="not_required"), issues=[],
)

REPORT = TechScoutReportProjection(
    run_id=SYNTHETIC_RUN_ID, verdict="recommended", recommendation="chroma",
    summary="The synthetic fixture selects Chroma because the frozen evidence and allowlisted PoC cover every hard constraint.",
    constraints=[
        TechScoutConstraintProjection(
            constraint=constraint, candidate_id="chroma", status="satisfied",
            evidence_ids=["ev-chroma-persistence", "ev-chroma-poc"],
        )
        for constraint in DETAIL.hard_constraints
    ],
    poc_results=[
        TechScoutPocProjection(
            candidate_id="chroma", recipe_id="fixture:chroma-local-contract-v1",
            status="passed", checks=["import", "persistence", "upsert", "query", "filter"],
            duration_ms=640, synthetic=True,
        ),
        TechScoutPocProjection(
            candidate_id="qdrant-local", recipe_id="fixture:qdrant-local-contract-v1",
            status="passed", checks=["import", "persistence", "upsert", "query", "filter"],
            duration_ms=710, synthetic=True,
        ),
        TechScoutPocProjection(
            candidate_id="pgvector", status="research_only", checks=[], duration_ms=0,
            synthetic=True,
        ),
    ],
    limitations=[
        FIXTURE_NOTICE,
        "Small contract checks do not establish production-scale performance.",
        "pgvector remains research-only without a reviewed PostgreSQL fixture.",
    ], evidence_ids=[item.evidence_id for item in EVIDENCE], synthetic=True,
)

TRACE = TracePage(items=[
    TraceEvent(
        cursor=encode_event_cursor(1), event_type="stage", stage="plan",
        status="completed", label="Investigation plan frozen from the synthetic request.",
        duration_ms=900, created_at=AS_OF + timedelta(seconds=1),
    ),
    TraceEvent(
        cursor=encode_event_cursor(2), event_type="skill", stage="research",
        status="completed", label="Official-source fixture selected.",
        skill="official-source-research", duration_ms=4200,
        created_at=AS_OF + timedelta(seconds=2),
    ),
    TraceEvent(
        cursor=encode_event_cursor(3), event_type="tool", stage="verify",
        status="completed", label="Allowlisted fixture recipe completed.",
        skill="vector-store-verification", tool="poc.run_allowlisted",
        duration_ms=710, created_at=AS_OF + timedelta(seconds=3),
    ),
    TraceEvent(
        cursor=encode_event_cursor(4), event_type="stage", stage="decide",
        status="completed", label="Deterministic gate published the fixture decision.",
        duration_ms=1300, created_at=AS_OF + timedelta(seconds=4),
    ),
])
