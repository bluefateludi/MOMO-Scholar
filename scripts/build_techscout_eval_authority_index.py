from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from paper_agent.eval.evidence_package import EvidencePackageBuilder, verify_evidence_package
from paper_agent.techscout.eval.contracts import EvaluationSummary, HarnessVariant


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(failed: Path, amended: Path, output: Path) -> None:
    failed_manifest = verify_evidence_package(failed)
    amended_manifest = verify_evidence_package(amended)
    amended_summary = EvaluationSummary.model_validate_json(
        (amended / "eval-summary.json").read_text(encoding="utf-8")
    )
    failed_manifest_path = failed / "artifact-manifest.json"
    amended_manifest_path = amended / "artifact-manifest.json"
    authority = {
        "schema_version": "techscout-final-eval-authority-index-v1",
        "baseline_git_commit": "b7516a7b478834614f6ce2ccf1ae63a5c73c3140",
        "attempts": [
            {
                "authority": "FAILED_PRECHECK_AUTHORITY",
                "complete": False,
                "reason": "frozen data authoring defect: duplicate hard constraint",
                "authoritative_observation_count": 0,
                "manifest_sha256": _sha256(failed_manifest_path),
            },
            {
                "authority": "AMENDED_AUTHORITY",
                "complete": True,
                "amendment": "deleted only the exact duplicate hard constraint",
                "manifest_sha256": _sha256(amended_manifest_path),
            },
        ],
        "amended_summary": amended_summary.model_dump(mode="json"),
        "further_full_reruns_authorized": False,
    }
    v0 = amended_summary.task_metrics[HarnessVariant.V0]
    v1 = amended_summary.task_metrics[HarnessVariant.V1]
    report = f"""# MOMO TechScout final evaluation authority

The original run is permanently retained as `FAILED_PRECHECK_AUTHORITY`. It
produced zero authoritative observations because a frozen-data authoring defect
duplicated one hard constraint. This was not a model or infrastructure result.

One transparent amended run was authorized after deleting only that duplicate.
No model, threshold, expected outcome, runner behavior, or other fixture changed.

- Amended N: `{amended_summary.e2e_case_count} E2E tasks / {amended_summary.e2e_run_count} V0+V1 observations, {amended_summary.retrieval_case_count} retrieval, {amended_summary.fault_case_count} fault`
- V0 Task Success / First-pass: `{v0.task_success_count}/{v0.task_count} / {v0.first_pass_success_count}/{v0.task_count}`
- V1 Task Success / First-pass: `{v1.task_success_count}/{v1.task_count} / {v1.first_pass_success_count}/{v1.task_count}`
- Fault Recovery Success: `{amended_summary.fault_recovery_success_count}/{amended_summary.fault_recovery_attempt_count}`
- Retrieval Recall@5 / version-filter accuracy: `{amended_summary.retrieval_recall_at_5} / {amended_summary.version_filter_accuracy}`
- V0 warm-cache p50/p95 ms: `{v0.latency['warm_cache'].p50_ms}/{v0.latency['warm_cache'].p95_ms}`
- V1 warm-cache p50/p95 ms: `{v1.latency['warm_cache'].p50_ms}/{v1.latency['warm_cache'].p95_ms}`
- Cold-live latency: `N/A (N=0; live network prohibited)`
- V0/V1 prompt tokens per successful task: `{v0.prompt_tokens_per_successful_task}/{v1.prompt_tokens_per_successful_task}`
- Estimated cost per successful task: `N/A`

No further full rerun is authorized.
"""
    builder = EvidencePackageBuilder(output)
    builder.write_json(
        "environment.json",
        {
            "git_dirty": False,
            "models": {"index_builder": "deterministic-v1"},
            "network_policy": "offline",
        },
    )
    builder.write_text("failed-authority-manifest.json", failed_manifest_path.read_text(encoding="utf-8"))
    builder.write_text("amended-authority-manifest.json", amended_manifest_path.read_text(encoding="utf-8"))
    builder.write_json("authority-summary.json", authority)
    builder.write_text("authority-summary.md", report)
    builder.seal(
        package_kind="momo-techscout-final-evaluation-authority-index-v1",
        required_artifacts={
            "environment.json",
            "failed-authority-manifest.json",
            "amended-authority-manifest.json",
            "authority-summary.json",
            "authority-summary.md",
        },
        manifest_metadata={
            "failed_package_kind": failed_manifest["package_kind"],
            "amended_package_kind": amended_manifest["package_kind"],
            "full_run_attempt_count": 2,
        },
    )


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
