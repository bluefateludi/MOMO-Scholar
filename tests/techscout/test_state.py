import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from paper_agent.techscout.errors import Failure, FailureCode, FailureStage
from paper_agent.techscout.models import (
    Candidate,
    EnvironmentSpec,
    GateOutcome,
    ResearchPlan,
    ResearchRequest,
    TerminalStatus,
)
from paper_agent.techscout.state import (
    CheckpointMetadata,
    ResearchStage,
    ResearchState,
    RunBudget,
)


def _request(run_id: str = "run:fixture-001") -> ResearchRequest:
    return ResearchRequest(
        run_id=run_id,
        question="Choose a local vector store.",
        project_context="A local Python RAG application.",
        environment=EnvironmentSpec(
            python_version="3.11",
            operating_system="linux",
            deployment="docker",
        ),
        hard_constraints=("metadata filtering",),
        candidates=(
            Candidate(
                candidate_id="candidate:qdrant-client",
                name="Qdrant Local",
                package_name="qdrant-client",
            ),
        ),
    )


def _budget() -> RunBudget:
    return RunBudget(deadline_at=datetime(2026, 8, 9, 12, tzinfo=timezone.utc))


def test_research_state_round_trips_as_json_without_opaque_runtime_objects() -> None:
    plan = ResearchPlan(
        plan_id="plan:fixture-001",
        investigation_dimensions=("compatibility",),
        required_capabilities=("official-doc-research",),
        planned_evidence=("official documentation",),
        poc_intent="research only",
    )
    checkpoint = CheckpointMetadata(
        checkpoint_id="checkpoint:fixture-001:0001",
        run_id="run:fixture-001",
        stage=ResearchStage.RESEARCH_CANDIDATES,
        sequence=1,
        parent_checkpoint_id=None,
        completed_stages=(ResearchStage.NORMALIZE_REQUEST, ResearchStage.PLAN_RESEARCH),
    )
    state = ResearchState(
        run_id="run:fixture-001",
        request=_request(),
        budget=_budget(),
        stage=ResearchStage.RESEARCH_CANDIDATES,
        step_count=2,
        tool_call_count=1,
        token_count=800,
        recovery_count=0,
        plan=plan,
        checkpoint=checkpoint,
        candidate_ids=("candidate:qdrant-client",),
        source_ids=("source:qdrant-docs@sha256:abc",),
        evidence_ids=(),
        poc_result_ids=(),
        failures=(),
        gate_outcome=None,
        terminal_status=None,
    )

    dumped = state.model_dump(mode="json")
    json.dumps(dumped)
    assert ResearchState.model_validate_json(state.model_dump_json()) == state
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ResearchState.model_validate({**dumped, "runtime_client": object()})


def test_terminal_state_requires_terminal_stage_and_gate_outcome() -> None:
    failure = Failure(
        failure_id="failure:fixture-001:0001",
        code=FailureCode.BUDGET_EXHAUSTED,
        stage=FailureStage.ORCHESTRATION,
        message="Step budget exhausted.",
        recoverable=False,
        attempt=1,
    )

    state = ResearchState(
        run_id="run:fixture-001",
        request=_request(),
        budget=_budget(),
        stage=ResearchStage.TERMINAL,
        step_count=16,
        tool_call_count=4,
        token_count=2_000,
        recovery_count=0,
        candidate_ids=("candidate:qdrant-client",),
        source_ids=(),
        evidence_ids=(),
        poc_result_ids=(),
        failures=(failure,),
        gate_outcome=GateOutcome.FAILED,
        terminal_status=TerminalStatus.FAILED,
    )
    assert state.terminal_status is TerminalStatus.FAILED

    with pytest.raises(ValidationError, match="terminal status requires terminal stage"):
        ResearchState.model_validate(
            {**state.model_dump(), "stage": ResearchStage.VALIDATE}
        )
    with pytest.raises(ValidationError, match="terminal stage requires"):
        ResearchState.model_validate(
            {
                **state.model_dump(),
                "terminal_status": None,
                "gate_outcome": None,
            }
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("step_count", 17, "step budget exhausted"),
        ("tool_call_count", 13, "tool-call budget exhausted"),
        ("token_count", 30_001, "token budget exhausted"),
        ("recovery_count", 2, "recovery budget exhausted"),
    ),
)
def test_research_state_rejects_exhausted_budgets(
    field: str,
    value: int,
    message: str,
) -> None:
    state = ResearchState(
        run_id="run:fixture-001",
        request=_request(),
        budget=_budget(),
        stage=ResearchStage.NORMALIZE_REQUEST,
        step_count=0,
        tool_call_count=0,
        token_count=0,
        recovery_count=0,
        candidate_ids=("candidate:qdrant-client",),
        source_ids=(),
        evidence_ids=(),
        poc_result_ids=(),
        failures=(),
    )

    with pytest.raises(ValidationError, match=message):
        ResearchState.model_validate({**state.model_dump(), field: value})


def test_research_state_keeps_request_and_candidate_identity_consistent() -> None:
    state_data = {
        "run_id": "run:fixture-001",
        "request": _request(),
        "budget": _budget(),
        "stage": ResearchStage.NORMALIZE_REQUEST,
        "step_count": 0,
        "tool_call_count": 0,
        "token_count": 0,
        "recovery_count": 0,
        "candidate_ids": ("candidate:qdrant-client",),
        "source_ids": (),
        "evidence_ids": (),
        "poc_result_ids": (),
        "failures": (),
    }

    with pytest.raises(ValidationError, match="request run identifier"):
        ResearchState.model_validate(
            {**state_data, "request": _request("run:different")}
        )
    with pytest.raises(ValidationError, match="retain every requested candidate"):
        ResearchState.model_validate({**state_data, "candidate_ids": ()})
    with pytest.raises(ValidationError, match="deadline_at must include a timezone"):
        RunBudget(deadline_at=datetime(2026, 8, 9, 12))