"""Fail-closed, deterministic validation of a TechScout recommendation."""

from collections import defaultdict

from pydantic import Field

from paper_agent.techscout.errors import (
    Failure,
    FailureCode,
    FailureStage,
    RecoveryAction,
    StableId,
)
from paper_agent.techscout.models import (
    CandidateEvidence,
    ConstraintStatus,
    DecisionReport,
    GateDecision,
    GateOutcome,
    PocPlan,
    PocResult,
    PocStatus,
    ResearchRequest,
    RunManifest,
    SourceChunk,
    SourceDocument,
    TechScoutModel,
    Verdict,
)


REQUIRED_TERMINAL_ARTIFACTS = frozenset(
    {
        "request.json",
        "research-plan.json",
        "source-snapshots.jsonl",
        "evidence.jsonl",
        "poc-plan.json",
        "poc-results.json",
        "decision-report.json",
        "decision-report.md",
        "traces.jsonl",
        "run_manifest.json",
    }
)


class ValidationInput(TechScoutModel):
    gate_id: StableId
    request: ResearchRequest
    report: DecisionReport
    sources: tuple[SourceDocument, ...]
    chunks: tuple[SourceChunk, ...]
    evidence: tuple[CandidateEvidence, ...]
    poc_plans: tuple[PocPlan, ...]
    poc_results: tuple[PocResult, ...]
    manifest: RunManifest
    trusted_recipe_ids: frozenset[StableId]
    verified_poc_artifact_ids: frozenset[StableId] = Field(default_factory=frozenset)
    terminal_artifact_names: frozenset[str]
    trace_complete: bool
    recovery_count: int = Field(default=0, ge=0, le=1)


class ValidationResult(TechScoutModel):
    decision: GateDecision
    failures: tuple[Failure, ...]


class _Finding:
    def __init__(
        self,
        code: FailureCode,
        message: str,
        *,
        recoverable: bool = False,
        action: RecoveryAction | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.recoverable = recoverable
        self.action = action


class ValidationGate:
    """Apply stable validation checks in a fixed order."""

    def evaluate(self, data: ValidationInput) -> ValidationResult:
        findings: list[_Finding] = []
        candidates = {item.candidate_id: item for item in data.request.candidates}
        sources = {item.source_id: item for item in data.sources}
        chunks = {item.chunk_id: item for item in data.chunks}
        evidence = {item.evidence_id: item for item in data.evidence}
        plans = {item.poc_plan_id: item for item in data.poc_plans}

        self._check_unique_ids(data, findings)
        if data.report.run_id != data.request.run_id:
            findings.append(
                _Finding(FailureCode.REPORT_SCHEMA_INVALID, "report run id does not match request")
            )
        if data.report.recommendation is not None and data.report.recommendation not in candidates:
            findings.append(
                _Finding(FailureCode.REPORT_SCHEMA_INVALID, "report recommends an unknown candidate")
            )

        reported_constraints = {item.constraint for item in data.report.constraint_results}
        missing_constraints = set(data.request.hard_constraints) - reported_constraints
        if missing_constraints:
            findings.append(
                _Finding(
                    FailureCode.REPORT_EVIDENCE_INVALID,
                    "hard constraints missing from report: " + ", ".join(sorted(missing_constraints)),
                    recoverable=data.recovery_count == 0,
                    action=(
                        RecoveryAction.REPAIR_REPORT
                        if data.recovery_count == 0
                        else RecoveryAction.FAIL_SAFELY
                    ),
                )
            )

        for item in data.evidence:
            if item.candidate_id not in candidates:
                findings.append(
                    _Finding(FailureCode.REPORT_EVIDENCE_INVALID, f"{item.evidence_id} has unknown candidate")
                )
            for source_id in item.source_ids:
                source = sources.get(source_id)
                if source is None or source.candidate_id != item.candidate_id:
                    findings.append(
                        _Finding(FailureCode.REPORT_EVIDENCE_INVALID, f"{item.evidence_id} has unresolvable source")
                    )
            for chunk_id in item.chunk_ids:
                chunk = chunks.get(chunk_id)
                if chunk is None or chunk.source_id not in item.source_ids:
                    findings.append(
                        _Finding(FailureCode.REPORT_EVIDENCE_INVALID, f"{item.evidence_id} has unresolvable chunk")
                    )

        for result in data.report.constraint_results:
            if result.candidate_id not in candidates:
                findings.append(
                    _Finding(FailureCode.REPORT_SCHEMA_INVALID, "constraint result has unknown candidate")
                )
            for evidence_id in result.evidence_ids:
                item = evidence.get(evidence_id)
                if (
                    item is None
                    or item.candidate_id != result.candidate_id
                    or item.constraint != result.constraint
                ):
                    findings.append(
                        _Finding(FailureCode.REPORT_EVIDENCE_INVALID, "constraint result has unresolvable evidence")
                    )

        results_by_candidate: dict[StableId, list[PocResult]] = defaultdict(list)
        for result in data.poc_results:
            results_by_candidate[result.candidate_id].append(result)
            plan = plans.get(result.poc_plan_id)
            if plan is None or plan.candidate_id != result.candidate_id:
                findings.append(
                    _Finding(FailureCode.POC_RECIPE_UNSUPPORTED, "PoC result has no matching plan")
                )
                continue
            if plan.trusted and plan.recipe_id not in data.trusted_recipe_ids:
                findings.append(
                    _Finding(FailureCode.POC_RECIPE_UNSUPPORTED, "PoC plan names an unreviewed recipe")
                )
            candidate = candidates.get(result.candidate_id)
            if (
                candidate is not None
                and candidate.resolved_version is not None
                and result.resolved_version is not None
                and candidate.resolved_version != result.resolved_version
            ):
                findings.append(
                    _Finding(FailureCode.VERSION_CONFLICT, "candidate and PoC resolved versions differ")
                )
            missing_artifacts = {
                artifact.artifact_id for artifact in result.artifacts
            } - data.verified_poc_artifact_ids
            if result.status is PocStatus.PASSED and not result.artifacts:
                findings.append(
                    _Finding(FailureCode.POC_ARTIFACT_INVALID, "passed PoC has no integrity artifact")
                )
            elif missing_artifacts:
                findings.append(
                    _Finding(FailureCode.POC_ARTIFACT_INVALID, "PoC artifact integrity was not verified")
                )
            if result.status is PocStatus.TIMED_OUT:
                findings.append(
                    _Finding(
                        FailureCode.POC_TIMEOUT,
                        "PoC timed out",
                        recoverable=data.recovery_count == 0,
                        action=(
                            RecoveryAction.DIAGNOSE_AND_RERUN_POC
                            if data.recovery_count == 0
                            else RecoveryAction.PUBLISH_LIMITED_RESULT
                        ),
                    )
                )
            elif result.status is PocStatus.FAILED:
                code = result.failure_code or FailureCode.POC_NONZERO_EXIT
                action = (
                    RecoveryAction.PIN_VERSION_AND_RERUN_POC
                    if code in {FailureCode.DEPENDENCY_CONFLICT, FailureCode.VERSION_CONFLICT}
                    else RecoveryAction.DIAGNOSE_AND_RERUN_POC
                )
                findings.append(
                    _Finding(
                        code,
                        "PoC exited unsuccessfully",
                        recoverable=data.recovery_count == 0,
                        action=action if data.recovery_count == 0 else RecoveryAction.PUBLISH_LIMITED_RESULT,
                    )
                )

        if data.report.verdict is Verdict.RECOMMENDED:
            recommendation = data.report.recommendation
            recommended_results = results_by_candidate.get(recommendation, [])
            passed = [result for result in recommended_results if result.status is PocStatus.PASSED]
            if not passed or not any(
                plans[result.poc_plan_id].trusted
                and plans[result.poc_plan_id].recipe_id in data.trusted_recipe_ids
                for result in passed
                if result.poc_plan_id in plans
            ):
                findings.append(
                    _Finding(
                        FailureCode.REPORT_EVIDENCE_INVALID,
                        "critical recommendation lacks a passed reviewed PoC",
                        recoverable=data.recovery_count == 0,
                        action=(
                            RecoveryAction.REPAIR_REPORT
                            if data.recovery_count == 0
                            else RecoveryAction.FAIL_SAFELY
                        ),
                    )
                )
            recommended_constraints = {
                item.constraint: item
                for item in data.report.constraint_results
                if item.candidate_id == recommendation
            }
            for constraint in data.request.hard_constraints:
                item = recommended_constraints.get(constraint)
                if (
                    item is None
                    or item.status is not ConstraintStatus.SATISFIED
                    or not item.evidence_ids
                ):
                    findings.append(
                        _Finding(
                            FailureCode.REPORT_EVIDENCE_INVALID,
                            f"recommendation does not prove hard constraint: {constraint}",
                            recoverable=data.recovery_count == 0,
                            action=(
                                RecoveryAction.REPAIR_REPORT
                                if data.recovery_count == 0
                                else RecoveryAction.FAIL_SAFELY
                            ),
                        )
                    )

        if data.manifest.run_id != data.request.run_id or data.manifest.report_id != data.report.report_id:
            findings.append(
                _Finding(FailureCode.REPORT_SCHEMA_INVALID, "terminal manifest does not link request and report")
            )
        if not data.trace_complete:
            findings.append(
                _Finding(FailureCode.REPORT_SCHEMA_INVALID, "terminal trace is incomplete")
            )
        missing_terminal = REQUIRED_TERMINAL_ARTIFACTS - data.terminal_artifact_names
        if missing_terminal:
            findings.append(
                _Finding(
                    FailureCode.REPORT_SCHEMA_INVALID,
                    "terminal artifacts missing: " + ", ".join(sorted(missing_terminal)),
                )
            )

        return self._result(data, findings)

    @staticmethod
    def _check_unique_ids(data: ValidationInput, findings: list[_Finding]) -> None:
        groups = (
            ("source", [item.source_id for item in data.sources]),
            ("chunk", [item.chunk_id for item in data.chunks]),
            ("evidence", [item.evidence_id for item in data.evidence]),
            ("PoC plan", [item.poc_plan_id for item in data.poc_plans]),
            ("PoC result", [item.poc_result_id for item in data.poc_results]),
        )
        for label, identifiers in groups:
            if len(identifiers) != len(set(identifiers)):
                findings.append(
                    _Finding(FailureCode.REPORT_SCHEMA_INVALID, f"duplicate {label} identifier")
                )

    @staticmethod
    def _result(data: ValidationInput, findings: list[_Finding]) -> ValidationResult:
        failures = tuple(
            Failure(
                failure_id=f"failure:{data.gate_id}:validation:{index:03d}",
                code=finding.code,
                stage=_failure_stage(finding.code),
                message=finding.message,
                recoverable=finding.recoverable,
                recovery_action=finding.action,
                attempt=data.recovery_count + 1,
            )
            for index, finding in enumerate(findings, start=1)
        )
        if not failures:
            decision = GateDecision(
                gate_id=data.gate_id,
                outcome=GateOutcome.PASSED,
                checked_constraints=data.request.hard_constraints,
                reasons=("All deterministic validation checks passed.",),
            )
        else:
            recoverable = next((failure for failure in failures if failure.recoverable), None)
            only_limited = all(
                failure.code
                in {
                    FailureCode.POC_RECIPE_UNSUPPORTED,
                    FailureCode.POC_TIMEOUT,
                    FailureCode.POC_NONZERO_EXIT,
                    FailureCode.DEPENDENCY_CONFLICT,
                    FailureCode.VERSION_CONFLICT,
                    FailureCode.TOOL_UNAVAILABLE,
                }
                for failure in failures
            )
            if recoverable is not None:
                outcome = GateOutcome.RECOVER
                action = recoverable.recovery_action
            elif only_limited:
                outcome = GateOutcome.LIMITED
                action = RecoveryAction.PUBLISH_LIMITED_RESULT
            else:
                outcome = GateOutcome.FAILED
                action = RecoveryAction.FAIL_SAFELY
            decision = GateDecision(
                gate_id=data.gate_id,
                outcome=outcome,
                checked_constraints=data.request.hard_constraints,
                reasons=tuple(failure.message for failure in failures),
                failure_ids=tuple(failure.failure_id for failure in failures),
                recovery_action=action,
            )
        return ValidationResult(decision=decision, failures=failures)


def _failure_stage(code: FailureCode) -> FailureStage:
    if code in {
        FailureCode.REPORT_SCHEMA_INVALID,
        FailureCode.REPORT_EVIDENCE_INVALID,
    }:
        return FailureStage.REPORTING
    if code is FailureCode.POC_RECIPE_UNSUPPORTED:
        return FailureStage.POC_PLANNING
    if code in {
        FailureCode.DEPENDENCY_CONFLICT,
        FailureCode.VERSION_CONFLICT,
        FailureCode.POC_TIMEOUT,
        FailureCode.POC_NONZERO_EXIT,
        FailureCode.POC_ARTIFACT_INVALID,
        FailureCode.TOOL_UNAVAILABLE,
    }:
        return FailureStage.POC_EXECUTION
    return FailureStage.VALIDATION
