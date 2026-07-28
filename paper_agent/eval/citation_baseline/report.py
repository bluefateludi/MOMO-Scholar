from __future__ import annotations

from typing import cast


def _short(value: object) -> str:
    return str(value)[:12]


def _number(value: object, *, digits: int) -> str:
    if not isinstance(value, (int, float)):
        return "n/a"
    return format(value, f".{digits}f")


def _publishable(metadata: dict[str, object]) -> tuple[bool, list[str]]:
    failures: list[str] = []
    if metadata.get("data_kind") != "real":
        failures.append("dataset is not real")
    if metadata.get("case_count") != 20:
        failures.append("case count is not 20")
    if metadata.get("git_dirty") is not False:
        failures.append("Git worktree is dirty")
    if metadata.get("sealed") is not True:
        failures.append("evidence package is not sealed")
    if metadata.get("recomputed") is not True:
        failures.append("offline recomputation is incomplete")
    if metadata.get("calibration_complete") is not True:
        failures.append("human review calibration is incomplete")
    return not failures, failures


def _metric_row(
    label: str,
    entry: dict[str, object],
) -> str:
    macro = _number(entry.get("macro_mean"), digits=6)
    low = _number(entry.get("ci_95_low"), digits=6)
    high = _number(entry.get("ci_95_high"), digits=6)
    cases = entry.get("case_denominator", "n/a")
    return (
        f"| {label} | {macro} | [{low}, {high}] | {cases} |"
    )


def render_citation_reports(
    statistics: dict[str, object],
    metadata: dict[str, object],
) -> tuple[str, str]:
    aggregate = cast(dict[str, dict[str, object]], statistics["aggregate"])
    status_counts = cast(
        dict[str, int], statistics["assertion_status_counts"]
    )
    denominators = cast(dict[str, int], statistics["denominators"])
    operations = cast(dict[str, object], statistics["operations"])

    lines: list[str] = [
        "# Citation Quality Baseline Report",
        "",
        f"Cases: {metadata['case_count']} ({metadata['data_kind']})",
        f"Rubric: {metadata['rubric_version']} "
        f"(calibration: {metadata['calibration_set_version']})",
        f"Generation model: {metadata['generation_model_version']}",
        f"Git: `{metadata['git_sha']}` "
        f"(dirty={str(metadata['git_dirty']).lower()})",
        f"Dataset fingerprint: `{_short(metadata['dataset_fingerprint_sha256'])}`",
        f"Output hash: `{_short(metadata['output_sha256'])}`",
        "",
        "## Structure",
        "",
        "| Metric | Macro mean | 95% CI | Cases |",
        "|---|---:|---|---:|",
        _metric_row("Citation Coverage", aggregate["citation_coverage"]),
        _metric_row("Citation Validity", aggregate["citation_validity"]),
        "",
        f"Denominators: {denominators['assertions']} assertions, "
        f"{denominators['citations']} citations.",
        "",
        "## Semantics",
        "",
        "| Metric | Macro mean | 95% CI | Cases |",
        "|---|---:|---|---:|",
        _metric_row(
            "Unsupported Assertion Rate",
            aggregate["unsupported_assertion_rate"],
        ),
        "",
        "| Status | Count |",
        "|---|---:|",
        f"| Supported | {status_counts['supported']} |",
        f"| Unsupported | {status_counts['unsupported']} |",
        f"| Ambiguous | {status_counts['ambiguous']} |",
        f"| Unscorable | {status_counts['unscorable']} |",
        "",
        "Ambiguous and unscorable assertions are reported separately "
        "and never coerced to supported or unsupported.",
        "",
        "## Calibration",
        "",
        "| Statistic | Value |",
        "|---|---:|",
        f"| Raw agreement | {_number(metadata['calibration_raw_agreement'], digits=6)} |",
        f"| Cohen's kappa | {_number(metadata['calibration_cohens_kappa'], digits=6)} |",
        f"| Disagreements | {metadata['calibration_disagreement_count']} |",
        f"| Unresolved | {metadata['calibration_unresolved_count']} |",
        "",
        "## Operations",
        "",
        "| Attempted | Completed | Failed | Failure rate | p50 ms | p95 ms |",
        "|---:|---:|---:|---:|---:|---:|",
        f"| {operations['attempted']} | {operations['completed']} | "
        f"{operations['failed']} | {_number(operations['failure_rate'], digits=6)} | "
        f"{_number(operations['completed_latency_ms_p50'], digits=3)} | "
        f"{_number(operations['completed_latency_ms_p95'], digits=3)} |",
        "",
        "## Limitations",
        "",
    ]
    limitations = cast(list[str], metadata.get("limitations", []))
    lines.extend(f"- {item}" for item in limitations)
    lines.extend(
        [
            "",
            f"Artifact manifest: `{_short(metadata['artifact_manifest_sha256'])}`",
            "",
        ]
    )

    allowed, blockers = _publishable(metadata)
    resume: list[str] = ["# Resume Evidence", ""]
    if not allowed:
        resume.append("No resume-ready numeric claims.")
        resume.extend(f"- {blocker}" for blocker in blockers)
        resume.append("")
        return "\n".join(lines), "\n".join(resume)

    manifest = _short(metadata["artifact_manifest_sha256"])
    case_count = metadata["case_count"]
    for label, key, denom_key in (
        ("Citation Coverage", "citation_coverage", "assertions"),
        ("Citation Validity", "citation_validity", "citations"),
        ("Unsupported Assertion Rate", "unsupported_assertion_rate", "scorable_assertions"),
    ):
        entry = aggregate[key]
        macro = _number(entry.get("macro_mean"), digits=6)
        low = _number(entry.get("ci_95_low"), digits=6)
        high = _number(entry.get("ci_95_high"), digits=6)
        cases = entry.get("case_denominator")
        denom = denominators[denom_key]
        resume.append(
            f"- On {case_count} real cases, {label} was {macro}, "
            f"95% CI [{low}, {high}], n={cases} cases, "
            f"{denom} {denom_key}; manifest `{manifest}`."
        )
    resume.append("")
    return "\n".join(lines), "\n".join(resume)


__all__ = ["render_citation_reports"]
