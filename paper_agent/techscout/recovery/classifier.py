"""Classify sandbox failures without relying on model output."""

from paper_agent.techscout.errors import (
    Failure,
    FailureCode,
    FailureStage,
    RecoveryAction,
    StableId,
)
from paper_agent.techscout.sandbox.types import ExecutionStatus, SandboxResult


class FailureClassifier:
    _DEPENDENCY_MARKERS = (
        "resolutionimpossible",
        "dependency conflict",
        "conflicting dependencies",
    )
    _VERSION_MARKERS = (
        "no matching distribution found",
        "could not find a version that satisfies",
        "requires-python",
    )

    def classify_sandbox(
        self,
        result: SandboxResult,
        *,
        failure_id: StableId,
        attempt: int = 1,
    ) -> Failure | None:
        if result.status is ExecutionStatus.SUCCEEDED:
            return None
        text = f"{result.stdout}\n{result.stderr}".casefold()
        if result.status is ExecutionStatus.TIMED_OUT:
            code = FailureCode.POC_TIMEOUT
            action = RecoveryAction.DIAGNOSE_AND_RERUN_POC
        elif result.status is ExecutionStatus.UNAVAILABLE:
            code = FailureCode.TOOL_UNAVAILABLE
            action = RecoveryAction.PUBLISH_LIMITED_RESULT
        elif any(marker in text for marker in self._DEPENDENCY_MARKERS):
            code = FailureCode.DEPENDENCY_CONFLICT
            action = RecoveryAction.PIN_VERSION_AND_RERUN_POC
        elif any(marker in text for marker in self._VERSION_MARKERS):
            code = FailureCode.VERSION_CONFLICT
            action = RecoveryAction.PIN_VERSION_AND_RERUN_POC
        else:
            code = FailureCode.POC_NONZERO_EXIT
            action = RecoveryAction.DIAGNOSE_AND_RERUN_POC

        recoverable = code is not FailureCode.TOOL_UNAVAILABLE and attempt == 1
        return Failure(
            failure_id=failure_id,
            code=code,
            stage=FailureStage.POC_EXECUTION,
            message=_message(code, result.exit_code),
            recoverable=recoverable,
            recovery_action=action if recoverable else RecoveryAction.PUBLISH_LIMITED_RESULT,
            attempt=attempt,
            details={
                "exit_code": result.exit_code,
                "timed_out": result.timed_out,
                "recipe_id": result.command.recipe_id,
                "stage": result.command.stage.value,
            },
        )


def _message(code: FailureCode, exit_code: int | None) -> str:
    if code is FailureCode.POC_TIMEOUT:
        return "The allowlisted PoC exceeded its timeout."
    if code is FailureCode.TOOL_UNAVAILABLE:
        return "The Docker sandbox is unavailable."
    if code is FailureCode.DEPENDENCY_CONFLICT:
        return "The allowlisted installation reported a dependency conflict."
    if code is FailureCode.VERSION_CONFLICT:
        return "The allowlisted installation reported an unavailable version."
    return f"The allowlisted PoC exited with code {exit_code}."
