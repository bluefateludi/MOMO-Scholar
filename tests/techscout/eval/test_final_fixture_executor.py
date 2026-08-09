from pathlib import Path

from paper_agent.techscout.eval.contracts import (
    CaseKind,
    EvaluationCase,
    HarnessVariant,
    validate_fault_contract,
    validate_retrieval_contract,
)
from paper_agent.techscout.eval.faults import DeterministicFaultInjector
from paper_agent.techscout.eval.smoke import FrozenFixtureExecutor
from paper_agent.techscout.eval.suite import load_suite
from paper_agent.techscout.observability import TechScoutTraceRecorder


FIXTURES = Path("tests/fixtures/techscout/eval")


def test_final_executor_observes_v0_v1_retrieval_and_fault_boundaries(tmp_path):
    _, cases = load_suite(FIXTURES / "final-suite.json")
    executor = FrozenFixtureExecutor(tmp_path / "checkpoints")
    trace = TechScoutTraceRecorder(tmp_path / "traces.jsonl", run_id="final-boundaries")

    e2e = next(case for case in cases if case.case_id == "techscout-final-e2e-01")
    v0 = executor.run_e2e(e2e, HarnessVariant.V0, timeout_seconds=120, trace=trace)
    v1 = executor.run_e2e(e2e, HarnessVariant.V1, timeout_seconds=120, trace=trace)
    assert v0.terminal_status == v1.terminal_status == "completed"

    retrieval = next(case for case in cases if case.case_id == "techscout-final-retrieval-09")
    retrieval_result = executor.run_retrieval(retrieval, timeout_seconds=120, trace=trace)
    validate_retrieval_contract(retrieval, retrieval_result)
    assert retrieval_result.relevant_source_ids[0] not in retrieval_result.retrieved_source_ids[:5]

    fault = next(case for case in cases if case.case_id == "techscout-final-fault-07")
    assert fault.kind is CaseKind.FAULT and fault.fault_plan is not None
    fault_result = executor.run_fault(
        fault,
        DeterministicFaultInjector(fault.fault_plan),
        timeout_seconds=120,
        trace=trace,
    )
    validate_fault_contract(fault, fault_result)
    assert fault_result.recovery_succeeded is False
    trace.seal()


def test_v0_disables_targeted_recovery(tmp_path):
    case = EvaluationCase.model_validate_json(
        (FIXTURES / "smoke-bounded-recovery.json").read_text(encoding="utf-8")
    )
    executor = FrozenFixtureExecutor(tmp_path / "checkpoints")
    trace = TechScoutTraceRecorder(tmp_path / "traces.jsonl", run_id="v0-no-recovery")
    result = executor.run_e2e(case, HarnessVariant.V0, timeout_seconds=120, trace=trace)
    assert result.recovery_attempted is False
    assert result.poc_result_present is False
    trace.seal()
