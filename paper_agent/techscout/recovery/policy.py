"""At most one local recovery of only the failed stage."""

from paper_agent.techscout.errors import Failure, RecoveryAction, StableId
from paper_agent.techscout.models import TechScoutModel
from paper_agent.techscout.state import ResearchStage


class RecoveryDecision(TechScoutModel):
    should_recover: bool
    action: RecoveryAction
    repeated_stage: ResearchStage | None
    checkpoint_id: StableId | None
    original_failure_id: StableId
    next_recovery_count: int
    reason: str


class RecoveryPolicy:
    _STAGES = {
        "research": ResearchStage.RESEARCH_CANDIDATES,
        "context": ResearchStage.SELECT_CONTEXT,
        "poc_planning": ResearchStage.PLAN_POC,
        "poc_execution": ResearchStage.EXECUTE_POC,
        "validation": ResearchStage.VALIDATE,
        "reporting": ResearchStage.REVIEW_REPORT,
    }

    def decide(
        self,
        failure: Failure,
        *,
        recovery_count: int,
        checkpoint_id: StableId | None,
    ) -> RecoveryDecision:
        stage = self._STAGES.get(failure.stage.value)
        permitted = (
            failure.recoverable
            and recovery_count == 0
            and checkpoint_id is not None
            and stage is not None
        )
        if permitted:
            return RecoveryDecision(
                should_recover=True,
                action=failure.recovery_action or RecoveryAction.FAIL_SAFELY,
                repeated_stage=stage,
                checkpoint_id=checkpoint_id,
                original_failure_id=failure.failure_id,
                next_recovery_count=1,
                reason="Repeat only the failed stage from its linked checkpoint.",
            )
        action = (
            RecoveryAction.PUBLISH_LIMITED_RESULT
            if failure.recovery_action is RecoveryAction.PUBLISH_LIMITED_RESULT
            or failure.stage.value in {"research", "poc_planning", "poc_execution"}
            else RecoveryAction.FAIL_SAFELY
        )
        return RecoveryDecision(
            should_recover=False,
            action=action,
            repeated_stage=None,
            checkpoint_id=None,
            original_failure_id=failure.failure_id,
            next_recovery_count=recovery_count,
            reason="Recovery is unavailable or the single recovery attempt is exhausted.",
        )
