import pytest

from paper_agent.techscout.eval.faults import (
    DeterministicFaultInjector,
    FaultPlan,
    InjectedFault,
)


def test_fault_injector_triggers_once_at_exact_stage_call():
    injector = DeterministicFaultInjector(
        (FaultPlan(stage="poc", failure_code="dependency_conflict", trigger_on_call=2),)
    )
    injector.check("poc")

    with pytest.raises(InjectedFault, match="dependency_conflict"):
        injector.check("poc")

    injector.check("poc")
    assert injector.triggered_count == 1
