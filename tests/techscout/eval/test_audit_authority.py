import json
from pathlib import Path

from paper_agent.eval.evidence_package import verify_evidence_package
from paper_agent.techscout.eval.contracts import EvaluationSummary
from scripts.build_techscout_eval_audit_authority import build_audit_summary, main


ARTIFACTS = Path("docs/evaluations/artifacts")
FAILED = ARTIFACTS / "techscout-final-2026-08-09-FAILED_PRECHECK_AUTHORITY"
AMENDED = ARTIFACTS / "techscout-final-2026-08-09-AMENDED_AUTHORITY"
INDEX = ARTIFACTS / "techscout-final-2026-08-09-AUTHORITY_INDEX"
AUDIT = ARTIFACTS / "techscout-final-2026-08-09-FINAL_AUDIT_AUTHORITY"


def test_audit_summary_is_a_deterministic_projection_of_amended_observations():
    amended = EvaluationSummary.model_validate_json(
        (AMENDED / "eval-summary.json").read_text(encoding="utf-8")
    )
    authority = json.loads((AUDIT / "audit-summary.json").read_text(encoding="utf-8"))
    projected = build_audit_summary(
        amended,
        failed_manifest_sha256=authority["authority_manifest_sha256"]["failed_precheck"],
        amended_manifest_sha256=authority["authority_manifest_sha256"]["amended"],
        index_manifest_sha256=authority["authority_manifest_sha256"]["prior_index"],
    )
    assert projected == authority
    assert set(projected["resume_authoritative_metrics"].values()) == {None}


def test_audit_builder_seals_verifiable_package(tmp_path):
    output = tmp_path / "audit"
    main(FAILED, AMENDED, INDEX, output)
    manifest = verify_evidence_package(output)
    assert manifest["resume_metrics_authorized"] is False
    assert "No resume-ready numeric" in (output / "resume-evidence.md").read_text()
