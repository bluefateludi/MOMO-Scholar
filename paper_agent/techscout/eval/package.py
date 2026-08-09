from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from paper_agent.eval.evidence_package import EvidencePackageBuilder
from paper_agent.techscout.eval.contracts import (
    EvaluationEnvironment,
    EvaluationSummary,
    FaultExecutionResult,
    RetrievalExecutionResult,
    SuiteDefinition,
    TaskRunObservation,
)


PACKAGE_ARTIFACTS = frozenset(
    {
        "environment.json",
        "resolved-config.json",
        "case-metrics.jsonl",
        "eval-summary.json",
        "resume-evidence.md",
        "traces.jsonl",
        "traces-manifest.json",
    }
)


def publish_partial_results(
    output_dir: Path,
    *,
    observations: tuple[tuple[str, object], ...],
    failure_code: str,
) -> None:
    """Preserve completed observations after a terminal runner failure."""
    output_dir.mkdir(parents=True, exist_ok=True)
    records = [
        value.model_dump(mode="json")
        for _, value in observations
        if hasattr(value, "model_dump")
    ]
    (output_dir / "partial-results.json").write_text(
        json.dumps(
            {"sealed": False, "complete": False, "observations": records},
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "failures.jsonl").write_text(
        json.dumps(
            {"failure_code": failure_code, "partial_result_count": len(records)},
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )


def _resume_projection(summary: EvaluationSummary) -> str:
    def display(value: object) -> str:
        return "N/A" if value is None else str(value)

    lines = [
        "# MOMO TechScout evaluation evidence",
        "",
        f"- Profile: `{summary.profile.value}`",
        f"- Fault Recovery Success: `{summary.fault_recovery_success_count}/{summary.fault_recovery_attempt_count}`",
        f"- Retrieval Recall@5: `{display(summary.retrieval_recall_at_5)}`",
        f"- Version-filter accuracy: `{display(summary.version_filter_accuracy)}`",
        f"- Average fault recovery stages/retries: `{display(summary.average_fault_recovery_stages)}/{display(summary.average_fault_retries)}`",
    ]
    for variant, metrics in summary.task_metrics.items():
        lines.extend(
            [
                f"- {variant.value.upper()} Task Success: `{metrics.task_success_count}/{metrics.task_count}`",
                f"- {variant.value.upper()} First-pass Success: `{metrics.first_pass_success_count}/{metrics.task_count}`",
                f"- {variant.value.upper()} Recovery Success: `{metrics.recovery_success_count}/{metrics.recovery_attempt_count}`",
                f"- {variant.value.upper()} Tool schema/execution success: `{metrics.tool_call_schema_success_count}/{metrics.tool_call_execution_success_count}/{metrics.tool_call_count}`",
                f"- {variant.value.upper()} Average recovery stages/retries: `{display(metrics.average_recovery_stages)}/{metrics.average_retries}`",
                f"- {variant.value.upper()} Prompt/total tokens per successful task: `{display(metrics.prompt_tokens_per_successful_task)}/{display(metrics.total_tokens_per_successful_task)}`",
                f"- {variant.value.upper()} Estimated cost per successful task: `{display(metrics.estimated_cost_per_successful_task)}`",
                f"- {variant.value.upper()} Cold-live latency p50/p95 ms: `{metrics.latency['cold_live'].p50_ms}/{metrics.latency['cold_live'].p95_ms}`",
                f"- {variant.value.upper()} Warm-cache latency p50/p95 ms: `{metrics.latency['warm_cache'].p50_ms}/{metrics.latency['warm_cache'].p95_ms}`",
            ]
        )
    lines.extend(
        [
            "",
            "Cold-live and warm-cache observations are intentionally not combined.",
            (
                "Synthetic smoke results are acceptance evidence, not live benchmark claims."
                if summary.profile.value == "smoke"
                else "Final results use frozen offline fixtures; cold-live is N/A and no live-network claim is made."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def publish_package(
    output_dir: Path,
    *,
    suite: SuiteDefinition,
    environment: EvaluationEnvironment,
    summary: EvaluationSummary,
    task_runs: tuple[TaskRunObservation, ...],
    retrieval_results: tuple[RetrievalExecutionResult, ...],
    fault_results: tuple[FaultExecutionResult, ...],
) -> None:
    builder = EvidencePackageBuilder(output_dir)
    builder.write_json("environment.json", environment.model_dump(mode="json"))
    builder.write_json("resolved-config.json", suite.model_dump(mode="json"))
    records = [
        *(run.model_dump(mode="json") for run in task_runs),
        *(result.model_dump(mode="json") for result in retrieval_results),
        *(result.model_dump(mode="json") for result in fault_results),
    ]
    builder.write_text(
        "case-metrics.jsonl",
        "".join(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n" for record in records),
    )
    builder.write_json("eval-summary.json", summary.model_dump(mode="json"))
    builder.write_text("resume-evidence.md", _resume_projection(summary))
    builder.seal(
        package_kind="momo-techscout-evaluation-v1",
        required_artifacts=PACKAGE_ARTIFACTS,
        manifest_metadata={
            "suite_id": suite.suite_id,
            "profile": suite.profile.value,
            "sealed_once": True,
            "fixture_authority": "synthetic" if suite.profile.value == "smoke" else "final",
            "runner_completed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        },
    )
