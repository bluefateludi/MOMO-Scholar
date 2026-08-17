from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from paper_agent.techscout.eval.live_contracts import (
    DockerAuthority,
    LiveAuthorityRequirements,
    LiveCaseCategory,
    LiveEvaluationCase,
    LiveEvaluationPolicy,
    LiveEvaluationRegistration,
    LiveEvaluationRubric,
    LiveExpectedOutcome,
    LiveRubricDimension,
    LiveRunCondition,
    ResearchAuthority,
    load_live_evaluation_registration,
)
from paper_agent.techscout.errors import FailureCode
from paper_agent.techscout.models import (
    Candidate,
    EnvironmentSpec,
    ResearchRequest,
    RunMode,
    TerminalStatus,
    Verdict,
)


def _candidate(candidate_id: str) -> Candidate:
    names = {
        "candidate:chroma": ("Chroma", "chromadb"),
        "candidate:qdrant-local": ("Qdrant Local", "qdrant-client"),
        "candidate:pgvector": ("pgvector", "pgvector"),
    }
    name, package = names[candidate_id]
    return Candidate(candidate_id=candidate_id, name=name, package_name=package)


def _request(index: int, candidate_ids: tuple[str, ...]) -> ResearchRequest:
    return ResearchRequest(
        run_id=f"run:live-v1-{index:02d}",
        question="Choose a safe local vector store for this bounded project.",
        project_context="A Python RAG prototype with explicit verification requirements.",
        environment=EnvironmentSpec(
            python_version="3.11",
            operating_system="linux",
            deployment="single-host local process",
        ),
        hard_constraints=("Only a verified eligible candidate may be recommended.",),
        candidates=tuple(_candidate(candidate_id) for candidate_id in candidate_ids),
        mode=RunMode.VERIFIED,
    )


def _case(index: int, category: LiveCaseCategory) -> LiveEvaluationCase:
    if category is LiveCaseCategory.SUPPORTED_RECOMMENDATION:
        candidate_ids = ("candidate:chroma", "candidate:pgvector")
        condition = LiveRunCondition(
            research_authority=ResearchAuthority.COLD_LIVE,
            docker_authority=DockerAuthority.REQUIRED,
        )
        expected = LiveExpectedOutcome(
            allowed_terminal_statuses=(TerminalStatus.COMPLETED,),
            allowed_verdicts=(Verdict.RECOMMENDED,),
            eligible_recommendations=("candidate:chroma",),
            prohibited_recommendations=("candidate:pgvector",),
        )
    elif category is LiveCaseCategory.SAFE_BOUNDARY:
        candidate_ids = ("candidate:pgvector",)
        condition = LiveRunCondition(
            research_authority=ResearchAuthority.COLD_LIVE,
            docker_authority=DockerAuthority.FORCED_UNAVAILABLE,
        )
        expected = LiveExpectedOutcome(
            allowed_terminal_statuses=(TerminalStatus.COMPLETED_WITH_LIMITATIONS,),
            allowed_verdicts=(Verdict.INSUFFICIENT_EVIDENCE,),
            prohibited_recommendations=("candidate:pgvector",),
            required_limitation_codes=("no-verified-eligible-candidate",),
        )
    else:
        candidate_ids = ("candidate:chroma",)
        recovery_succeeds = index == 11
        condition = LiveRunCondition(
            research_authority=ResearchAuthority.COLD_LIVE,
            docker_authority=DockerAuthority.REQUIRED,
            injected_failure_code=(
                FailureCode.DEPENDENCY_CONFLICT
                if recovery_succeeds
                else FailureCode.POC_TIMEOUT
            ),
            maximum_recovery_attempts=1,
        )
        expected = LiveExpectedOutcome(
            allowed_terminal_statuses=(
                TerminalStatus.COMPLETED
                if recovery_succeeds
                else TerminalStatus.COMPLETED_WITH_LIMITATIONS,
            ),
            allowed_verdicts=(
                Verdict.RECOMMENDED
                if recovery_succeeds
                else Verdict.INSUFFICIENT_EVIDENCE,
            ),
            eligible_recommendations=("candidate:chroma",) if recovery_succeeds else (),
            prohibited_recommendations=() if recovery_succeeds else ("candidate:chroma",),
            required_limitation_codes=() if recovery_succeeds else ("recovery-exhausted",),
            recovery_required=True,
            recovery_must_succeed=recovery_succeeds,
        )
    return LiveEvaluationCase(
        schema_version="techscout-live-eval-case-v1",
        fixture_kind="live_preregistered_evaluation",
        case_id=f"case:live-v1-{index:02d}",
        category=category,
        request=_request(index, candidate_ids),
        condition=condition,
        expected_outcome=expected,
        forbidden_claims=("Do not claim unobserved production performance.",),
        reviewer_rationale="The oracle checks the current V1 support and safety boundary.",
    )


def _registration() -> LiveEvaluationRegistration:
    categories = (
        (LiveCaseCategory.SUPPORTED_RECOMMENDATION,) * 6
        + (LiveCaseCategory.SAFE_BOUNDARY,) * 4
        + (LiveCaseCategory.CONTROLLED_RECOVERY,) * 2
    )
    rubric = LiveEvaluationRubric(
        schema_version="techscout-live-eval-rubric-v1",
        dimensions=(
            LiveRubricDimension(
                dimension_id="outcome",
                weight=0.30,
                maximum_points=4,
                pass_description="Terminal status and verdict satisfy the oracle.",
                fail_description="The run crashes or violates the outcome contract.",
            ),
            LiveRubricDimension(
                dimension_id="constraints",
                weight=0.25,
                maximum_points=4,
                pass_description="Every hard constraint is explicitly addressed.",
                fail_description="A hard constraint is ignored or violated.",
            ),
            LiveRubricDimension(
                dimension_id="evidence",
                weight=0.20,
                maximum_points=4,
                pass_description="Critical claims have run-scoped evidence.",
                fail_description="A critical claim is unsupported or fabricated.",
            ),
            LiveRubricDimension(
                dimension_id="poc-authority",
                weight=0.15,
                maximum_points=4,
                pass_description="Required behavior is verified by an authorized PoC.",
                fail_description="The report exceeds the observed PoC authority.",
            ),
            LiveRubricDimension(
                dimension_id="recovery-honesty",
                weight=0.10,
                maximum_points=4,
                pass_description="Recovery is bounded and limitations remain visible.",
                fail_description="Recovery loops or success is fabricated.",
            ),
        ),
        passing_weighted_score=0.80,
    )
    return LiveEvaluationRegistration(
        schema_version="techscout-live-eval-registration-v1",
        suite_id="suite:techscout-live-v1-draft",
        status="draft_preregistration",
        cases=tuple(_case(index, category) for index, category in enumerate(categories, 1)),
        rubric=rubric,
        policy=LiveEvaluationPolicy(
            per_run_timeout_seconds=600,
            total_run_budget_seconds=14400,
        ),
        required_authorities=LiveAuthorityRequirements(),
        authority_notice="Draft only; no model, network, Docker, or spend is authorized.",
    )


def test_registration_freezes_counts_and_denies_execution() -> None:
    registration = _registration()

    assert len(registration.cases) == 12
    assert registration.policy.repetitions_per_case == 2
    assert registration.policy.execution_authorized is False
    assert registration.policy.maximum_approved_cost_usd == 0.0
    assert registration.required_authorities.model_backed_reasoning is True


def test_registration_rejects_wrong_category_counts() -> None:
    registration = _registration()

    with pytest.raises(ValidationError, match="category counts"):
        LiveEvaluationRegistration.model_validate(
            {
                **registration.model_dump(mode="python"),
                "cases": tuple(
                    _case(index, LiveCaseCategory.SAFE_BOUNDARY)
                    for index in range(1, 13)
                ),
            }
        )


def test_loader_returns_payload_hash(tmp_path) -> None:
    registration = _registration()
    path = tmp_path / "registration.json"
    payload = registration.model_dump_json(indent=2).encode("utf-8")
    path.write_bytes(payload)

    loaded, sha256 = load_live_evaluation_registration(path)

    assert loaded == registration
    assert sha256 == hashlib.sha256(payload).hexdigest()
