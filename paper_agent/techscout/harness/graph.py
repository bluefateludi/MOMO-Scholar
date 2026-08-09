from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph

from paper_agent.techscout.errors import Failure, FailureCode, FailureStage
from paper_agent.techscout.harness.checkpoint import SQLiteCheckpointAdapter
from paper_agent.techscout.harness.stages import (
    HarnessRunResult,
    StageArtifacts,
    StageDeadline,
    StageDeadlineExceeded,
    StageResult,
    StageServices,
)
from paper_agent.techscout.models import (
    DecisionReport,
    GateOutcome,
    RunManifest,
    TerminalStatus,
)
from paper_agent.techscout.state import ResearchStage, ResearchState


_LINEAR_STAGES = (
    ResearchStage.NORMALIZE_REQUEST,
    ResearchStage.PLAN_RESEARCH,
    ResearchStage.RESEARCH_CANDIDATES,
    ResearchStage.SELECT_CONTEXT,
    ResearchStage.PLAN_POC,
    ResearchStage.EXECUTE_POC,
)

_RECOVERY_STAGES = {
    FailureStage.INTAKE: ResearchStage.NORMALIZE_REQUEST,
    FailureStage.PLANNING: ResearchStage.PLAN_RESEARCH,
    FailureStage.RESEARCH: ResearchStage.RESEARCH_CANDIDATES,
    FailureStage.CONTEXT: ResearchStage.SELECT_CONTEXT,
    FailureStage.POC_PLANNING: ResearchStage.PLAN_POC,
    FailureStage.POC_EXECUTION: ResearchStage.EXECUTE_POC,
    FailureStage.VALIDATION: ResearchStage.VALIDATE,
    FailureStage.REPORTING: ResearchStage.REVIEW_REPORT,
    FailureStage.PUBLISHING: ResearchStage.PUBLISH,
}

_FAILURE_STAGES = {
    research_stage: failure_stage
    for failure_stage, research_stage in _RECOVERY_STAGES.items()
}


class _GraphState(TypedDict):
    research_state_json: str
    report_json: NotRequired[str | None]
    manifest_json: NotRequired[str | None]


class TechScoutHarness:
    """Thin, bounded graph shell around injected TechScout stage services."""

    def __init__(
        self,
        services: StageServices,
        checkpoints: SQLiteCheckpointAdapter,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._services = services
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._graph = self._build_graph(checkpoints)

    def run(
        self,
        state: ResearchState | None = None,
        *,
        run_id: str | None = None,
        interrupt_after: ResearchStage | None = None,
    ) -> HarnessRunResult:
        if state is None and run_id is None:
            raise ValueError("run_id is required when resuming without input state")
        if state is not None and run_id not in {None, state.run_id}:
            raise ValueError("run_id must match the input state")
        thread_id = state.run_id if state is not None else run_id
        config = {"configurable": {"thread_id": thread_id}}
        interrupts = [interrupt_after.value] if interrupt_after is not None else None
        graph_input = (
            {
                "research_state_json": state.model_dump_json(),
                "report_json": None,
                "manifest_json": None,
            }
            if state is not None
            else None
        )
        result = self._graph.invoke(
            graph_input,
            config=config,
            interrupt_after=interrupts,
        )
        artifacts = self._decode_artifacts(result)
        return HarnessRunResult(
            state=ResearchState.model_validate_json(result["research_state_json"]),
            report=artifacts.report,
            manifest=artifacts.manifest,
        )

    def _build_graph(self, checkpoints: SQLiteCheckpointAdapter) -> Any:
        builder = StateGraph(_GraphState)
        for stage in (*_LINEAR_STAGES, ResearchStage.VALIDATE):
            builder.add_node(stage.value, self._stage_node(stage))
        builder.add_node(
            ResearchStage.RECOVER_ONCE.value,
            self._recovery_node,
        )
        builder.add_node(
            ResearchStage.REVIEW_REPORT.value,
            self._stage_node(ResearchStage.REVIEW_REPORT),
        )
        builder.add_node(
            ResearchStage.PUBLISH.value,
            self._stage_node(ResearchStage.PUBLISH),
        )
        builder.add_node(ResearchStage.TERMINAL.value, self._terminal_node)

        builder.add_edge(START, ResearchStage.NORMALIZE_REQUEST.value)
        for current, following in zip(_LINEAR_STAGES, _LINEAR_STAGES[1:]):
            builder.add_conditional_edges(
                current.value,
                self._route_next,
                {"next": following.value, "end": END},
            )
        builder.add_conditional_edges(
            ResearchStage.EXECUTE_POC.value,
            self._route_next,
            {"next": ResearchStage.VALIDATE.value, "end": END},
        )
        builder.add_conditional_edges(
            ResearchStage.VALIDATE.value,
            self._route_after_validation,
            {
                "recover": ResearchStage.RECOVER_ONCE.value,
                "review": ResearchStage.REVIEW_REPORT.value,
                "terminal": ResearchStage.TERMINAL.value,
                "end": END,
            },
        )
        builder.add_conditional_edges(
            ResearchStage.RECOVER_ONCE.value,
            self._route_next,
            {"next": ResearchStage.VALIDATE.value, "end": END},
        )
        builder.add_conditional_edges(
            ResearchStage.REVIEW_REPORT.value,
            self._route_next,
            {"next": ResearchStage.PUBLISH.value, "end": END},
        )
        builder.add_conditional_edges(
            ResearchStage.PUBLISH.value,
            self._route_terminal,
            {"terminal": ResearchStage.TERMINAL.value, "end": END},
        )
        builder.add_edge(ResearchStage.TERMINAL.value, END)
        return builder.compile(checkpointer=checkpoints.saver)

    def _stage_node(
        self,
        stage: ResearchStage,
    ) -> Callable[[_GraphState], _GraphState]:
        def execute(raw_state: _GraphState) -> _GraphState:
            state = ResearchState.model_validate_json(
                raw_state["research_state_json"]
            )
            budget_code = self._budget_code(state)
            if budget_code is not None:
                terminal = self._terminalize_budget(state, budget_code)
                return {"research_state_json": terminal.model_dump_json()}
            artifacts = self._decode_artifacts(raw_state)
            stage_state = state.model_copy(update={"stage": stage})
            try:
                result = self._execute_stage(stage, stage_state, artifacts)
                updated = self._apply_result(state, stage, result)
            except StageDeadlineExceeded:
                terminal = self._terminalize_budget(
                    state,
                    FailureCode.DEADLINE_EXCEEDED,
                )
                return self._encode_graph_state(terminal, artifacts)
            except ValueError:
                terminal = self._terminalize_malformed_output(state, stage)
                return {"research_state_json": terminal.model_dump_json()}
            budget_code = self._budget_code(
                updated,
                require_next_step=stage is not ResearchStage.PUBLISH,
            )
            if (
                updated.stage is not ResearchStage.TERMINAL
                and budget_code is not None
            ):
                updated = self._terminalize_budget(updated, budget_code)
            merged_artifacts = self._merge_artifacts(artifacts, result.artifacts)
            return self._encode_graph_state(updated, merged_artifacts)

        return execute

    def _apply_result(
        self,
        previous: ResearchState,
        stage: ResearchStage,
        result: StageResult,
    ) -> ResearchState:
        if result.state.run_id != previous.run_id:
            raise ValueError("stage service cannot change the run identifier")
        step_count = previous.step_count + 1
        tool_call_count = previous.tool_call_count + result.tool_calls
        token_count = previous.token_count + result.tokens
        if (
            step_count > previous.budget.max_steps
            or tool_call_count > previous.budget.max_tool_calls
            or token_count > previous.budget.max_tokens
        ):
            attempted = previous.model_copy(
                update={"step_count": min(step_count, previous.budget.max_steps)}
            )
            return self._terminalize_budget(
                attempted,
                FailureCode.BUDGET_EXHAUSTED,
            )
        return result.state.model_copy(
            update={
                "run_id": previous.run_id,
                "request": previous.request,
                "budget": previous.budget,
                "stage": stage,
                "step_count": step_count,
                "tool_call_count": tool_call_count,
                "token_count": token_count,
                "recovery_count": previous.recovery_count,
                "terminal_status": None,
            }
        )

    @staticmethod
    def _route_after_validation(raw_state: _GraphState) -> str:
        state = ResearchState.model_validate_json(raw_state["research_state_json"])
        if state.stage is ResearchStage.TERMINAL:
            return "end"
        if state.gate_outcome is GateOutcome.FAILED:
            return "terminal"
        if (
            state.gate_outcome is GateOutcome.RECOVER
            and state.recovery_count < state.budget.recovery_limit
            and TechScoutHarness._recovery_stage(state) is not None
        ):
            return "recover"
        return "review"

    @staticmethod
    def _route_next(raw_state: _GraphState) -> str:
        state = ResearchState.model_validate_json(raw_state["research_state_json"])
        return "end" if state.stage is ResearchStage.TERMINAL else "next"

    @staticmethod
    def _route_terminal(raw_state: _GraphState) -> str:
        state = ResearchState.model_validate_json(raw_state["research_state_json"])
        return "end" if state.stage is ResearchStage.TERMINAL else "terminal"

    def _recovery_node(self, raw_state: _GraphState) -> _GraphState:
        state = ResearchState.model_validate_json(raw_state["research_state_json"])
        artifacts = self._decode_artifacts(raw_state)
        failed_stage = self._recovery_stage(state)
        if failed_stage is None:
            raise ValueError("recoverable gate requires a typed failed stage")
        retry_state = state.model_copy(update={"stage": failed_stage})
        try:
            result = self._execute_stage(failed_stage, retry_state, artifacts)
            updated = self._apply_result(
                state,
                ResearchStage.RECOVER_ONCE,
                result,
            )
        except StageDeadlineExceeded:
            terminal = self._terminalize_budget(
                state,
                FailureCode.DEADLINE_EXCEEDED,
            ).model_copy(update={"recovery_count": state.recovery_count + 1})
            return self._encode_graph_state(terminal, artifacts)
        except ValueError:
            terminal = self._terminalize_malformed_output(state, failed_stage)
            terminal = terminal.model_copy(
                update={"recovery_count": state.recovery_count + 1}
            )
            return self._encode_graph_state(terminal, artifacts)
        if updated.stage is ResearchStage.TERMINAL:
            return self._encode_graph_state(updated, artifacts)
        updated = updated.model_copy(
            update={"recovery_count": state.recovery_count + 1}
        )
        budget_code = self._budget_code(updated)
        if budget_code is not None:
            updated = self._terminalize_budget(updated, budget_code)
        merged_artifacts = self._merge_artifacts(artifacts, result.artifacts)
        return self._encode_graph_state(updated, merged_artifacts)

    @staticmethod
    def _recovery_stage(state: ResearchState) -> ResearchStage | None:
        for failure in reversed(state.failures):
            if failure.recoverable:
                return _RECOVERY_STAGES.get(failure.stage)
        return None

    def _budget_code(
        self,
        state: ResearchState,
        *,
        require_next_step: bool = True,
    ) -> FailureCode | None:
        if self._now() >= state.budget.deadline_at:
            return FailureCode.DEADLINE_EXCEEDED
        if require_next_step and state.step_count >= state.budget.max_steps:
            return FailureCode.BUDGET_EXHAUSTED
        return None

    def _execute_stage(
        self,
        stage: ResearchStage,
        state: ResearchState,
        artifacts: StageArtifacts,
    ) -> StageResult:
        remaining_seconds = (state.budget.deadline_at - self._now()).total_seconds()
        if remaining_seconds <= 0:
            raise StageDeadlineExceeded
        deadline = StageDeadline(
            deadline_at=state.budget.deadline_at,
            timeout_seconds=remaining_seconds,
        )
        return self._services.execute(stage, state, artifacts, deadline)

    @staticmethod
    def _terminalize_budget(
        state: ResearchState,
        code: FailureCode | None,
    ) -> ResearchState:
        failure_code = code or FailureCode.BUDGET_EXHAUSTED
        failure = Failure(
            failure_id=f"failure:{state.run_id}:budget-{len(state.failures) + 1:04d}",
            code=failure_code,
            stage=FailureStage.ORCHESTRATION,
            message=(
                "Run deadline exceeded."
                if failure_code is FailureCode.DEADLINE_EXCEEDED
                else "Run budget exhausted."
            ),
            recoverable=False,
            attempt=1,
        )
        return state.model_copy(
            update={
                "stage": ResearchStage.TERMINAL,
                "failures": (*state.failures, failure),
                "gate_outcome": GateOutcome.FAILED,
                "terminal_status": TerminalStatus.FAILED,
            }
        )

    @staticmethod
    def _terminalize_malformed_output(
        state: ResearchState,
        stage: ResearchStage,
    ) -> ResearchState:
        failure = Failure(
            failure_id=(
                f"failure:{state.run_id}:malformed-{len(state.failures) + 1:04d}"
            ),
            code=FailureCode.REPORT_SCHEMA_INVALID,
            stage=_FAILURE_STAGES[stage],
            message="Stage returned malformed structured output.",
            recoverable=False,
            attempt=1,
        )
        return state.model_copy(
            update={
                "stage": ResearchStage.TERMINAL,
                "step_count": state.step_count + 1,
                "failures": (*state.failures, failure),
                "gate_outcome": GateOutcome.FAILED,
                "terminal_status": TerminalStatus.FAILED,
            }
        )

    @staticmethod
    def _terminal_node(raw_state: _GraphState) -> _GraphState:
        state = ResearchState.model_validate_json(raw_state["research_state_json"])
        if state.gate_outcome is GateOutcome.PASSED:
            terminal_status = TerminalStatus.COMPLETED
        elif state.gate_outcome in {GateOutcome.LIMITED, GateOutcome.RECOVER}:
            terminal_status = TerminalStatus.COMPLETED_WITH_LIMITATIONS
        else:
            terminal_status = TerminalStatus.FAILED
        gate_outcome = state.gate_outcome or GateOutcome.FAILED
        artifacts = TechScoutHarness._decode_artifacts(raw_state)
        if terminal_status is not TerminalStatus.FAILED and not (
            artifacts.report is not None
            and artifacts.manifest is not None
            and artifacts.report.run_id == state.run_id
            and artifacts.manifest.run_id == state.run_id
            and artifacts.manifest.report_id == artifacts.report.report_id
            and artifacts.manifest.terminal_status is terminal_status
        ):
            terminal = TechScoutHarness._terminalize_invalid_artifacts(state)
            return TechScoutHarness._encode_graph_state(terminal, artifacts)
        terminal = state.model_copy(
            update={
                "stage": ResearchStage.TERMINAL,
                "gate_outcome": gate_outcome,
                "terminal_status": terminal_status,
            }
        )
        return TechScoutHarness._encode_graph_state(terminal, artifacts)

    @staticmethod
    def _decode_artifacts(raw_state: _GraphState) -> StageArtifacts:
        report_json = raw_state.get("report_json")
        manifest_json = raw_state.get("manifest_json")
        return StageArtifacts(
            report=(
                DecisionReport.model_validate_json(report_json)
                if report_json is not None
                else None
            ),
            manifest=(
                RunManifest.model_validate_json(manifest_json)
                if manifest_json is not None
                else None
            ),
        )

    @staticmethod
    def _merge_artifacts(
        previous: StageArtifacts,
        updated: StageArtifacts,
    ) -> StageArtifacts:
        return StageArtifacts(
            report=updated.report or previous.report,
            manifest=updated.manifest or previous.manifest,
        )

    @staticmethod
    def _encode_graph_state(
        state: ResearchState,
        artifacts: StageArtifacts,
    ) -> _GraphState:
        return {
            "research_state_json": state.model_dump_json(),
            "report_json": (
                artifacts.report.model_dump_json()
                if artifacts.report is not None
                else None
            ),
            "manifest_json": (
                artifacts.manifest.model_dump_json()
                if artifacts.manifest is not None
                else None
            ),
        }

    @staticmethod
    def _terminalize_invalid_artifacts(state: ResearchState) -> ResearchState:
        failure = Failure(
            failure_id=(
                f"failure:{state.run_id}:artifacts-{len(state.failures) + 1:04d}"
            ),
            code=FailureCode.REPORT_SCHEMA_INVALID,
            stage=FailureStage.REPORTING,
            message="Completed run requires a matching report and manifest.",
            recoverable=False,
            attempt=1,
        )
        return state.model_copy(
            update={
                "stage": ResearchStage.TERMINAL,
                "failures": (*state.failures, failure),
                "gate_outcome": GateOutcome.FAILED,
                "terminal_status": TerminalStatus.FAILED,
            }
        )
