from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from paper_agent.techscout.errors import Failure, FailureCode, FailureStage, RecoveryAction
from paper_agent.techscout.eval.contracts import (
    EvaluationCase,
    FaultExecutionResult,
    HarnessVariant,
    RetrievalExecutionResult,
    TaskExecutionResult,
)
from paper_agent.techscout.eval.faults import DeterministicFaultInjector, InjectedFault
from paper_agent.techscout.harness import (
    SQLiteCheckpointAdapter,
    StageArtifacts,
    StageDeadline,
    StageResult,
    TechScoutHarness,
)
from paper_agent.techscout.models import (
    CacheStatus,
    Candidate,
    ConstraintResult,
    ConstraintStatus,
    DecisionReport,
    EnvironmentSpec,
    GateOutcome,
    ResearchPlan,
    ResearchRequest,
    RunManifest,
    TerminalStatus,
    ToolCall,
    ToolResult,
    ToolStatus,
    Verdict,
)
from paper_agent.techscout.observability import TechScoutTraceRecorder, TraceEventName
from paper_agent.techscout.observability.adapters import (
    TracingSkillRouter,
    TracingStageServices,
    TracingToolRuntime,
)
from paper_agent.techscout.runtime_skills import fixed_skill_registry
from paper_agent.techscout.state import ResearchStage, ResearchState, RunBudget


_NOW = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)


class _SuccessfulSearchRuntime:
    async def discover_tools(self, skill_id: str | None = None) -> tuple[str, ...]:
        return ("web.search",)

    async def invoke(self, call: ToolCall) -> ToolResult:
        return ToolResult(
            tool_call_id=call.tool_call_id,
            status=ToolStatus.SUCCEEDED,
            latency_ms=1,
            cache_status=CacheStatus.HIT,
        )


class _SmokeStageServices:
    def __init__(
        self,
        case: EvaluationCase,
        source: dict[str, object],
        trace: TechScoutTraceRecorder,
        *,
        load_stage_skill: bool = True,
    ) -> None:
        self._case = case
        self._source = source
        self._trace = trace
        self._load_stage_skill = load_stage_skill
        self._poc_attempts = 0

    def execute(
        self,
        stage: ResearchStage,
        state: ResearchState,
        artifacts: StageArtifacts,
        deadline: StageDeadline,
    ) -> StageResult:
        updates: dict[str, object] = {}
        if stage is ResearchStage.PLAN_RESEARCH:
            updates["plan"] = ResearchPlan(
                plan_id=f"plan:{self._case.case_id}",
                investigation_dimensions=("compatibility", "verification"),
                required_capabilities=("official-doc-research",),
                planned_evidence=("frozen official snapshot",),
                poc_intent="run the allowlisted fixture smoke when supported",
            )
        elif stage is ResearchStage.RESEARCH_CANDIDATES:
            skill_id = "skill:baseline-core"
            if self._load_stage_skill:
                selection = TracingSkillRouter(fixed_skill_registry(), self._trace).route(
                    "official-doc-research",
                    stage,
                    selection_id=f"selection:{self._case.case_id}",
                    reason="frozen_official_evidence",
                )
                skill_id = selection.skill_id
            asyncio.run(
                TracingToolRuntime(_SuccessfulSearchRuntime(), self._trace).invoke(
                    ToolCall(
                        tool_call_id=f"tool-call:{self._case.case_id}",
                        tool_name="web.search",
                        skill_id=skill_id,
                        arguments={
                            "query": "local vector store compatibility",
                            "candidate_id": state.candidate_ids[0],
                            "domains": ["example.invalid"],
                            "max_results": 1,
                        },
                    )
                )
            )
            updates.update(
                source_ids=(f"source:{self._case.case_id}",),
                evidence_ids=(f"evidence:{self._case.case_id}",),
            )
        elif stage is ResearchStage.EXECUTE_POC and self._case.supports_poc:
            self._poc_attempts += 1
            if self._source.get("scenario") == "bounded_failure_recovery" and self._poc_attempts == 1:
                failure = Failure(
                    failure_id=f"failure:{self._case.case_id}:dependency",
                    code=FailureCode.DEPENDENCY_CONFLICT,
                    stage=FailureStage.POC_EXECUTION,
                    message="Frozen dependency conflict.",
                    recoverable=True,
                    recovery_action=RecoveryAction.PIN_VERSION_AND_RERUN_POC,
                    attempt=1,
                )
                updates["failures"] = (*state.failures, failure)
            else:
                updates["poc_result_ids"] = (f"poc-result:{self._case.case_id}",)
        elif stage is ResearchStage.VALIDATE:
            if self._source.get("scenario") == "bounded_failure_recovery" and state.recovery_count == 0:
                updates["gate_outcome"] = GateOutcome.RECOVER
            elif self._source.get("scenario") == "no_safe_winner_research_only":
                updates["gate_outcome"] = GateOutcome.LIMITED
            else:
                updates["gate_outcome"] = GateOutcome.PASSED
        elif stage is ResearchStage.REVIEW_REPORT:
            limited = state.gate_outcome is GateOutcome.LIMITED
            status = ConstraintStatus.UNKNOWN if limited else ConstraintStatus.SATISFIED
            report = DecisionReport(
                report_id=f"report:{self._case.case_id}",
                run_id=state.run_id,
                recommendation=None if limited else state.candidate_ids[0],
                verdict=Verdict.INSUFFICIENT_EVIDENCE if limited else Verdict.RECOMMENDED,
                summary="No safe winner." if limited else "Frozen smoke contract passed.",
                constraint_results=tuple(
                    ConstraintResult(
                        candidate_id=state.candidate_ids[0],
                        constraint=constraint,
                        status=status,
                        evidence_ids=(f"evidence:{self._case.case_id}",),
                        reason="Local verification is unavailable." if limited else None,
                    )
                    for constraint in state.request.hard_constraints
                ),
                limitations=("research_only",) if limited else (),
            )
            return StageResult(state=state, artifacts=StageArtifacts(report=report), tokens=100)
        elif stage is ResearchStage.PUBLISH:
            assert artifacts.report is not None
            limited = state.gate_outcome is GateOutcome.LIMITED
            manifest = RunManifest(
                run_id=state.run_id,
                terminal_status=(
                    TerminalStatus.COMPLETED_WITH_LIMITATIONS if limited else TerminalStatus.COMPLETED
                ),
                report_id=artifacts.report.report_id,
                artifact_ids=(artifacts.report.report_id,),
                limitation_codes=("research_only",) if limited else (),
            )
            return StageResult(state=state, artifacts=StageArtifacts(manifest=manifest), tokens=100)
        return StageResult(
            state=state.model_copy(update=updates),
            tool_calls=1 if stage is ResearchStage.RESEARCH_CANDIDATES else 0,
            tokens=100,
        )


def _initial_state(case: EvaluationCase, source: dict[str, object]) -> ResearchState:
    request_data = source["request"]
    assert isinstance(request_data, dict)
    candidates = request_data["candidates"]
    assert isinstance(candidates, list) and candidates
    first = candidates[0]
    assert isinstance(first, dict)
    request = ResearchRequest(
        run_id=f"run:{case.case_id}",
        question=str(request_data["question"]),
        project_context=str(request_data["project_context"]),
        environment=EnvironmentSpec(
            python_version="3.11",
            operating_system="linux-container",
            deployment="single-node-local",
        ),
        hard_constraints=tuple(str(item) for item in request_data["hard_constraints"]),
        candidates=(
            Candidate(
                candidate_id=f"candidate:{first['candidate_id']}",
                name=str(first["display_name"]),
            ),
        ),
    )
    return ResearchState(
        run_id=request.run_id,
        request=request,
        budget=RunBudget(deadline_at=_NOW + timedelta(seconds=120)),
        stage=ResearchStage.NORMALIZE_REQUEST,
        step_count=0,
        tool_call_count=0,
        token_count=0,
        recovery_count=0,
        candidate_ids=tuple(candidate.candidate_id for candidate in request.candidates),
        source_ids=(),
        evidence_ids=(),
        poc_result_ids=(),
        failures=(),
    )


def _sha256_model(value: object) -> str:
    payload = value.model_dump(mode="json")
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class FrozenSmokeExecutor:
    """Seconds-scale deterministic adapter that crosses the real Harness seams."""

    version = "frozen-synthetic-v1"

    def __init__(self, checkpoint_root: Path) -> None:
        self._checkpoint_root = checkpoint_root

    def cancel(self, case_id: str) -> None:
        # Smoke stages are local and bounded; no blocking external operation survives.
        return None

    def run_e2e(
        self,
        case: EvaluationCase,
        variant: HarnessVariant,
        *,
        timeout_seconds: int,
        trace: TechScoutTraceRecorder,
    ) -> TaskExecutionResult:
        source = json.loads(Path(case.source_fixture).read_text(encoding="utf-8"))
        if source.get("task_id") != case.case_id or timeout_seconds > 120:
            raise ValueError("smoke fixture identity or timeout is invalid")
        self._checkpoint_root.mkdir(parents=True, exist_ok=True)
        checkpoint_path = self._checkpoint_root / f"{case.case_id}-{variant.value}.sqlite3"
        services = TracingStageServices(
            _SmokeStageServices(
                case,
                source,
                trace,
                load_stage_skill=variant is HarnessVariant.V1,
            ),
            trace,
        )
        with SQLiteCheckpointAdapter(checkpoint_path) as checkpoints:
            result = TechScoutHarness(services, checkpoints, now=lambda: _NOW).run(
                _initial_state(case, source)
            )
        assert result.report is not None and result.manifest is not None
        terminal_status = result.manifest.terminal_status.value
        trace.record_terminal(
            terminal_status=terminal_status,
            gate_outcome=result.state.gate_outcome.value,
            latency_ms=0,
            prompt_tokens=result.state.token_count,
            completion_tokens=0,
            retry_count=result.state.recovery_count,
            recovery_count=result.state.recovery_count,
            report_sha256=_sha256_model(result.report),
            manifest_sha256=_sha256_model(result.manifest),
            context={"case_id": case.case_id, "harness_variant": variant.value},
        )
        constraint_names = {item.constraint for item in result.report.constraint_results}
        return TaskExecutionResult(
            terminal_status=terminal_status,
            report_schema_valid=True,
            hard_constraints_addressed=set(result.state.request.hard_constraints) <= constraint_names,
            required_evidence_available=bool(result.state.source_ids),
            poc_result_present=bool(result.state.poc_result_ids),
            validation_gate_passed=result.state.gate_outcome in {GateOutcome.PASSED, GateOutcome.LIMITED},
            artifacts_and_trace_complete=True,
            prompt_tokens=result.state.token_count,
            completion_tokens=0,
            tool_call_schema_valid_count=result.state.tool_call_count,
            tool_call_execution_success_count=result.state.tool_call_count,
            tool_call_count=result.state.tool_call_count,
            recovery_attempted=result.state.recovery_count == 1,
            recovery_succeeded=True if result.state.recovery_count == 1 else None,
            recovery_stages=result.state.recovery_count,
            retry_count=result.state.recovery_count,
        )

    def run_retrieval(self, case, *, timeout_seconds, trace) -> RetrievalExecutionResult:
        source = json.loads(Path(case.source_fixture).read_text(encoding="utf-8"))
        record = source["retrieval_observations"][case.case_id]
        return RetrievalExecutionResult(
            retrieved_source_ids=tuple(record["retrieved_source_ids"]),
            relevant_source_ids=tuple(record["relevant_source_ids"]),
            expected_version_match=record["expected_version_match"],
            actual_version_match=record["actual_version_match"],
        )

    def run_fault(
        self,
        case,
        injector: DeterministicFaultInjector,
        *,
        timeout_seconds,
        trace,
    ) -> FaultExecutionResult:
        source = json.loads(Path(case.source_fixture).read_text(encoding="utf-8"))
        record = source["fault_observations"][case.case_id]
        try:
            injector.check(str(record["stage"]))
        except InjectedFault as error:
            recovery_succeeded = error.plan.failure_code in {
                "dependency_conflict",
                "tool_timeout",
                "cache_corruption",
                "checkpoint_interruption",
                "schema_repairable",
                "transient_tool_failure",
            }
            trace.record(
                TraceEventName.ERROR_CLASSIFIED,
                status="error",
                attributes={
                    "case_id": case.case_id,
                    "failure_id": f"failure:{case.case_id}",
                    "failure_code": error.plan.failure_code,
                    "failure_stage": str(record["stage"]),
                    "recoverable": recovery_succeeded,
                    "attempt": 1,
                },
            )
            return FaultExecutionResult(
                injected_failure_code=error.plan.failure_code,
                recovery_succeeded=recovery_succeeded,
                recovery_stages=1,
                retry_count=int(recovery_succeeded),
            )
        raise ValueError("frozen fault observation did not trigger the declared plan")
