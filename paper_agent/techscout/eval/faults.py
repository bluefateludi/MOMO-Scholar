from __future__ import annotations

from pydantic import Field

from paper_agent.techscout.models import NonEmptyStr, TechScoutModel


class FaultPlan(TechScoutModel):
    stage: NonEmptyStr
    failure_code: NonEmptyStr
    trigger_on_call: int = Field(default=1, ge=1)


class InjectedFault(RuntimeError):
    def __init__(self, plan: FaultPlan) -> None:
        super().__init__(plan.failure_code)
        self.plan = plan


class DeterministicFaultInjector:
    """Inject one typed failure at an exact stage/call without time or randomness."""

    def __init__(self, plan: FaultPlan) -> None:
        self._plan = plan
        self._calls: dict[str, int] = {}
        self._triggered = False

    def check(self, stage: str) -> None:
        call = self._calls.get(stage, 0) + 1
        self._calls[stage] = call
        if not self._triggered and self._plan.stage == stage and self._plan.trigger_on_call == call:
            self._triggered = True
            raise InjectedFault(self._plan)

    @property
    def triggered_count(self) -> int:
        return int(self._triggered)
