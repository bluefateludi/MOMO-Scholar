from paper_agent.eval.citation_baseline.report import render_citation_reports


def _stats() -> dict[str, object]:
    """Mimics score_citation_baseline output structure."""
    return {
        "bootstrap": {
            "method": "case_percentile",
            "confidence_level": 0.95,
            "resamples": 10_000,
            "seed": 20_260_726,
        },
        "aggregate": {
            "citation_coverage": {
                "macro_mean": 0.85,
                "case_denominator": 20,
                "ci_95_low": 0.70,
                "ci_95_high": 0.95,
            },
            "citation_validity": {
                "macro_mean": 0.90,
                "case_denominator": 20,
                "ci_95_low": 0.75,
                "ci_95_high": 0.95,
            },
            "unsupported_assertion_rate": {
                "macro_mean": 0.15,
                "case_denominator": 20,
                "ci_95_low": 0.05,
                "ci_95_high": 0.30,
            },
        },
        "assertion_status_counts": {
            "supported": 15,
            "unsupported": 3,
            "ambiguous": 1,
            "unscorable": 1,
        },
        "denominators": {
            "attempted_cases": 20,
            "completed_cases": 20,
            "assertions": 20,
            "citations": 20,
            "scorable_assertions": 18,
        },
        "operations": {
            "attempted": 20,
            "completed": 20,
            "failed": 0,
            "failure_rate": 0.0,
            "completed_latency_ms_p50": 5.0,
            "completed_latency_ms_p95": 10.0,
        },
    }


def _metadata(**updates: object) -> dict[str, object]:
    value = {
        "case_count": 20,
        "data_kind": "real",
        "git_sha": "a" * 40,
        "git_dirty": False,
        "sealed": True,
        "recomputed": True,
        "calibration_complete": True,
        "rubric_version": "rubric-v1",
        "calibration_set_version": "cal-v1",
        "calibration_raw_agreement": 0.9,
        "calibration_cohens_kappa": 0.75,
        "calibration_disagreement_count": 1,
        "calibration_unresolved_count": 0,
        "generation_model_version": "qwen-max@2026-07-01",
        "dataset_fingerprint_sha256": "b" * 64,
        "output_sha256": "c" * 64,
        "artifact_manifest_sha256": "d" * 64,
        "limitations": ["Licensed 20-case frozen corpus only."],
    }
    value.update(updates)
    return value


def test_report_contains_structure_semantics_calibration_and_operations() -> None:
    report, resume = render_citation_reports(_stats(), _metadata())

    # Structure table
    assert "## Structure" in report
    assert "Citation Coverage" in report
    assert "Citation Validity" in report
    assert "0.850000" in report
    assert "0.900000" in report
    assert "[0.700000, 0.950000]" in report

    # Semantics table
    assert "## Semantics" in report
    assert "Unsupported Assertion Rate" in report
    assert "0.150000" in report

    # Assertion status counts
    assert "Supported" in report
    assert "Ambiguous" in report
    assert "Unscorable" in report
    assert "never coerced" in report

    # Calibration
    assert "## Calibration" in report
    assert "0.900000" in report
    assert "0.750000" in report

    # Operations
    assert "## Operations" in report
    assert "0.000000" in report

    # Limitations and source hashes
    assert "Licensed 20-case frozen corpus only." in report
    assert ("b" * 12) in report
    assert ("d" * 12) in report

    # Resume
    assert "20 real cases" in resume
    assert "Citation Coverage" in resume
    assert "0.850000" in resume
    assert ("d" * 12) in resume


def test_resume_numbers_are_suppressed_when_authority_is_not_publishable() -> None:
    invalid = (
        {"data_kind": "synthetic"},
        {"case_count": 19},
        {"git_dirty": True},
        {"sealed": False},
        {"recomputed": False},
        {"calibration_complete": False},
    )
    for mutation in invalid:
        _, resume = render_citation_reports(_stats(), _metadata(**mutation))
        assert "No resume-ready numeric claims" in resume
        assert "0.850000" not in resume
