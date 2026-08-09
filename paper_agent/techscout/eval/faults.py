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

    def __init__(self, plans: tuple[FaultPlan, ...]) -> None:
        self._plans = plans
        self._calls: dict[str, int] = {}
        self._triggered: set[int] = set()

    def check(self, stage: str) -> None:
        call = self._calls.get(stage, 0) + 1
        self._calls[stage] = call
        for index, plan in enumerate(self._plans):
            if index not in self._triggered and plan.stage == stage and plan.trigger_on_call == call:
                self._triggered.add(index)
                raise InjectedFault(plan)

    @property
    def triggered_count(self) -> int:
        return len(self._triggered)
