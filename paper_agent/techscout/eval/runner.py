from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from paper_agent.eval.evidence_package import EvidencePackageBuilder
from paper_agent.techscout.eval.contracts import (
    PROFILE_COUNTS,
    CaseKind,
    EvaluationCase,
    EvaluationEnvironment,
    EvaluationSummary,
    HarnessVariant,
    SuiteDefinition,
)
from paper_agent.techscout.eval.metrics import summarize
from paper_agent.techscout.observability import TechScoutTraceRecorder, TraceEventName


_PACKAGE_ARTIFACTS = frozenset(
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


def _load_suite(path: Path) -> tuple[SuiteDefinition, tuple[EvaluationCase, ...]]:
    suite = SuiteDefinition.model_validate_json(path.read_text(encoding="utf-8"))
    cases = tuple(
        EvaluationCase.model_validate_json((path.parent / case_file).read_text(encoding="utf-8"))
        for case_file in suite.case_files
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
    ):
        raise ValueError("final suite requires four workers, 120-second timeout, and one infrastructure rerun")
    expected_variants = (
        {HarnessVariant.V1}
        if suite.profile.value == "smoke"
        else {HarnessVariant.V0, HarnessVariant.V1}
    )
    for case in cases:
        if case.kind is CaseKind.END_TO_END and {
            run.harness_variant for run in case.runs
        } != expected_variants:
            raise ValueError(
                f"{suite.profile.value} end-to-end task requires variants "
                f"{sorted(item.value for item in expected_variants)}"
            )
    return suite, cases


def _resume_projection(summary: EvaluationSummary) -> str:
    lines = [
            "# MOMO TechScout evaluation evidence",
            "",
            f"- Profile: `{summary.profile.value}`",
            f"- Recovery Success: `{summary.recovery_success_count}/{summary.recovery_attempt_count}`",
    ]
    for variant, metrics in summary.task_metrics.items():
        lines.extend(
            [
                f"- {variant.value.upper()} Task Success: `{metrics.task_success_count}/{metrics.task_count}`",
                f"- {variant.value.upper()} First-pass Success: `{metrics.first_pass_success_count}/{metrics.task_count}`",
                f"- {variant.value.upper()} Cold-live latency p50/p95 ms: `{metrics.latency['cold_live'].p50_ms}/{metrics.latency['cold_live'].p95_ms}`",
                f"- {variant.value.upper()} Warm-cache latency p50/p95 ms: `{metrics.latency['warm_cache'].p50_ms}/{metrics.latency['warm_cache'].p95_ms}`",
            ]
        )
    lines.extend(
        [
            "",
            "Cold-live and warm-cache observations are intentionally not combined.",
            "Synthetic smoke results are acceptance evidence, not live benchmark claims.",
            "",
        ]
    )
    return "\n".join(lines)


def run_evaluation_suite(
    suite_path: Path,
    output_dir: Path,
    *,
    environment: EvaluationEnvironment,
) -> EvaluationSummary:
    """Run one frozen suite once and publish a sealed, non-overwritable package."""
    suite, cases = _load_suite(suite_path)
    if environment.executor_version != suite.executor_version:
        raise ValueError("environment executor version does not match frozen suite")
    builder = EvidencePackageBuilder(output_dir)
    recorder = TechScoutTraceRecorder(
        output_dir / "traces.jsonl",
        run_id=suite.suite_id,
    )
    for case in cases:
        for run in case.runs:
            recorder.record(
                TraceEventName.VALIDATION_COMPLETED,
                status="ok" if run.task_checks.passed else "error",
                attributes={
                    "gate_outcome": "passed" if run.task_checks.passed else "failed",
                    "checked_constraint_count": 6,
                    "failure_count": 0 if run.task_checks.passed else 1,
                },
            )
            recorder.record(
                TraceEventName.TERMINAL_COMPLETED,
                status="ok" if run.task_checks.passed else "error",
                attributes={
                    "terminal_status": "completed",
                    "gate_outcome": "passed" if run.task_checks.passed else "failed",
                    "latency_ms": run.latency_ms,
                    "prompt_tokens": run.prompt_tokens,
                    "completion_tokens": run.completion_tokens,
                    "total_tokens": run.prompt_tokens + run.completion_tokens,
                    "retry_count": run.retry_count,
                    "recovery_count": run.recovery_stages,
                },
            )
    recorder.seal()
    summary = summarize(suite, cases)
    builder.write_json("environment.json", environment.model_dump(mode="json"))
    builder.write_json("resolved-config.json", suite.model_dump(mode="json"))
    builder.write_text(
        "case-metrics.jsonl",
        "".join(
            json.dumps(case.model_dump(mode="json"), sort_keys=True, separators=(",", ":")) + "\n"
            for case in cases
        ),
    )
    builder.write_json("eval-summary.json", summary.model_dump(mode="json"))
    builder.write_text("resume-evidence.md", _resume_projection(summary))
    builder.seal(
        package_kind="momo-techscout-evaluation-v1",
        required_artifacts=_PACKAGE_ARTIFACTS,
        manifest_metadata={
            "suite_id": suite.suite_id,
            "profile": suite.profile.value,
            "sealed_once": True,
            "fixture_authority": "synthetic" if suite.profile.value == "smoke" else "final",
            "runner_completed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        },
    )
    return summary
