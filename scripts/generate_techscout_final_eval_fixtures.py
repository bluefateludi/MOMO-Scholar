from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "tests" / "fixtures" / "techscout" / "eval"
SOURCES = ROOT / "tests" / "fixtures" / "techscout" / "final"


def write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def case(case_id: str, kind: str, source: str, expected: dict[str, object], **extra: object) -> dict[str, object]:
    return {
        "schema_version": "techscout-eval-case-v1",
        "fixture_kind": "synthetic_frozen_evaluation",
        "case_id": case_id,
        "kind": kind,
        "source_fixture": source,
        "cache_mode": "warm_cache" if kind == "end_to_end" else "offline",
        "supports_poc": bool(extra.pop("supports_poc", False)),
        **extra,
        "expected_contract": {"contract_kind": kind, **expected},
        "observed_metrics": {},
    }


def main() -> None:
    case_files: list[str] = []
    dimensions = (
        ("local-persistence", "local persistence"),
        ("metadata-filter", "metadata equality filtering"),
        ("no-service", "no separately managed database"),
        ("python-compat", "Python 3.11 compatibility"),
        ("durability", "restart durability"),
        ("isolation", "tenant metadata isolation"),
        ("backup", "local backup support"),
        ("small-footprint", "single-node footprint"),
        ("license", "permissive project license"),
        ("api-stability", "stable Python API"),
        ("filter-composition", "composable metadata filters"),
        ("offline-start", "offline local startup"),
    )
    for number, (slug, constraint) in enumerate(dimensions, 1):
        case_id = f"techscout-final-e2e-{number:02d}"
        source_path = SOURCES / f"e2e-{number:02d}-{slug}.json"
        source = {
            "schema_version": "techscout-final-task-v1",
            "fixture_kind": "frozen_offline_final_input",
            "task_id": case_id,
            "scenario": "happy_path",
            "network_policy": "offline",
            "request": {
                "question": f"Choose a local vector store satisfying {constraint}.",
                "project_context": "Python 3.11 single-node local RAG service.",
                "hard_constraints": [constraint, "metadata equality filtering"],
                "candidates": [{"candidate_id": "chroma", "display_name": "Chroma"}],
            },
            "frozen_inputs": {"provenance": "offline synthetic final fixture", "dimension": slug},
            "observed_metrics": {},
        }
        write(source_path, source)
        filename = f"final-e2e-{number:02d}.json"
        write(EVAL / filename, case(case_id, "end_to_end", source_path.relative_to(ROOT).as_posix(), {
            "terminal_status": "completed", "task_success": True, "first_pass_success": True
        }, supports_poc=number % 3 != 0))
        case_files.append(filename)

    observation_source = SOURCES / "offline-observations.json"
    observations: dict[str, object] = {"schema_version": "techscout-final-observations-v1", "retrieval_observations": {}, "fault_observations": {}}
    for number in range(1, 41):
        case_id = f"techscout-final-retrieval-{number:02d}"
        relevant = [f"official:dimension-{number:02d}"]
        retrieved = relevant + [f"official:distractor-{number:02d}-{rank}" for rank in range(1, 5)]
        if number in {9, 18, 27, 36}:
            retrieved = [f"official:distractor-{number:02d}-{rank}" for rank in range(1, 6)] + relevant
        observations["retrieval_observations"][case_id] = {
            "retrieved_source_ids": retrieved,
            "relevant_source_ids": relevant,
            "expected_version_match": True,
            "actual_version_match": number not in {10, 20, 30},
        }
        filename = f"final-retrieval-{number:02d}.json"
        write(EVAL / filename, case(case_id, "retrieval", observation_source.relative_to(ROOT).as_posix(), {
            "relevant_source_ids": relevant, "expected_version_match": True
        }))
        case_files.append(filename)

    fault_codes = (
        "dependency_conflict", "tool_timeout", "cache_corruption", "checkpoint_interruption",
        "schema_repairable", "transient_tool_failure", "permission_denied", "invalid_contract",
    )
    for number, failure_code in enumerate(fault_codes, 1):
        case_id = f"techscout-final-fault-{number:02d}"
        stage = "poc_execution" if number <= 4 else "research"
        observations["fault_observations"][case_id] = {"stage": stage}
        recovered = number <= 6
        filename = f"final-fault-{number:02d}.json"
        write(EVAL / filename, case(case_id, "fault", observation_source.relative_to(ROOT).as_posix(), {
            "injected_failure_code": failure_code, "recovery_succeeded": recovered
        }, fault_plan={"stage": stage, "failure_code": failure_code, "trigger_on_call": 1}))
        case_files.append(filename)
    write(observation_source, observations)
    write(EVAL / "final-suite.json", {
        "schema_version": "techscout-eval-suite-v1",
        "suite_id": "techscout-final-2026-08-09-v1",
        "profile": "final",
        "case_files": case_files,
        "executor_version": "frozen-synthetic-v1",
        "fixture_case_tree_sha256": "e8b90f5e7025155d0a114be1cfade705a8c7be2dafa9d6fdf589ad140243ed0d",
        "source_tree_sha256": "08a22e8720f668f92f35e127fc3c8b1f49e5f484f8df804ba70bb3ffd6b33066",
        "execution_policy": {
            "model": "frozen-synthetic-model-v1", "temperature": 0.0,
            "search_snapshot_id": "snapshot:techscout-final-2026-08-09-v1",
            "workers": 4, "timeout_seconds": 120, "max_infrastructure_reruns": 1,
            "tuning_iterations": 0,
        },
    })


if __name__ == "__main__":
    main()
