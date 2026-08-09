from paper_agent.techscout.errors import (
    Failure,
    FailureCode,
    FailureStage,
    RecoveryAction,
)
from paper_agent.techscout.models import Candidate, PocPlan
from paper_agent.techscout.recovery.approval import (
    ApprovalOutcome,
    ApprovalPolicy,
    OperationKind,
    OperationRequest,
)
from paper_agent.techscout.recovery.classifier import FailureClassifier
from paper_agent.techscout.recovery.policy import RecoveryPolicy
from paper_agent.techscout.sandbox.compiler import PocCompiler
from paper_agent.techscout.sandbox.types import (
    ExecutionStatus,
    PocStage,
    SandboxResult,
)
from paper_agent.techscout.state import ResearchStage


def _command():
    candidate = Candidate(
        candidate_id="candidate:qdrant-client",
        name="Qdrant Local",
        package_name="qdrant-client",
    )
    plan = PocPlan(
        poc_plan_id="poc-plan:qdrant:1",
        candidate_id=candidate.candidate_id,
        recipe_id="recipe:qdrant-local@1",
        trusted=True,
        checks=("install",),
    )
    return PocCompiler().compile(plan, candidate, PocStage.INSTALL)


def test_classifier_maps_dependency_conflict_to_one_allowed_fix() -> None:
    result = SandboxResult(
        command=_command(),
        status=ExecutionStatus.FAILED,
        exit_code=1,
        timed_out=False,
        duration_ms=12,
        stderr="ERROR: ResolutionImpossible: conflicting dependencies",
        failure_code=FailureCode.POC_NONZERO_EXIT,
    )

    failure = FailureClassifier().classify_sandbox(
        result,
        failure_id="failure:run-001:poc:001",
    )

    assert failure is not None
    assert failure.code is FailureCode.DEPENDENCY_CONFLICT
    assert failure.recovery_action is RecoveryAction.PIN_VERSION_AND_RERUN_POC
    assert failure.stage is FailureStage.POC_EXECUTION


def test_recovery_repeats_only_failed_stage_once_and_links_checkpoint() -> None:
    failure = Failure(
        failure_id="failure:run-001:poc:001",
        code=FailureCode.DEPENDENCY_CONFLICT,
        stage=FailureStage.POC_EXECUTION,
        message="Dependency conflict.",
        recoverable=True,
        recovery_action=RecoveryAction.PIN_VERSION_AND_RERUN_POC,
        attempt=1,
    )
    policy = RecoveryPolicy()

    first = policy.decide(
        failure,
        recovery_count=0,
        checkpoint_id="checkpoint:run-001:poc",
    )
    exhausted = policy.decide(
        failure,
        recovery_count=1,
        checkpoint_id="checkpoint:run-001:poc",
    )

    assert first.should_recover is True
    assert first.repeated_stage is ResearchStage.EXECUTE_POC
    assert first.checkpoint_id == "checkpoint:run-001:poc"
    assert first.original_failure_id == failure.failure_id
    assert first.next_recovery_count == 1
    assert exhausted.should_recover is False
    assert exhausted.repeated_stage is None
    assert exhausted.action is RecoveryAction.PUBLISH_LIMITED_RESULT


def test_recovery_rejects_forged_or_stop_only_failure_actions() -> None:
    policy = RecoveryPolicy()
    unsafe = Failure(
        failure_id="failure:run-001:policy:001",
        code=FailureCode.UNSAFE_REQUEST,
        stage=FailureStage.POLICY,
        message="Unsafe request.",
        recoverable=True,
        recovery_action=RecoveryAction.REQUEST_APPROVAL,
        attempt=1,
    )
    mismatched = Failure(
        failure_id="failure:run-001:poc:002",
        code=FailureCode.DEPENDENCY_CONFLICT,
        stage=FailureStage.POC_EXECUTION,
        message="Dependency conflict.",
        recoverable=True,
        recovery_action=RecoveryAction.DIAGNOSE_AND_RERUN_POC,
        attempt=1,
    )

    for failure in (unsafe, mismatched):
        decision = policy.decide(
            failure,
            recovery_count=0,
            checkpoint_id="checkpoint:run-001:failure",
        )
        assert decision.should_recover is False


def test_high_risk_operations_require_approval_and_default_to_denial() -> None:
    policy = ApprovalPolicy()

    reviewed = policy.evaluate(
        OperationRequest(
            kind=OperationKind.RUN_REVIEWED_POC,
            description="Run Qdrant Local smoke.",
            allowlisted=True,
        )
    )
    interrupted = policy.evaluate(
        OperationRequest(
            kind=OperationKind.MOUNT_HOST_PATH,
            description="Mount an arbitrary host directory.",
            approval_available=True,
        )
    )
    denied = policy.evaluate(
        OperationRequest(
            kind=OperationKind.DELETE_FILES,
            description="Delete a host directory.",
        )
    )
    untrusted = policy.evaluate(
        OperationRequest(
            kind=OperationKind.RUN_REVIEWED_POC,
            description="Run generated command text.",
            allowlisted=False,
            approval_available=True,
        )
    )

    assert reviewed.outcome is ApprovalOutcome.ALLOW
    assert interrupted.outcome is ApprovalOutcome.REQUIRE_APPROVAL
    assert denied.outcome is ApprovalOutcome.DENY
    assert untrusted.outcome is ApprovalOutcome.DENY
