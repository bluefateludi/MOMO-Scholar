from paper_agent.eval.retrieval_benchmark.report import render_retrieval_reports


def _stats() -> dict[str, object]:
    metric = {
        "mean_delta": 0.125,
        "paired_case_count": 40,
        "ci_95_low": 0.025,
        "ci_95_high": 0.225,
    }
    return {
        "ks": [1, 3, 5, 8, 10],
        "primary_k": 8,
        "aggregate": {
            "keyword": {"8": {"recall_at_k": 0.5}},
            "vector": {"8": {"recall_at_k": 0.55}},
            "hybrid_rrf": {"8": {"recall_at_k": 0.625}},
        },
        "paired_deltas": {
            "hybrid_rrf_minus_keyword": {"8": {"recall_at_k": metric}},
            "hybrid_rrf_minus_vector": {
                "8": {"recall_at_k": {**metric, "mean_delta": 0.075}}
            },
        },
        "operations": {
            mode: {
                "attempted": 40,
                "completed": 40,
                "failed": 0,
                "failure_rate": 0.0,
                "latency_ms_p50": latency,
                "latency_ms_p95": latency * 2,
            }
            for mode, latency in (("keyword", 5.0), ("vector", 50.0), ("hybrid_rrf", 55.0))
        },
    }


def _metadata(**updates: object) -> dict[str, object]:
    value = {
        "case_count": 40,
        "data_kind": "real",
        "git_sha": "a" * 40,
        "git_dirty": False,
        "sealed": True,
        "recomputed": True,
        "dataset_fingerprint_sha256": "b" * 64,
        "corpus_sha256": "c" * 64,
        "embedding_model_version": "text-embedding-v4@2026-07-01",
        "artifact_manifest_sha256": "d" * 64,
        "limitations": ["Licensed 40-case frozen corpus only."],
    }
    value.update(updates)
    return value


def test_report_contains_configuration_metrics_operations_and_sources() -> None:
    report, resume = render_retrieval_reports(_stats(), _metadata())

    assert "K={1,3,5,8,10}" in report
    assert "Primary K: 8" in report
    assert "text-embedding-v4@2026-07-01" in report
    assert "Latency and failures" in report
    assert "Licensed 40-case frozen corpus only." in report
    assert ("b" * 12) in report
    assert ("c" * 12) in report
    assert "40 real cases" in resume
    assert "Recall@8" in resume
    assert "+0.125000" in resume
    assert "95% CI [0.025000, 0.225000]" in resume
    assert ("d" * 12) in resume


def test_resume_numbers_are_suppressed_when_authority_is_not_publishable() -> None:
    invalid = (
        {"data_kind": "synthetic"},
        {"case_count": 39},
        {"git_dirty": True},
        {"sealed": False},
        {"recomputed": False},
    )
    for mutation in invalid:
        _, resume = render_retrieval_reports(_stats(), _metadata(**mutation))
        assert "No resume-ready numeric claims" in resume
        assert "+0.125000" not in resume
