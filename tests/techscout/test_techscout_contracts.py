import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from paper_agent.techscout.errors import (
    Failure,
    FailureCode,
    FailureStage,
    RecoveryAction,
)
from paper_agent.techscout.models import (
    Candidate,
    CandidateEvidence,
    ConstraintResult,
    DecisionReport,
    EnvironmentSpec,
    GateDecision,
    GateOutcome,
    CacheStatus,
    ConstraintStatus,
    EvidenceKind,
    PocArtifact,
    PocPlan,
    PocResult,
    ResearchPlan,
    ResearchRequest,
    RunManifest,
    RunMode,
    PocStatus,
    SourceType,
    SkillSelection,
    SkillSpec,
    SourceChunk,
    SourceDocument,
    TerminalStatus,
    ToolCall,
    ToolResult,
    ToolStatus,
    Verdict,
)


def _candidate() -> Candidate:
    return Candidate(
        candidate_id="candidate:qdrant-client",
        name="Qdrant Local",
        repository_url="https://github.com/qdrant/qdrant-client",
        package_name="qdrant-client",
        requested_version="1.15.*",
        resolved_version="1.15.1",
    )


def _request() -> ResearchRequest:
    return ResearchRequest(
        run_id="run:fixture-001",
        question="Which local vector store fits this service?",
        project_context="A local Python RAG service.",
        environment=EnvironmentSpec(
            python_version="3.11",
            operating_system="linux",
            deployment="local-container",
        ),
        hard_constraints=("persistence", "metadata filtering"),
        candidates=(_candidate(),),
        mode=RunMode.FAST,
    )


def test_request_is_strict_immutable_and_preserves_stable_ids() -> None:
    request = _request()

    payload = json.loads(request.model_dump_json())
    restored = ResearchRequest.model_validate_json(json.dumps(payload))

    assert payload["run_id"] == "run:fixture-001"
    assert payload["candidates"][0]["candidate_id"] == "candidate:qdrant-client"
    assert restored == request
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ResearchRequest.model_validate({**payload, "surprise": True})
    with pytest.raises(ValidationError):
        ResearchRequest.model_validate({**payload, "hard_constraints": "persistence"})
    with pytest.raises(ValidationError):
        Candidate.model_validate(
            {**payload["candidates"][0], "candidate_id": "candidate:changed", "extra": 1}
        )


def test_all_domain_artifacts_are_json_serializable() -> None:
    source = SourceDocument(
        source_id="source:qdrant-filter-docs@sha256:abc123",
        candidate_id="candidate:qdrant-client",
        source_type=SourceType.OFFICIAL_DOCUMENTATION,
        url="https://qdrant.tech/documentation/concepts/filtering/",
        title="Filtering",
        version="1.15",
        as_of=datetime(2026, 8, 9, tzinfo=timezone.utc),
        content_sha256="a" * 64,
    )
    chunk = SourceChunk(
        chunk_id="chunk:qdrant-filter-docs:0001",
        source_id=source.source_id,
        text="Qdrant supports payload filtering.",
        ordinal=0,
        content_sha256="b" * 64,
    )
    evidence = CandidateEvidence(
        evidence_id="evidence:qdrant:filtering",
        candidate_id="candidate:qdrant-client",
        constraint="metadata filtering",
        claim="Qdrant supports metadata filtering.",
        source_ids=(source.source_id,),
        chunk_ids=(chunk.chunk_id,),
        kind=EvidenceKind.RETRIEVED_FACT,
    )
    skill = SkillSpec(
        skill_id="skill:official-doc-research@1",
        name="official-doc-research",
        version="1",
        stage="research_candidates",
        instructions="Use official sources.",
        completion_criteria=("official evidence retained",),
        allowed_tools=("web.search", "web.fetch"),
        source_budget=5,
        tool_call_budget=4,
        step_budget=4,
        token_budget=2_000,
        handled_failure_codes=(FailureCode.SEARCH_TIMEOUT,),
    )
    artifacts = (
        ResearchPlan(
            plan_id="plan:fixture-001",
            investigation_dimensions=("compatibility",),
            required_capabilities=("official-doc-research",),
            planned_evidence=("official documentation",),
            poc_intent="verify local filtering",
        ),
        SkillSelection(
            selection_id="selection:fixture-001:research",
            skill_id=skill.skill_id,
            stage="research_candidates",
            reason="Official evidence is required.",
        ),
        skill,
        ToolCall(
            tool_call_id="tool-call:fixture-001:0001",
            tool_name="web.search",
            skill_id=skill.skill_id,
            arguments={"query": "Qdrant filtering"},
        ),
        ToolResult(
            tool_call_id="tool-call:fixture-001:0001",
            status=ToolStatus.SUCCEEDED,
            output={"source_ids": [source.source_id]},
            latency_ms=12,
            cache_status=CacheStatus.MISS,
        ),
        source,
        chunk,
        evidence,
        PocPlan(
            poc_plan_id="poc-plan:qdrant:1",
            candidate_id="candidate:qdrant-client",
            recipe_id="recipe:qdrant-local@1",
            trusted=True,
            checks=("install", "import", "filter"),
        ),
        PocResult(
            poc_result_id="poc-result:qdrant:1",
            poc_plan_id="poc-plan:qdrant:1",
            candidate_id="candidate:qdrant-client",
            status=PocStatus.PASSED,
            resolved_version="1.15.1",
            exit_code=0,
            timed_out=False,
            duration_ms=750,
            artifacts=(
                PocArtifact(
                    artifact_id="poc-artifact:qdrant:stdout",
                    kind="stdout",
                    sha256="c" * 64,
                    size_bytes=42,
                ),
            ),
        ),
        GateDecision(
            gate_id="gate:fixture-001:final",
            outcome=GateOutcome.PASSED,
            checked_constraints=("persistence", "metadata filtering"),
            reasons=("All deterministic checks passed.",),
        ),
    )

    for artifact in artifacts:
        json.dumps(artifact.model_dump(mode="json"))


def test_decision_report_and_manifest_have_honest_terminal_semantics() -> None:
    report = DecisionReport(
        report_id="report:fixture-001",
        run_id="run:fixture-001",
        recommendation="candidate:qdrant-client",
        verdict=Verdict.RECOMMENDED,
        summary="Qdrant satisfies both hard constraints.",
        constraint_results=(
            ConstraintResult(
                candidate_id="candidate:qdrant-client",
                constraint="persistence",
                status=ConstraintStatus.SATISFIED,
                evidence_ids=("evidence:qdrant:persistence",),
            ),
        ),
        limitations=(),
    )
    manifest = RunManifest(
        run_id=report.run_id,
        terminal_status=TerminalStatus.COMPLETED,
        report_id=report.report_id,
        artifact_ids=(report.report_id,),
        limitation_codes=(),
    )

    assert json.loads(manifest.model_dump_json())["terminal_status"] == "completed"
    with pytest.raises(ValidationError, match="completed run cannot have limitations"):
        RunManifest(
            run_id=report.run_id,
            terminal_status=TerminalStatus.COMPLETED,
            report_id=report.report_id,
            artifact_ids=(report.report_id,),
            limitation_codes=("poc_unavailable",),
        )
    with pytest.raises(ValidationError, match="failed run cannot claim a report"):
        RunManifest(
            run_id=report.run_id,
            terminal_status=TerminalStatus.FAILED,
            report_id=report.report_id,
            artifact_ids=(),
            limitation_codes=("unsafe_request",),
        )


def test_failure_contract_covers_every_planned_recovery_branch() -> None:
    expected = {
        "search_timeout",
        "search_rate_limited",
        "page_parsing_failed",
        "malformed_mcp_response",
        "dependency_conflict",
        "version_conflict",
        "poc_timeout",
        "poc_nonzero_exit",
        "report_schema_invalid",
        "report_evidence_invalid",
        "unsafe_request",
        "budget_exhausted",
    }

    assert expected <= {code.value for code in FailureCode}
    failure = Failure(
        failure_id="failure:fixture-001:0001",
        code=FailureCode.SEARCH_TIMEOUT,
        stage=FailureStage.RESEARCH,
        message="Search timed out.",
        recoverable=True,
        recovery_action=RecoveryAction.USE_CACHE_OR_RETRY_SEARCH,
        attempt=1,
    )
    assert json.loads(failure.model_dump_json())["code"] == "search_timeout"
    with pytest.raises(ValidationError, match="non-recoverable failure"):
        Failure(
            failure_id="failure:fixture-001:0002",
            code=FailureCode.UNSAFE_REQUEST,
            stage=FailureStage.POLICY,
            message="Unsafe operation requested.",
            recoverable=False,
            recovery_action=RecoveryAction.RETRY_TOOL_CALL,
            attempt=1,
        )
