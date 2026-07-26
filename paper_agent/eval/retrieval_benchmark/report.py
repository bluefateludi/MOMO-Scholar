from __future__ import annotations


def _short(value: object) -> str:
    return str(value)[:12]


def _publishable(metadata: dict[str, object]) -> tuple[bool, list[str]]:
    failures = []
    if metadata.get("data_kind") != "real":
        failures.append("dataset is not real")
    if metadata.get("case_count") != 40:
        failures.append("case count is not 40")
    if metadata.get("git_dirty") is not False:
        failures.append("Git worktree is dirty")
    if metadata.get("sealed") is not True:
        failures.append("evidence package is not sealed")
    if metadata.get("recomputed") is not True:
        failures.append("offline recomputation is incomplete")
    return not failures, failures


def render_retrieval_reports(
    statistics: dict[str, object], metadata: dict[str, object]
) -> tuple[str, str]:
    aggregate = statistics["aggregate"]
    paired = statistics["paired_deltas"]
    operations = statistics["operations"]
    lines = [
        "# Retrieval Benchmark Report",
        "",
        f"Cases: {metadata['case_count']} ({metadata['data_kind']})",
        f"K={{1,3,5,8,10}}",
        f"Primary K: {statistics['primary_k']}",
        f"Embedding model: {metadata['embedding_model_version']}",
        f"Git: `{metadata['git_sha']}` (dirty={str(metadata['git_dirty']).lower()})",
        f"Dataset fingerprint: `{_short(metadata['dataset_fingerprint_sha256'])}`",
        f"Corpus hash: `{_short(metadata['corpus_sha256'])}`",
        "",
        "## Recall@8",
        "",
        "| Mode | Macro recall |",
        "|---|---:|",
    ]
    for mode in ("keyword", "vector", "hybrid_rrf"):
        value = aggregate[mode]["8"]["recall_at_k"]
        lines.append(f"| {mode} | {value:.6f} |")
    lines.extend(["", "## Paired comparisons", ""])
    for comparison in (
        "hybrid_rrf_minus_keyword",
        "hybrid_rrf_minus_vector",
    ):
        value = paired[comparison]["8"]["recall_at_k"]
        lines.append(
            f"- {comparison}: {value['mean_delta']:+.6f}, "
            f"95% CI [{value['ci_95_low']:.6f}, {value['ci_95_high']:.6f}], "
            f"n={value['paired_case_count']}"
        )
    lines.extend(
        [
            "",
            "## Latency and failures",
            "",
            "| Mode | p50 ms | p95 ms | Failed/attempted | Failure rate |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for mode in ("keyword", "vector", "hybrid_rrf"):
        value = operations[mode]
        lines.append(
            f"| {mode} | {value['latency_ms_p50']:.3f} | "
            f"{value['latency_ms_p95']:.3f} | {value['failed']}/{value['attempted']} | "
            f"{value['failure_rate']:.6f} |"
        )
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in metadata.get("limitations", []))
    lines.extend(
        [
            "",
            f"Artifact manifest: `{_short(metadata['artifact_manifest_sha256'])}`",
            "",
        ]
    )

    allowed, blockers = _publishable(metadata)
    resume = ["# Resume Evidence", ""]
    if not allowed:
        resume.append("No resume-ready numeric claims.")
        resume.extend(f"- {blocker}" for blocker in blockers)
        resume.append("")
        return "\n".join(lines), "\n".join(resume)

    keyword = aggregate["keyword"]["8"]["recall_at_k"]
    vector = aggregate["vector"]["8"]["recall_at_k"]
    hybrid = aggregate["hybrid_rrf"]["8"]["recall_at_k"]
    manifest = _short(metadata["artifact_manifest_sha256"])
    for source, source_value, comparison in (
        ("Keyword", keyword, "hybrid_rrf_minus_keyword"),
        ("Vector-only", vector, "hybrid_rrf_minus_vector"),
    ):
        delta = paired[comparison]["8"]["recall_at_k"]
        resume.append(
            f"- On {metadata['case_count']} real cases, Hybrid+RRF Recall@8 was "
            f"{hybrid:.6f} versus {source} {source_value:.6f}: "
            f"{delta['mean_delta']:+.6f} paired delta, 95% CI "
            f"[{delta['ci_95_low']:.6f}, {delta['ci_95_high']:.6f}], "
            f"n={delta['paired_case_count']}; manifest `{manifest}`."
        )
    resume.append("")
    return "\n".join(lines), "\n".join(resume)


__all__ = ["render_retrieval_reports"]
