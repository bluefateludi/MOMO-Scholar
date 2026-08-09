from __future__ import annotations

from collections import Counter
from pathlib import Path

from paper_agent.techscout.eval.contracts import (
    PROFILE_COUNTS,
    CaseKind,
    EvaluationCase,
    SuiteDefinition,
)


def load_suite(path: Path) -> tuple[SuiteDefinition, tuple[EvaluationCase, ...]]:
    suite = SuiteDefinition.model_validate_json(path.read_text(encoding="utf-8"))
    cases = tuple(
        EvaluationCase.model_validate_json((path.parent / name).read_text(encoding="utf-8"))
        for name in suite.case_files
    )
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("evaluation case identifiers must be unique")
    counts = Counter(case.kind for case in cases)
    actual = (
        counts[CaseKind.END_TO_END],
        counts[CaseKind.RETRIEVAL],
        counts[CaseKind.FAULT],
    )
    if actual != PROFILE_COUNTS[suite.profile]:
        raise ValueError(
            f"{suite.profile.value} suite requires counts {PROFILE_COUNTS[suite.profile]}, got {actual}"
        )
    if suite.profile.value == "final" and (
        suite.execution_policy.workers != 4
        or suite.execution_policy.timeout_seconds != 120
        or suite.execution_policy.max_infrastructure_reruns != 1
        or suite.fixture_case_tree_sha256 is None
        or suite.source_tree_sha256 is None
    ):
        raise ValueError(
            "final suite requires frozen fixture/source hashes, four workers, "
            "120-second timeout, and one infrastructure rerun"
        )
    return suite, cases
