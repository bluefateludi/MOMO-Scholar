import json

import pytest
from pydantic import ValidationError

from paper_agent.techscout.errors import Failure, FailureCode, FailureStage
from paper_agent.techscout.models import GateOutcome, ResearchPlan, TerminalStatus
from paper_agent.techscout.state import CheckpointMetadata, ResearchStage, ResearchState


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
        stage=ResearchStage.RESEARCH_CANDIDATES,
        step_count=2,
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
        stage=ResearchStage.TERMINAL,
        step_count=16,
        recovery_count=0,
        candidate_ids=(),
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
