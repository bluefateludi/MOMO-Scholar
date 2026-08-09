from datetime import datetime, timezone

from paper_agent.techscout.errors import FailureCode, FailureStage
from paper_agent.techscout.models import (
    Candidate,
    CandidateEvidence,
    ConstraintResult,
    ConstraintStatus,
    DecisionReport,
    EnvironmentSpec,
    EvidenceKind,
    GateOutcome,
    PocArtifact,
    PocPlan,
    PocResult,
    PocStatus,
    ResearchRequest,
    RunManifest,
    SourceChunk,
    SourceDocument,
    SourceType,
    TerminalStatus,
    Verdict,
)
from paper_agent.techscout.validation.gate import (
    REQUIRED_TERMINAL_ARTIFACTS,
    ValidationGate,
    ValidationInput,
)


def _candidate() -> Candidate:
    return Candidate(
        candidate_id="candidate:qdrant-client",
        name="Qdrant Local",
        package_name="qdrant-client",
        resolved_version="1.15.1",
    )


def _request(candidate: Candidate | None = None) -> ResearchRequest:
    selected = candidate or _candidate()
    return ResearchRequest(
        run_id="run:validation-001",
        question="Choose a local vector store.",
        project_context="A local Python RAG service.",
        environment=EnvironmentSpec(
            python_version="3.11",
            operating_system="linux",
            deployment="local-container",
        ),
        hard_constraints=("persistence", "metadata filtering"),
        candidates=(selected,),
    )


def _evidence(candidate: Candidate):
    sources = []
    chunks = []
    evidence = []
    for ordinal, constraint in enumerate(("persistence", "metadata filtering"), start=1):
        source = SourceDocument(
            source_id=f"source:qdrant-docs:{ordinal}",
            candidate_id=candidate.candidate_id,
            source_type=SourceType.OFFICIAL_DOCUMENTATION,
            url=f"https://qdrant.tech/documentation/{ordinal}",
            title=f"Qdrant contract {ordinal}",
            version="1.15.1",
            as_of=datetime(2026, 8, 9, tzinfo=timezone.utc),
            content_sha256=str(ordinal) * 64,
        )
        chunk = SourceChunk(
            chunk_id=f"chunk:qdrant-docs:{ordinal}",
            source_id=source.source_id,
            text=f"Qdrant supports {constraint}.",
            ordinal=ordinal,
            content_sha256=str(ordinal + 2) * 64,
        )
        item = CandidateEvidence(
            evidence_id=f"evidence:qdrant:{ordinal}",
            candidate_id=candidate.candidate_id,
            constraint=constraint,
            claim=f"Qdrant supports {constraint}.",
            source_ids=(source.source_id,),
            chunk_ids=(chunk.chunk_id,),
            kind=EvidenceKind.RETRIEVED_FACT,
        )
        sources.append(source)
        chunks.append(chunk)
        evidence.append(item)
    return tuple(sources), tuple(chunks), tuple(evidence)


def _valid_input() -> ValidationInput:
    candidate = _candidate()
    request = _request(candidate)
    sources, chunks, evidence = _evidence(candidate)
    plan = PocPlan(
        poc_plan_id="poc-plan:qdrant:1",
        candidate_id=candidate.candidate_id,
        recipe_id="recipe:qdrant-local@1",
        trusted=True,
        checks=("import", "persistence", "query", "filter"),
    )
    result = PocResult(
        poc_result_id="poc-result:qdrant:1",
        poc_plan_id=plan.poc_plan_id,
        candidate_id=candidate.candidate_id,
        status=PocStatus.PASSED,
        resolved_version="1.15.1",
        exit_code=0,
        timed_out=False,
        duration_ms=50,
        artifacts=(
            PocArtifact(
                artifact_id="poc-artifact:qdrant:stdout",
                kind="stdout",
                sha256="f" * 64,
                size_bytes=50,
            ),
        ),
    )
    report = DecisionReport(
        report_id="report:validation-001",
        run_id=request.run_id,
        recommendation=candidate.candidate_id,
        verdict=Verdict.RECOMMENDED,
        summary="Qdrant satisfies both constraints.",
        constraint_results=tuple(
            ConstraintResult(
                candidate_id=candidate.candidate_id,
                constraint=item.constraint,
                status=ConstraintStatus.SATISFIED,
                evidence_ids=(item.evidence_id,),
            )
            for item in evidence
        ),
        limitations=(),
    )
    manifest = RunManifest(
        run_id=request.run_id,
        terminal_status=TerminalStatus.COMPLETED,
        report_id=report.report_id,
        artifact_ids=(report.report_id,),
        limitation_codes=(),
    )
    return ValidationInput(
        gate_id="gate:validation-001:final",
        request=request,
        report=report,
        sources=sources,
        chunks=chunks,
        evidence=evidence,
        poc_plans=(plan,),
        poc_results=(result,),
        manifest=manifest,
        trusted_recipe_ids=frozenset({"recipe:qdrant-local@1", "recipe:chroma-local@1"}),
        verified_poc_artifact_ids=frozenset({"poc-artifact:qdrant:stdout"}),
        terminal_artifact_names=REQUIRED_TERMINAL_ARTIFACTS,
        trace_complete=True,
    )


def test_validation_gate_passes_complete_supported_recommendation() -> None:
    result = ValidationGate().evaluate(_valid_input())

    assert result.decision.outcome is GateOutcome.PASSED
    assert result.failures == ()
    assert result.decision.checked_constraints == ("persistence", "metadata filtering")


def test_validation_gate_repairs_only_report_when_constraint_evidence_is_missing() -> None:
    data = _valid_input()
    report = data.report.model_copy(
        update={"constraint_results": data.report.constraint_results[:1]}
    )

    result = ValidationGate().evaluate(data.model_copy(update={"report": report}))

    assert result.decision.outcome is GateOutcome.RECOVER
    assert result.decision.recovery_action.value == "repair_report"
    assert any(failure.code is FailureCode.REPORT_EVIDENCE_INVALID for failure in result.failures)
    assert all(failure.stage is FailureStage.REPORTING for failure in result.failures)


def test_validation_gate_rejects_unsupported_critical_recommendation() -> None:
    data = _valid_input()
    untrusted = data.poc_plans[0].model_copy(
        update={"recipe_id": "recipe:unknown@1"}
    )

    result = ValidationGate().evaluate(
        data.model_copy(update={"poc_plans": (untrusted,)})
    )

    assert result.decision.outcome is GateOutcome.RECOVER
    codes = {failure.code for failure in result.failures}
    assert FailureCode.POC_RECIPE_UNSUPPORTED in codes
    assert FailureCode.REPORT_EVIDENCE_INVALID in codes


def test_validation_gate_requests_one_local_poc_recovery_for_dependency_failure() -> None:
    data = _valid_input()
    failed = data.poc_results[0].model_copy(
        update={
            "status": PocStatus.FAILED,
            "exit_code": 1,
            "failure_code": FailureCode.DEPENDENCY_CONFLICT,
        }
    )

    first = ValidationGate().evaluate(
        data.model_copy(update={"poc_results": (failed,)})
    )
    exhausted = ValidationGate().evaluate(
        data.model_copy(update={"poc_results": (failed,), "recovery_count": 1})
    )

    assert first.decision.outcome is GateOutcome.RECOVER
    assert first.decision.recovery_action.value == "pin_version_and_rerun_poc"
    assert first.failures[0].stage is FailureStage.POC_EXECUTION
    assert exhausted.decision.outcome is GateOutcome.FAILED
    assert all(not failure.recoverable for failure in exhausted.failures)


def test_validation_gate_accepts_honest_research_only_no_safe_winner() -> None:
    candidate = Candidate(
        candidate_id="candidate:pgvector",
        name="pgvector",
        package_name="pgvector",
    )
    request = ResearchRequest(
        run_id="run:research-only-001",
        question="Choose a locally verified vector store.",
        project_context="Local verification is mandatory.",
        environment=EnvironmentSpec(
            python_version="3.11",
            operating_system="linux",
            deployment="local-container",
        ),
        hard_constraints=("local verification",),
        candidates=(candidate,),
    )
    source = SourceDocument(
        source_id="source:pgvector:official",
        candidate_id=candidate.candidate_id,
        source_type=SourceType.OFFICIAL_DOCUMENTATION,
        url="https://github.com/pgvector/pgvector",
        title="pgvector",
        as_of=datetime(2026, 8, 9, tzinfo=timezone.utc),
        content_sha256="a" * 64,
    )
    chunk = SourceChunk(
        chunk_id="chunk:pgvector:official:1",
        source_id=source.source_id,
        text="pgvector requires PostgreSQL.",
        ordinal=0,
        content_sha256="b" * 64,
    )
    evidence = CandidateEvidence(
        evidence_id="evidence:pgvector:verification",
        candidate_id=candidate.candidate_id,
        constraint="local verification",
        claim="No reviewed PostgreSQL fixture is available.",
        source_ids=(source.source_id,),
        chunk_ids=(chunk.chunk_id,),
        kind=EvidenceKind.RETRIEVED_FACT,
    )
    report = DecisionReport(
        report_id="report:research-only-001",
        run_id=request.run_id,
        verdict=Verdict.INSUFFICIENT_EVIDENCE,
        summary="No safe winner because local verification is unavailable.",
        constraint_results=(
            ConstraintResult(
                candidate_id=candidate.candidate_id,
                constraint="local verification",
                status=ConstraintStatus.UNKNOWN,
                evidence_ids=(evidence.evidence_id,),
                reason="pgvector has no reviewed PostgreSQL fixture.",
            ),
        ),
        limitations=("pgvector remains research-only",),
    )
    manifest = RunManifest(
        run_id=request.run_id,
        terminal_status=TerminalStatus.COMPLETED_WITH_LIMITATIONS,
        report_id=report.report_id,
        artifact_ids=(report.report_id,),
        limitation_codes=("poc_recipe_unsupported",),
    )
    data = ValidationInput(
        gate_id="gate:research-only-001:final",
        request=request,
        report=report,
        sources=(source,),
        chunks=(chunk,),
        evidence=(evidence,),
        poc_plans=(
            PocPlan(
                poc_plan_id="poc-plan:pgvector:1",
                candidate_id=candidate.candidate_id,
                trusted=False,
                checks=(),
            ),
        ),
        poc_results=(),
        manifest=manifest,
        trusted_recipe_ids=frozenset({"recipe:qdrant-local@1", "recipe:chroma-local@1"}),
        terminal_artifact_names=REQUIRED_TERMINAL_ARTIFACTS,
        trace_complete=True,
    )

    result = ValidationGate().evaluate(data)

    assert result.decision.outcome is GateOutcome.PASSED
    assert result.failures == ()
