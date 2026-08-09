from datetime import datetime, timedelta, timezone

import pytest

from paper_agent.techscout.harness import (
    SQLiteCheckpointAdapter,
    StageResult,
    TechScoutHarness,
)
from paper_agent.techscout.models import (
    Candidate,
    EnvironmentSpec,
    GateOutcome,
    ResearchPlan,
    ResearchRequest,
    TerminalStatus,
)
from paper_agent.techscout.errors import (
    Failure,
    FailureCode,
    FailureStage,
    RecoveryAction,
)
from paper_agent.techscout.state import ResearchStage, ResearchState, RunBudget


def _initial_state(*, max_steps: int = 16) -> ResearchState:
    request = ResearchRequest(
        run_id="run:harness-happy",
        question="Choose a local vector store.",
        project_context="A local Python RAG application.",
        environment=EnvironmentSpec(
            python_version="3.11",
            operating_system="linux",
            deployment="local",
        ),
        hard_constraints=("metadata filtering",),
        candidates=(
            Candidate(
                candidate_id="candidate:qdrant-local",
                name="Qdrant Local",
                package_name="qdrant-client",
            ),
        ),
    )
    return ResearchState(
        run_id=request.run_id,
        request=request,
        budget=RunBudget(
            max_steps=max_steps,
            deadline_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        ),
        stage=ResearchStage.NORMALIZE_REQUEST,
        step_count=0,
        tool_call_count=0,
        token_count=0,
        recovery_count=0,
        candidate_ids=("candidate:qdrant-local",),
        source_ids=(),
        evidence_ids=(),
        poc_result_ids=(),
        failures=(),
    )


class DeterministicStageServices:
    def __init__(self) -> None:
        self.calls: list[ResearchStage] = []

    def execute(
        self,
        stage: ResearchStage,
        state: ResearchState,
    ) -> StageResult:
        self.calls.append(stage)
        updates: dict[str, object] = {}
        if stage is ResearchStage.PLAN_RESEARCH:
            updates["plan"] = ResearchPlan(
                plan_id="plan:harness-happy",
                investigation_dimensions=("compatibility",),
                required_capabilities=("official-doc-research",),
                planned_evidence=("official documentation",),
                poc_intent="verify local filtering",
            )
        elif stage is ResearchStage.RESEARCH_CANDIDATES:
            updates.update(
                source_ids=("source:qdrant-docs",),
                evidence_ids=("evidence:qdrant-filtering",),
            )
        elif stage is ResearchStage.EXECUTE_POC:
            updates["poc_result_ids"] = ("poc-result:qdrant-local",)
        elif stage is ResearchStage.VALIDATE:
            updates["gate_outcome"] = GateOutcome.PASSED
        return StageResult(
            state=state.model_copy(update=updates),
            tool_calls=1 if stage is ResearchStage.RESEARCH_CANDIDATES else 0,
            tokens=100,
        )


def test_frozen_request_reaches_completed_terminal_state(tmp_path) -> None:
    services = DeterministicStageServices()
    checkpoint_path = tmp_path / "harness.sqlite3"

    with SQLiteCheckpointAdapter(checkpoint_path) as checkpoints:
        result = TechScoutHarness(services, checkpoints).run(_initial_state())

    assert result.stage is ResearchStage.TERMINAL
    assert result.terminal_status is TerminalStatus.COMPLETED
    assert result.gate_outcome is GateOutcome.PASSED
    assert result.step_count == 9
    assert services.calls == [
        ResearchStage.NORMALIZE_REQUEST,
        ResearchStage.PLAN_RESEARCH,
        ResearchStage.RESEARCH_CANDIDATES,
        ResearchStage.SELECT_CONTEXT,
        ResearchStage.PLAN_POC,
        ResearchStage.EXECUTE_POC,
        ResearchStage.VALIDATE,
        ResearchStage.REVIEW_REPORT,
        ResearchStage.PUBLISH,
    ]


def test_interrupted_run_resumes_without_repeating_completed_stages(tmp_path) -> None:
    services = DeterministicStageServices()
    checkpoint_path = tmp_path / "resume.sqlite3"

    with SQLiteCheckpointAdapter(checkpoint_path) as checkpoints:
        interrupted = TechScoutHarness(services, checkpoints).run(
            _initial_state(),
            interrupt_after=ResearchStage.PLAN_RESEARCH,
        )

    assert interrupted.stage is ResearchStage.PLAN_RESEARCH
    assert services.calls == [
        ResearchStage.NORMALIZE_REQUEST,
        ResearchStage.PLAN_RESEARCH,
    ]

    with SQLiteCheckpointAdapter(checkpoint_path) as checkpoints:
        resumed = TechScoutHarness(services, checkpoints).run(
            run_id="run:harness-happy"
        )

    assert resumed.terminal_status is TerminalStatus.COMPLETED
    assert services.calls.count(ResearchStage.NORMALIZE_REQUEST) == 1
    assert services.calls.count(ResearchStage.PLAN_RESEARCH) == 1
    assert resumed.step_count == 9


class RecoveringStageServices(DeterministicStageServices):
    def execute(
        self,
        stage: ResearchStage,
        state: ResearchState,
    ) -> StageResult:
        if stage is ResearchStage.EXECUTE_POC:
            self.calls.append(stage)
            if self.calls.count(stage) == 1:
                failure = Failure(
                    failure_id="failure:harness-poc:0001",
                    code=FailureCode.POC_NONZERO_EXIT,
                    stage=FailureStage.POC_EXECUTION,
                    message="The deterministic PoC failed.",
                    recoverable=True,
                    recovery_action=RecoveryAction.DIAGNOSE_AND_RERUN_POC,
                    attempt=1,
                )
                return StageResult(
                    state=state.model_copy(update={"failures": (failure,)}),
                    tokens=100,
                )
            return StageResult(
                state=state.model_copy(
                    update={"poc_result_ids": ("poc-result:qdrant-recovered",)}
                ),
                tokens=100,
            )
        if stage is ResearchStage.VALIDATE:
            self.calls.append(stage)
            outcome = (
                GateOutcome.PASSED
                if state.poc_result_ids
                else GateOutcome.RECOVER
            )
            return StageResult(
                state=state.model_copy(update={"gate_outcome": outcome}),
                tokens=100,
            )
        return super().execute(stage, state)


def test_recovery_repeats_only_the_failed_stage_once(tmp_path) -> None:
    services = RecoveringStageServices()

    with SQLiteCheckpointAdapter(tmp_path / "recovery.sqlite3") as checkpoints:
        result = TechScoutHarness(services, checkpoints).run(_initial_state())

    assert result.terminal_status is TerminalStatus.COMPLETED
    assert result.recovery_count == 1
    assert services.calls.count(ResearchStage.EXECUTE_POC) == 2
    assert services.calls.count(ResearchStage.VALIDATE) == 2
    assert services.calls.count(ResearchStage.NORMALIZE_REQUEST) == 1
    assert services.calls.count(ResearchStage.PLAN_RESEARCH) == 1
    assert services.calls.count(ResearchStage.RESEARCH_CANDIDATES) == 1


class ExhaustedRecoveryServices(DeterministicStageServices):
    def execute(
        self,
        stage: ResearchStage,
        state: ResearchState,
    ) -> StageResult:
        if stage is ResearchStage.EXECUTE_POC:
            self.calls.append(stage)
            attempt = self.calls.count(stage)
            failure = Failure(
                failure_id=f"failure:harness-poc:{attempt:04d}",
                code=FailureCode.POC_NONZERO_EXIT,
                stage=FailureStage.POC_EXECUTION,
                message="The deterministic PoC failed.",
                recoverable=True,
                recovery_action=RecoveryAction.DIAGNOSE_AND_RERUN_POC,
                attempt=attempt,
            )
            return StageResult(
                state=state.model_copy(
                    update={"failures": (*state.failures, failure)}
                ),
                tokens=100,
            )
        if stage is ResearchStage.VALIDATE:
            self.calls.append(stage)
            return StageResult(
                state=state.model_copy(update={"gate_outcome": GateOutcome.RECOVER}),
                tokens=100,
            )
        return super().execute(stage, state)


def test_exhausted_recovery_is_limited_and_never_retries_twice(tmp_path) -> None:
    services = ExhaustedRecoveryServices()

    with SQLiteCheckpointAdapter(
        tmp_path / "recovery-exhausted.sqlite3"
    ) as checkpoints:
        result = TechScoutHarness(services, checkpoints).run(_initial_state())

    assert result.terminal_status is TerminalStatus.COMPLETED_WITH_LIMITATIONS
    assert result.recovery_count == 1
    assert services.calls.count(ResearchStage.EXECUTE_POC) == 2
    assert services.calls.count(ResearchStage.VALIDATE) == 2


def test_step_budget_exhaustion_terminates_without_starting_another_stage(
    tmp_path,
) -> None:
    services = DeterministicStageServices()

    with SQLiteCheckpointAdapter(tmp_path / "budget.sqlite3") as checkpoints:
        result = TechScoutHarness(services, checkpoints).run(
            _initial_state(max_steps=2)
        )

    assert result.stage is ResearchStage.TERMINAL
    assert result.terminal_status is TerminalStatus.FAILED
    assert result.gate_outcome is GateOutcome.FAILED
    assert result.step_count == 2
    assert result.failures[-1].code is FailureCode.BUDGET_EXHAUSTED
    assert services.calls == [
        ResearchStage.NORMALIZE_REQUEST,
        ResearchStage.PLAN_RESEARCH,
    ]


class MalformedPlanningServices(DeterministicStageServices):
    def execute(
        self,
        stage: ResearchStage,
        state: ResearchState,
    ) -> StageResult:
        if stage is ResearchStage.PLAN_RESEARCH:
            self.calls.append(stage)
            raise ValueError("malformed structured planning output")
        return super().execute(stage, state)


def test_malformed_stage_output_terminates_as_a_typed_failure(tmp_path) -> None:
    services = MalformedPlanningServices()

    with SQLiteCheckpointAdapter(tmp_path / "malformed.sqlite3") as checkpoints:
        result = TechScoutHarness(services, checkpoints).run(_initial_state())

    assert result.stage is ResearchStage.TERMINAL
    assert result.terminal_status is TerminalStatus.FAILED
    assert result.failures[-1].code is FailureCode.REPORT_SCHEMA_INVALID
    assert result.failures[-1].stage is FailureStage.PLANNING
    assert services.calls == [
        ResearchStage.NORMALIZE_REQUEST,
        ResearchStage.PLAN_RESEARCH,
    ]


class ExcessiveUsageServices(DeterministicStageServices):
    def __init__(self, *, tool_calls: int, tokens: int) -> None:
        super().__init__()
        self._tool_calls = tool_calls
        self._tokens = tokens

    def execute(
        self,
        stage: ResearchStage,
        state: ResearchState,
    ) -> StageResult:
        self.calls.append(stage)
        return StageResult(
            state=state,
            tool_calls=self._tool_calls,
            tokens=self._tokens,
        )


@pytest.mark.parametrize(
    ("tool_calls", "tokens"),
    ((13, 0), (0, 30_001)),
)
def test_stage_usage_cannot_overrun_tool_or_token_budget(
    tmp_path,
    tool_calls: int,
    tokens: int,
) -> None:
    services = ExcessiveUsageServices(tool_calls=tool_calls, tokens=tokens)

    with SQLiteCheckpointAdapter(
        tmp_path / f"usage-{tool_calls}-{tokens}.sqlite3"
    ) as checkpoints:
        result = TechScoutHarness(services, checkpoints).run(_initial_state())

    assert result.terminal_status is TerminalStatus.FAILED
    assert result.failures[-1].code is FailureCode.BUDGET_EXHAUSTED
    assert services.calls == [ResearchStage.NORMALIZE_REQUEST]


def test_exact_tool_budget_is_allowed_when_later_stages_use_no_tools(
    tmp_path,
) -> None:
    services = DeterministicStageServices()
    initial = _initial_state()
    state = initial.model_copy(
        update={
            "budget": initial.budget.model_copy(update={"max_tool_calls": 1})
        }
    )

    with SQLiteCheckpointAdapter(tmp_path / "exact-tools.sqlite3") as checkpoints:
        result = TechScoutHarness(services, checkpoints).run(state)

    assert result.terminal_status is TerminalStatus.COMPLETED
    assert result.tool_call_count == 1


def test_expired_whole_run_deadline_terminates_before_stage_execution(
    tmp_path,
) -> None:
    services = DeterministicStageServices()
    state = _initial_state().model_copy(
        update={
            "budget": _initial_state().budget.model_copy(
                update={"deadline_at": datetime(2026, 8, 9, tzinfo=timezone.utc)}
            )
        }
    )

    with SQLiteCheckpointAdapter(tmp_path / "deadline.sqlite3") as checkpoints:
        result = TechScoutHarness(
            services,
            checkpoints,
            now=lambda: datetime(2026, 8, 10, tzinfo=timezone.utc),
        ).run(state)

    assert result.terminal_status is TerminalStatus.FAILED
    assert result.failures[-1].code is FailureCode.DEADLINE_EXCEEDED
    assert result.step_count == 0
    assert services.calls == []
