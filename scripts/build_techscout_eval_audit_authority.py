from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from paper_agent.eval.evidence_package import EvidencePackageBuilder, verify_evidence_package


def _manifest(root: Path) -> tuple[dict[str, object], Path, str]:
    manifest = verify_evidence_package(root)
    path = root / "artifact-manifest.json"
    return manifest, path, hashlib.sha256(path.read_bytes()).hexdigest()


def main(failed: Path, amended: Path, index: Path, output: Path) -> None:
    failed_manifest, failed_path, failed_sha = _manifest(failed)
    amended_manifest, amended_path, amended_sha = _manifest(amended)
    index_manifest, index_path, index_sha = _manifest(index)
    summary = {
        "schema_version": "techscout-final-eval-audit-authority-v1",
        "status": "COMPLETE_SYNTHETIC_ACCEPTANCE_NOT_RESUME_METRICS",
        "completed_population": {
            "end_to_end_tasks": 12,
            "v0_v1_observations": 24,
            "retrieval_cases": 40,
            "fault_cases": 8,
        },
        "recorded_synthetic_diagnostics": {
            "v0_task_success": "12/12",
            "v1_task_success": "12/12",
            "v0_first_pass": "12/12",
            "v1_first_pass": "12/12",
            "fault_recovery": "6/8",
            "retrieval_recall_at_5": 0.9,
            "version_filter_accuracy": 0.925,
            "v0_warm_cache_p50_p95_ms": [235, 265],
            "v1_warm_cache_p50_p95_ms": [250, 296],
        },
        "resume_authoritative_metrics": {
            "task_success": None,
            "first_pass_success": None,
            "recovery_success": None,
            "retrieval_recall_at_5": None,
            "retries": None,
            "tokens": None,
            "cold_live_latency": None,
            "warm_cache_latency": None,
            "cost": None,
        },
        "audit_reason": (
            "Rankings, recovery outcomes, token counts, and E2E services were authored "
            "as synthetic fixtures; they are acceptance diagnostics, not independent observations."
        ),
        "full_run_attempt_count": 2,
        "further_full_reruns_authorized": False,
        "authority_manifest_sha256": {
            "failed_precheck": failed_sha,
            "amended": amended_sha,
            "prior_index": index_sha,
        },
    }
    report = """# MOMO TechScout final evaluation audit authority

The amended runner completed 12 E2E tasks (24 V0/V1 observations), 40 retrieval
cases, and eight fault cases. The recorded values remain preserved, but audit
found that rankings, fault outcomes, token counts, and E2E services were authored
as synthetic fixture behavior. They are acceptance diagnostics and must not be
presented as independent model, product, cold-live, cost, or resume measurements.

Resume-authoritative Task Success, First-pass, Recovery, Recall@5, retries,
tokens, latency, and cost are therefore all `N/A`.

The original `FAILED_PRECHECK_AUTHORITY`, amended package, and prior authority
index remain byte-for-byte preserved. No further complete run is authorized.
"""
    resume = """# MOMO TechScout resume metrics authority

- Completed synthetic population: `12 E2E / 24 V0+V1 / 40 retrieval / 8 fault`
- Task Success / First-pass / Recovery / Recall@5: `N/A`
- Retries / Tokens / Cold-live latency / Warm-cache latency / Cost: `N/A`

No resume-ready numeric performance claim is authorized. Recorded synthetic
acceptance diagnostics remain available only in the referenced amended package.
"""
    builder = EvidencePackageBuilder(output)
    builder.write_json(
        "environment.json",
        {"git_dirty": False, "models": {"audit": "deterministic-v1"}, "network_policy": "offline"},
    )
    builder.write_text("failed-authority-manifest.json", failed_path.read_text(encoding="utf-8"))
    builder.write_text("amended-authority-manifest.json", amended_path.read_text(encoding="utf-8"))
    builder.write_text("prior-index-manifest.json", index_path.read_text(encoding="utf-8"))
    builder.write_json("audit-summary.json", summary)
    builder.write_text("audit-summary.md", report)
    builder.write_text("resume-evidence.md", resume)
    builder.seal(
        package_kind="momo-techscout-final-evaluation-audit-authority-v1",
        required_artifacts={
            "environment.json",
            "failed-authority-manifest.json",
            "amended-authority-manifest.json",
            "prior-index-manifest.json",
            "audit-summary.json",
            "audit-summary.md",
            "resume-evidence.md",
        },
        manifest_metadata={
            "failed_package_kind": failed_manifest["package_kind"],
            "amended_package_kind": amended_manifest["package_kind"],
            "prior_index_package_kind": index_manifest["package_kind"],
            "resume_metrics_authorized": False,
        },
    )


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
