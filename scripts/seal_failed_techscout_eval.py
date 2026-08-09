from __future__ import annotations

import json
import sys
from pathlib import Path

from paper_agent.eval.evidence_package import EvidencePackageBuilder
from paper_agent.observability.sealed_jsonl import verify_sealed_jsonl


BASELINE = "b7516a7b478834614f6ce2ccf1ae63a5c73c3140"
REQUIRED = frozenset(
    {
        "environment.json",
        "resolved-config.json",
        "partial-results.json",
        "failures.jsonl",
        "failure-diagnostic.json",
        "eval-summary.json",
        "resume-evidence.md",
        "traces.jsonl",
        "traces-manifest.json",
    }
)


def main(output: Path, suite_path: Path, execution_commit: str) -> None:
    partial = json.loads((output / "partial-results.json").read_text(encoding="utf-8"))
    failure = json.loads((output / "failures.jsonl").read_text(encoding="utf-8"))
    trace_manifest = verify_sealed_jsonl(output / "traces.jsonl")
    trace_records = [
        json.loads(line)
        for line in (output / "traces.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    events = [record for record in trace_records if record.get("record_type") == "event"]
    terminal_events = [record for record in events if record.get("name") == "terminal.completed"]
    traced_cases = {
        record.get("attributes", {}).get("case_id")
        for record in events
        if record.get("attributes", {}).get("case_id")
    }
    builder = EvidencePackageBuilder(output)
    builder.write_json(
        "environment.json",
        {
            "git_dirty": False,
            "models": {"fixture_executor": "frozen-synthetic-model-v1"},
            "executor_version": "frozen-synthetic-v1",
            "baseline_git_commit": BASELINE,
            "execution_git_commit": execution_commit,
            "network_policy": "offline",
        },
    )
    builder.write_text("resolved-config.json", suite_path.read_text(encoding="utf-8"))
    builder.write_json(
        "failure-diagnostic.json",
        {
            "failure_class": "fixture_input_validation",
            "failure_code": failure["failure_code"],
            "message": "ResearchRequest rejected duplicate hard constraints.",
            "case_id": "techscout-final-e2e-02",
            "rerun_authorized": False,
            "original_trace_preserved": True,
        },
    )
    builder.write_json(
        "eval-summary.json",
        {
            "schema_version": "techscout-eval-failure-summary-v1",
            "complete": False,
            "planned_counts": {"end_to_end": 12, "observations_v0_v1": 24, "retrieval": 40, "fault": 8},
            "authoritative_observation_counts": {
                "end_to_end": 0,
                "retrieval": 0,
                "fault": 0,
            },
            "non_authoritative_trace_diagnostics": {
                "event_count": len(events),
                "terminal_event_count": len(terminal_events),
                "traced_case_count": len(traced_cases),
                "trace_sha256": trace_manifest["sha256"],
            },
            "metrics": {
                "task_success": None,
                "first_pass_success": None,
                "recovery_success": None,
                "retrieval_recall_at_5": None,
                "version_filter_accuracy": None,
                "average_recovery_stages": None,
                "average_retries": None,
                "tokens_per_successful_task": None,
                "latency": {
                    "cold_live": {"count": 0, "p50_ms": None, "p95_ms": None},
                    "warm_cache": {"count": 0, "p50_ms": None, "p95_ms": None},
                },
                "estimated_cost_per_successful_task": None,
            },
            "failure": failure,
            "partial_results_complete": partial["complete"],
        },
    )
    builder.write_text(
        "resume-evidence.md",
        """# MOMO TechScout final evaluation evidence

- Status: `INVALID — frozen fixture input validation failure`
- Authoritative observations: `0`
- Task Success / First-pass / Recovery / Recall@5: `N/A`
- Retries / Tokens / Cost: `N/A`
- Cold-live latency: `N/A (N=0; live network prohibited)`
- Warm-cache latency: `N/A (N=0)`

No resume-ready numeric claim is authorized by this package. The original sealed
trace is retained only as failure diagnostics and is not promoted to evaluation
observations.
""",
    )
    builder.seal(
        package_kind="momo-techscout-evaluation-failure-v1",
        required_artifacts=REQUIRED,
        manifest_metadata={
            "suite_id": "techscout-final-2026-08-09-v1",
            "complete": False,
            "failure_code": failure["failure_code"],
            "authoritative_observation_count": 0,
        },
    )


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3])
