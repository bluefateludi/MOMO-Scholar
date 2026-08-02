from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path

import httpx
import typer
from pydantic import ValidationError

from paper_agent.config import load_settings
from paper_agent.eval.evidence_package import (
    EvidencePackageBuilder,
    EvidencePackageError,
    verify_evidence_package,
)
from paper_agent.generation import DashScopeChatTransport, DashScopeGenerationProvider

from .live_generation import (
    BudgetedDashScopeTransport,
    LiveGenerationConfig,
    create_campaign_ledger,
    load_provider_model_authority,
    preflight_live_generation,
    run_live_generation,
)
from .automated_judge import (
    AutomatedJudgeAuthority,
    AutomatedJudgeError,
    AutomatedJudgeInput,
    DashScopeAutomatedJudgeProvider,
    inspect_frozen_generation,
    recompute_automated_citation_package,
    run_automated_judge,
    seal_automated_citation_package,
    verify_automated_citation_package,
)

from .contracts import (
    AtomicAssertion,
    CalibrationRecord,
    CitationOccurrence,
    EvidenceMatch,
    SupportJudgment,
)
from .metrics import CitationCaseInput, score_citation_baseline
from .report import render_citation_reports
from .review import (
    AdjudicationRecord,
    ReviewAssignment,
    ReviewIntegrityError,
    calibration_statistics,
    export_response_template_jsonl,
    export_review_jsonl,
    freeze_rubric,
    import_review_jsonl,
    judgments_for_scoring,
    merge_review_judgments,
    require_scoring_ready,
)


app = typer.Typer(help="Prepare, review, score, and verify citation baselines.")

_EXIT_REVIEW = 1
_EXIT_INPUT = 2
_EXIT_INTEGRITY = 3
_PACKAGE_KIND = "citation_baseline"
_SECRET_PATTERN = re.compile(
    r"(?i)(?:api[_-]?key|authorization|bearer\s+[a-z0-9._-]+|sk-[a-z0-9])"
)
_PREPARED_JSON = (
    "dataset-manifest.json",
    "corpus-manifest.json",
    "resolved-config.json",
    "environment.json",
)
_PREPARED_JSONL = (
    "gold-judgments.jsonl",
    "assertions.jsonl",
    "citation-occurrences.jsonl",
    "evidence-matches.jsonl",
    "calibration.jsonl",
    "adjudications.jsonl",
    "failures.jsonl",
    "logs.jsonl",
    "traces.jsonl",
)
_AUTHORITY_FILES = (
    "dataset-manifest.json",
    "corpus-manifest.json",
    "gold-judgments.jsonl",
    "resolved-config.json",
    "environment.json",
    "assertions.jsonl",
    "citation-occurrences.jsonl",
    "evidence-matches.jsonl",
    "review-rubric.json",
    "calibration.jsonl",
    "judgments.jsonl",
    "adjudications.jsonl",
    "failures.jsonl",
)
_PROJECTION_FILES = (
    "case-metrics.jsonl",
    "aggregate.json",
    "confidence-intervals.json",
    "report.md",
    "resume-evidence.md",
)


def _canonical_json(value: object) -> str:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )


def _jsonl(values: Iterable[object]) -> str:
    return "".join(
        _canonical_json(
            value.model_dump(mode="json")
            if hasattr(value, "model_dump")
            else value
        )
        for value in values
    )


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8", newline="\n")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _git_environment() -> dict[str, object]:
    def git(*args: str) -> str:
        result = subprocess.run(
            ("git", *args),
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return result.stdout.strip()

    return {
        "git_sha": git("rev-parse", "HEAD"),
        "git_dirty": bool(git("status", "--porcelain")),
        "python_version": sys.version.split()[0],
    }


def _new_directory(path: Path) -> None:
    if path.exists():
        raise ValueError("output path already exists")
    path.mkdir(parents=True)


def _read_text(path: Path) -> str:
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ValueError(f"{path.name} is missing or invalid") from error
    if _SECRET_PATTERN.search(content):
        raise ValueError(f"{path.name} contains forbidden secret material")
    return content


def _load_json(path: Path) -> object:
    try:
        return json.loads(_read_text(path))
    except json.JSONDecodeError as error:
        raise ValueError(f"{path.name} is invalid JSON") from error


def _load_jsonl(path: Path) -> list[object]:
    values: list[object] = []
    for line_number, line in enumerate(_read_text(path).splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"{path.name} contains invalid JSON at line {line_number}"
            ) from error
        if not isinstance(value, dict):
            raise ValueError(f"{path.name} rows must be JSON objects")
        values.append(value)
    return values


def _load_models(path: Path, model: type) -> tuple:
    return tuple(model.model_validate(value) for value in _load_jsonl(path))


def _load_assignments(root: Path) -> tuple[ReviewAssignment, ...]:
    payload = _load_json(root / "review-rubric.json")
    if not isinstance(payload, dict):
        raise ValueError("review-rubric.json must be an object")
    required = {
        "schema_version",
        "rubric_version",
        "calibration_set_version",
        "rubric_sha256",
        "definitions",
        "reason_codes",
        "assignments",
    }
    if set(payload) != required or payload.get("schema_version") != "1.0":
        raise ValueError("review-rubric.json has an invalid schema")
    rubric_version = payload.get("rubric_version")
    calibration_version = payload.get("calibration_set_version")
    if not isinstance(rubric_version, str) or not isinstance(
        calibration_version, str
    ):
        raise ValueError("review rubric versions are invalid")
    rubric = freeze_rubric(rubric_version, calibration_version)
    if (
        payload.get("rubric_sha256") != rubric.rubric_sha256
        or payload.get("definitions") != dict(rubric.definitions)
        or payload.get("reason_codes")
        != {key: list(value) for key, value in rubric.reason_codes.items()}
    ):
        raise ReviewIntegrityError("review rubric changed after freeze")
    raw_assignments = payload.get("assignments")
    if not isinstance(raw_assignments, list):
        raise ValueError("review assignment registry is invalid")
    assignments = tuple(
        ReviewAssignment.model_validate(value) for value in raw_assignments
    )
    export_review_jsonl(assignments)
    if any(
        assignment.rubric_version != rubric.rubric_version
        or assignment.calibration_set_version != rubric.calibration_set_version
        or assignment.rubric_sha256 != rubric.rubric_sha256
        for assignment in assignments
    ):
        raise ReviewIntegrityError("assignment rubric authority mismatch")
    return assignments


def _validate_authority_links(
    assertions: Sequence[AtomicAssertion],
    occurrences: Sequence[CitationOccurrence],
    matches: Sequence[EvidenceMatch],
    assignments: Sequence[ReviewAssignment],
) -> None:
    assertion_by_id = {item.assertion_id: item for item in assertions}
    occurrence_by_id = {item.occurrence_id: item for item in occurrences}
    match_ids = {item.match_id for item in matches}
    if len(assertion_by_id) != len(assertions):
        raise ValueError("assertion IDs must be unique")
    if len(occurrence_by_id) != len(occurrences):
        raise ValueError("citation occurrence IDs must be unique")
    if len(match_ids) != len(matches):
        raise ValueError("evidence match IDs must be unique")
    if any(item.assertion_id not in assertion_by_id for item in occurrences):
        raise ValueError("citation occurrence assertion reference is dangling")
    if any(
        item.assertion_id not in assertion_by_id
        or item.citation_occurrence_id not in occurrence_by_id
        or occurrence_by_id[item.citation_occurrence_id].assertion_id
        != item.assertion_id
        for item in matches
    ):
        raise ValueError("evidence match reference is dangling")

    assignment_keys: set[tuple[str, str]] = set()
    assignment_counts: dict[str, int] = {}
    calibration_state: dict[str, bool] = {}
    for assignment in assignments:
        item = assignment.item
        assertion = assertion_by_id.get(item.assertion_id)
        if assertion is None:
            raise ReviewIntegrityError("assignment assertion reference is dangling")
        expected_occurrences = tuple(
            occurrence.occurrence_id
            for occurrence in occurrences
            if occurrence.assertion_id == assertion.assertion_id
        )
        if (
            item.case_id != assertion.case_id
            or item.run_id != assertion.run_id
            or item.assertion_text != assertion.text
            or item.citation_occurrence_ids != expected_occurrences
        ):
            raise ReviewIntegrityError("assignment changed frozen assertion authority")
        key = (item.assertion_id, assignment.reviewer_pseudonym)
        if key in assignment_keys:
            raise ReviewIntegrityError("assignment registry contains duplicates")
        assignment_keys.add(key)
        assignment_counts[item.assertion_id] = assignment_counts.get(item.assertion_id, 0) + 1
        previous = calibration_state.setdefault(item.assertion_id, item.is_calibration)
        if previous != item.is_calibration:
            raise ReviewIntegrityError("assignment calibration state is inconsistent")
    for assertion_id, count in assignment_counts.items():
        expected = 2 if calibration_state[assertion_id] else 1
        if count != expected:
            raise ReviewIntegrityError("assignment reviewer count is incomplete")


def _load_authorities(root: Path, *, judgments: Path | None = None) -> dict[str, object]:
    assertions = _load_models(root / "assertions.jsonl", AtomicAssertion)
    occurrences = _load_models(
        root / "citation-occurrences.jsonl", CitationOccurrence
    )
    matches = _load_models(root / "evidence-matches.jsonl", EvidenceMatch)
    assignments = _load_assignments(root)
    calibration = _load_models(root / "calibration.jsonl", CalibrationRecord)
    adjudications = _load_models(
        root / "adjudications.jsonl", AdjudicationRecord
    )
    judgment_path = judgments if judgments is not None else root / "judgments.jsonl"
    loaded_judgments = _load_models(judgment_path, SupportJudgment)
    _validate_authority_links(assertions, occurrences, matches, assignments)
    return {
        "assertions": assertions,
        "occurrences": occurrences,
        "matches": matches,
        "assignments": assignments,
        "calibration": calibration,
        "adjudications": adjudications,
        "judgments": loaded_judgments,
    }


def _case_specs(root: Path) -> tuple[dict[str, object], ...]:
    config = _load_json(root / "resolved-config.json")
    if not isinstance(config, dict) or config.get("schema_version") != "1.0":
        raise ValueError("resolved-config.json has an invalid schema")
    raw_cases = config.get("cases")
    if not isinstance(raw_cases, list):
        raise ValueError("resolved configuration requires cases")
    cases: list[dict[str, object]] = []
    seen: set[str] = set()
    for value in raw_cases:
        if not isinstance(value, dict) or set(value) != {
            "case_id",
            "duration_ms",
            "unscorable_assertion_ids",
            "failure_reason_code",
        }:
            raise ValueError("resolved case configuration is invalid")
        case_id = value.get("case_id")
        duration = value.get("duration_ms")
        unscorable = value.get("unscorable_assertion_ids")
        failure = value.get("failure_reason_code")
        if (
            not isinstance(case_id, str)
            or not case_id.strip()
            or case_id in seen
            or isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or duration < 0
            or not isinstance(unscorable, list)
            or any(not isinstance(item, str) or not item.strip() for item in unscorable)
            or len(unscorable) != len(set(unscorable))
            or (failure is not None and (not isinstance(failure, str) or not failure.strip()))
        ):
            raise ValueError("resolved case configuration is invalid")
        seen.add(case_id)
        cases.append(value)
    return tuple(cases)


def _calibration(
    assignments: Sequence[ReviewAssignment],
    records: Sequence[CalibrationRecord],
):
    expected = tuple(
        sorted(
            {
                assignment.item.assertion_id
                for assignment in assignments
                if assignment.item.is_calibration
            }
        )
    )
    return calibration_statistics(records, expected_assertion_ids=expected)


def _scoring_judgments(
    judgments: Sequence[SupportJudgment],
    assignments: Sequence[ReviewAssignment],
    calibration: object,
) -> tuple[SupportJudgment, ...]:
    require_scoring_ready(calibration)
    expected = {
        (assignment.item.assertion_id, assignment.reviewer_pseudonym)
        for assignment in assignments
    }
    actual = {
        (judgment.assertion_id, judgment.reviewer_pseudonym)
        for judgment in judgments
    }
    if len(actual) != len(judgments) or actual != expected:
        raise ReviewIntegrityError("judgment set is incomplete or duplicated")
    return judgments_for_scoring(judgments, assignments, calibration)


def _citation_cases(
    root: Path,
    authorities: dict[str, object],
    judgments: Sequence[SupportJudgment],
) -> tuple[CitationCaseInput, ...]:
    assertions = authorities["assertions"]
    occurrences = authorities["occurrences"]
    matches = authorities["matches"]
    assignments = authorities["assignments"]
    assert isinstance(assertions, tuple)
    assert isinstance(occurrences, tuple)
    assert isinstance(matches, tuple)
    assert isinstance(assignments, tuple)
    calibration_ids = {
        assignment.item.assertion_id
        for assignment in assignments
        if assignment.item.is_calibration
    }
    cases: list[CitationCaseInput] = []
    configured_ids: set[str] = set()
    for spec in _case_specs(root):
        case_id = str(spec["case_id"])
        configured_ids.add(case_id)
        failure = spec["failure_reason_code"]
        if failure is not None:
            cases.append(
                CitationCaseInput(
                    case_id=case_id,
                    failure_reason_code=str(failure),
                    duration_ms=float(spec["duration_ms"]),
                )
            )
            continue
        case_assertions = tuple(
            item
            for item in assertions
            if item.case_id == case_id and item.assertion_id not in calibration_ids
        )
        assertion_ids = {item.assertion_id for item in case_assertions}
        cases.append(
            CitationCaseInput(
                case_id=case_id,
                assertions=case_assertions,
                citation_occurrences=tuple(
                    item for item in occurrences if item.assertion_id in assertion_ids
                ),
                evidence_matches=tuple(
                    item for item in matches if item.assertion_id in assertion_ids
                ),
                judgments=tuple(
                    item for item in judgments if item.assertion_id in assertion_ids
                ),
                unscorable_assertion_ids=tuple(spec["unscorable_assertion_ids"]),
                duration_ms=float(spec["duration_ms"]),
            )
        )
    reported_cases = {
        item.case_id for item in assertions if item.assertion_id not in calibration_ids
    }
    if not reported_cases <= configured_ids:
        raise ValueError("reported assertions are missing resolved case configuration")
    return tuple(cases)


def _authority_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for name in sorted(_AUTHORITY_FILES):
        content = (root / name).read_bytes()
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content)
    return digest.hexdigest()


def _report_metadata(
    root: Path,
    statistics: dict[str, object],
    calibration: object,
) -> dict[str, object]:
    dataset = _load_json(root / "dataset-manifest.json")
    environment = _load_json(root / "environment.json")
    config = _load_json(root / "resolved-config.json")
    if not isinstance(dataset, dict) or not isinstance(environment, dict) or not isinstance(config, dict):
        raise ValueError("citation package metadata is invalid")
    models = environment.get("models")
    generation_model = config.get("generation_model_version")
    if not isinstance(generation_model, str) and isinstance(models, dict):
        generation_model = models.get("generation")
    if not isinstance(generation_model, str) or not generation_model.strip():
        raise ValueError("generation model version is missing")
    fingerprint = dataset.get("dataset_fingerprint_sha256", "0" * 64)
    if not isinstance(fingerprint, str):
        raise ValueError("dataset fingerprint is invalid")
    authority_hash = _authority_sha256(root)
    case_count = statistics["denominators"]["attempted_cases"]
    return {
        "case_count": case_count,
        "data_kind": dataset.get("data_kind", "synthetic"),
        "git_sha": environment.get("git_sha", "unknown"),
        "git_dirty": environment.get("git_dirty"),
        "sealed": True,
        "recomputed": True,
        "calibration_complete": calibration.complete,
        "rubric_version": calibration.rubric_version,
        "calibration_set_version": calibration.calibration_set_version,
        "calibration_raw_agreement": calibration.raw_agreement,
        "calibration_cohens_kappa": calibration.cohens_kappa,
        "calibration_disagreement_count": len(calibration.disagreement_assertion_ids),
        "calibration_unresolved_count": len(calibration.unresolved_assertion_ids),
        "generation_model_version": generation_model,
        "dataset_fingerprint_sha256": fingerprint,
        "output_sha256": config.get("output_sha256", authority_hash),
        "artifact_manifest_sha256": authority_hash,
        "limitations": config.get("limitations", []),
    }


def _projections(
    root: Path,
    statistics: dict[str, object],
    calibration: object,
) -> dict[str, str]:
    aggregate = {
        "aggregate": statistics["aggregate"],
        "assertion_status_counts": statistics["assertion_status_counts"],
        "denominators": statistics["denominators"],
        "operations": statistics["operations"],
    }
    confidence = {
        "bootstrap": statistics["bootstrap"],
        "aggregate_ci_95": {
            name: {
                "low": value["ci_95_low"],
                "high": value["ci_95_high"],
                "case_denominator": value["case_denominator"],
            }
            for name, value in statistics["aggregate"].items()
        },
    }
    report, resume = render_citation_reports(
        statistics,
        _report_metadata(root, statistics, calibration),
    )
    return {
        "case-metrics.jsonl": _jsonl(statistics["case_metrics"]),
        "aggregate.json": _canonical_json(aggregate),
        "confidence-intervals.json": _canonical_json(confidence),
        "report.md": report,
        "resume-evidence.md": resume,
    }


def _prepare(source: Path, output: Path) -> None:
    if (source / "artifact-manifest.json").exists():
        raise ValueError("prepare requires an unsealed Pipeline-derived source")
    for name in _PREPARED_JSON:
        value = _load_json(source / name)
        if not isinstance(value, dict):
            raise ValueError(f"{name} must be an object")
    for name in _PREPARED_JSONL:
        _load_jsonl(source / name)
    assertions = _load_models(source / "assertions.jsonl", AtomicAssertion)
    occurrences = _load_models(source / "citation-occurrences.jsonl", CitationOccurrence)
    matches = _load_models(source / "evidence-matches.jsonl", EvidenceMatch)
    assignments = _load_assignments(source)
    _load_models(source / "calibration.jsonl", CalibrationRecord)
    _load_models(source / "adjudications.jsonl", AdjudicationRecord)
    _validate_authority_links(assertions, occurrences, matches, assignments)
    _case_specs(source)

    _new_directory(output)
    for name in _PREPARED_JSON:
        _atomic_write(output / name, _canonical_json(_load_json(source / name)))
    for name in _PREPARED_JSONL:
        _atomic_write(output / name, _jsonl(_load_jsonl(source / name)))
    _atomic_write(
        output / "review-rubric.json",
        _canonical_json(_load_json(source / "review-rubric.json")),
    )
    _atomic_write(output / "judgments.jsonl", "")


def _score(prepared: Path, judgments: Path, output: Path) -> dict[str, object]:
    authorities = _load_authorities(prepared, judgments=judgments)
    assignments = authorities["assignments"]
    calibration_records = authorities["calibration"]
    loaded_judgments = authorities["judgments"]
    assert isinstance(assignments, tuple)
    assert isinstance(calibration_records, tuple)
    assert isinstance(loaded_judgments, tuple)
    calibration = _calibration(assignments, calibration_records)
    scoring_judgments = _scoring_judgments(
        loaded_judgments, assignments, calibration
    )
    cases = _citation_cases(prepared, authorities, scoring_judgments)
    statistics = score_citation_baseline(cases=cases)

    _new_directory(output)
    builder = EvidencePackageBuilder(output)
    for name in (
        "dataset-manifest.json",
        "corpus-manifest.json",
        "gold-judgments.jsonl",
        "resolved-config.json",
        "environment.json",
        "assertions.jsonl",
        "citation-occurrences.jsonl",
        "evidence-matches.jsonl",
        "review-rubric.json",
        "calibration.jsonl",
        "adjudications.jsonl",
        "failures.jsonl",
        "logs.jsonl",
        "traces.jsonl",
    ):
        builder.write_text(name, (prepared / name).read_text(encoding="utf-8"))
    builder.write_text("judgments.jsonl", _jsonl(loaded_judgments))
    builder.write_text("raw-rankings.jsonl", "")
    projections = _projections(output, statistics, calibration)
    for name, content in projections.items():
        builder.write_text(name, content)
    builder.seal(package_kind=_PACKAGE_KIND)
    return statistics


def _recompute(package: Path, output: Path) -> list[str]:
    manifest = verify_evidence_package(package)
    if manifest.get("package_kind") != _PACKAGE_KIND:
        raise EvidencePackageError("package kind is not citation_baseline")
    authorities = _load_authorities(package)
    assignments = authorities["assignments"]
    calibration_records = authorities["calibration"]
    loaded_judgments = authorities["judgments"]
    assert isinstance(assignments, tuple)
    assert isinstance(calibration_records, tuple)
    assert isinstance(loaded_judgments, tuple)
    calibration = _calibration(assignments, calibration_records)
    scoring_judgments = _scoring_judgments(
        loaded_judgments, assignments, calibration
    )
    statistics = score_citation_baseline(
        cases=_citation_cases(package, authorities, scoring_judgments)
    )
    projections = _projections(package, statistics, calibration)
    _new_directory(output)
    for name, content in projections.items():
        _atomic_write(output / name, content)
    return [
        name
        for name, content in projections.items()
        if (package / name).read_bytes() != content.encode("utf-8")
    ]


@app.command()
def prepare(
    source: Path = typer.Option(..., exists=True, file_okay=False),
    output: Path = typer.Option(...),
) -> None:
    """Validate and freeze Pipeline-derived citation authorities offline."""
    try:
        _prepare(source, output)
    except (OSError, ValidationError, ReviewIntegrityError, ValueError):
        typer.echo("Preparation failed: invalid or unsafe citation inputs", err=True)
        raise typer.Exit(code=_EXIT_INPUT) from None
    typer.echo(f"Prepared citation experiment: {output}")


@app.command("export-review")
def export_review(
    prepared: Path = typer.Option(..., exists=True, file_okay=False),
    output: Path = typer.Option(...),
    reviewer_pseudonym: str | None = typer.Option(None),
) -> None:
    """Export deterministic blinded review assignments offline."""
    try:
        if output.exists():
            raise ValueError("output exists")
        assignments = _load_assignments(prepared)
        if reviewer_pseudonym is not None:
            assignments = tuple(
                item
                for item in assignments
                if item.reviewer_pseudonym == reviewer_pseudonym
            )
            if not assignments:
                raise ValueError("unknown reviewer")
        content = export_review_jsonl(assignments)
        _atomic_write(output, content)
    except (OSError, ValidationError, ReviewIntegrityError, ValueError):
        typer.echo("Review export failed: invalid frozen authorities", err=True)
        raise typer.Exit(code=_EXIT_INPUT) from None
    typer.echo(f"Exported review assignments: {output}")


@app.command("export-review-template")
def export_review_template(
    prepared: Path = typer.Option(..., exists=True, file_okay=False),
    output: Path = typer.Option(...),
    reviewer_pseudonym: str = typer.Option(...),
) -> None:
    """Export an import-shaped response template for one pseudonymous reviewer."""
    try:
        if output.exists():
            raise ValueError("output exists")
        assignments = tuple(
            item
            for item in _load_assignments(prepared)
            if item.reviewer_pseudonym == reviewer_pseudonym
        )
        if not assignments:
            raise ValueError("unknown reviewer")
        _atomic_write(output, export_response_template_jsonl(assignments))
    except (OSError, ValidationError, ReviewIntegrityError, ValueError):
        typer.echo(
            "Response template export failed: invalid frozen authorities",
            err=True,
        )
        raise typer.Exit(code=_EXIT_INPUT) from None
    typer.echo(f"Exported review response template: {output}")


@app.command("import-review")
def import_review(
    prepared: Path = typer.Option(..., exists=True, file_okay=False),
    review: Path = typer.Option(..., exists=True, dir_okay=False),
    output: Path = typer.Option(...),
    existing: Path | None = typer.Option(None, exists=True, dir_okay=False),
) -> None:
    """Validate hash-bound review responses and emit judgments offline."""
    try:
        assignments = _load_assignments(prepared)
        if output.exists():
            raise ValueError("output exists")
    except (OSError, ValidationError, ReviewIntegrityError, ValueError):
        typer.echo("Review import failed: invalid prepared authorities", err=True)
        raise typer.Exit(code=_EXIT_INPUT) from None
    try:
        imported = import_review_jsonl(_read_text(review), assignments)
        prior = _load_models(existing, SupportJudgment) if existing is not None else ()
        judgments = merge_review_judgments(prior, imported, assignments)
        _atomic_write(output, _jsonl(judgments))
    except (ValidationError, ReviewIntegrityError, ValueError):
        typer.echo(
            "Review import failed: authority hash or rubric mismatch",
            err=True,
        )
        raise typer.Exit(code=_EXIT_REVIEW) from None
    except OSError:
        typer.echo("Review import failed: output is unavailable", err=True)
        raise typer.Exit(code=_EXIT_INPUT) from None
    typer.echo(f"Imported review judgments: {output}")


@app.command()
def score(
    prepared: Path = typer.Option(..., exists=True, file_okay=False),
    judgments: Path = typer.Option(..., exists=True, dir_okay=False),
    output: Path = typer.Option(...),
) -> None:
    """Score complete calibrated judgments and seal the package offline."""
    try:
        statistics = _score(prepared, judgments, output)
    except ReviewIntegrityError as error:
        category = "calibration" if "calibration" in str(error).lower() else "judgment"
        typer.echo(f"Scoring blocked: incomplete or invalid {category} authority", err=True)
        raise typer.Exit(code=_EXIT_REVIEW) from None
    except (OSError, ValidationError, EvidencePackageError, ValueError):
        typer.echo("Scoring failed: invalid or unsafe citation inputs", err=True)
        raise typer.Exit(code=_EXIT_INPUT) from None
    if statistics["operations"]["failed"]:
        typer.echo(f"Sealed citation package with case failures: {output}", err=True)
        raise typer.Exit(code=_EXIT_REVIEW)
    typer.echo(f"Sealed citation package: {output}")


def _automated_authority(path: Path) -> AutomatedJudgeAuthority:
    value = _load_json(path)
    if not isinstance(value, dict):
        raise ValueError("automated judge authority must be an object")
    return AutomatedJudgeAuthority.model_validate(value)


def _automated_inputs(path: Path) -> tuple[AutomatedJudgeInput, ...]:
    return tuple(
        AutomatedJudgeInput.model_validate(value) for value in _load_jsonl(path)
    )


def _preflight_automated(
    generation: Path,
    authority: AutomatedJudgeAuthority,
    inputs: tuple[AutomatedJudgeInput, ...],
) -> dict[str, object]:
    frozen = inspect_frozen_generation(generation)
    if (
        authority.generation_model_version != frozen["generation_model_version"]
        or authority.generation_output_sha256
        != frozen["generation_output_sha256"]
        or authority.gold_evidence_sha256 != frozen["gold_evidence_sha256"]
    ):
        raise AutomatedJudgeError("judge authority does not match frozen generation")
    if not inputs or any(
        item.output_sha256 != authority.generation_output_sha256
        or item.gold_evidence_sha256 != authority.gold_evidence_sha256
        for item in inputs
    ):
        raise AutomatedJudgeError("judge inputs do not match frozen authorities")
    unresolved = sum(not item.deterministic_support_match_ids for item in inputs)
    minimum_passes = unresolved
    maximum_passes = unresolved
    maximum_sends_with_retries = maximum_passes * (
        authority.max_retries_per_pass + 1
    )
    if authority.max_total_sends < minimum_passes:
        raise AutomatedJudgeError("judge send budget cannot fund single-pass protocol")
    return {
        **frozen,
        "assertion_count": len(inputs),
        "deterministic_decision_count": len(inputs) - unresolved,
        "minimum_judge_passes": minimum_passes,
        "maximum_judge_passes": maximum_passes,
        "maximum_provider_sends_with_retries": maximum_sends_with_retries,
        "authorized_send_cap": authority.max_total_sends,
        "authorized_cost_cap": authority.max_total_cost,
        "pricing_currency": authority.pricing_currency,
    }


@app.command("preflight-automated-judge")
def preflight_automated_judge_command(
    generation: Path = typer.Option(..., exists=True, file_okay=False),
    authority: Path = typer.Option(..., exists=True, dir_okay=False),
    inputs: Path = typer.Option(..., exists=True, dir_okay=False),
) -> None:
    """Validate frozen generation, judge provenance, and budgets without sending."""
    try:
        summary = _preflight_automated(
            generation,
            _automated_authority(authority),
            _automated_inputs(inputs),
        )
    except (OSError, ValidationError, AutomatedJudgeError, ValueError):
        typer.echo("Automated judge preflight failed: frozen authority mismatch", err=True)
        raise typer.Exit(code=_EXIT_INPUT) from None
    typer.echo(_canonical_json({"status": "PASS", "provider_calls": 0, **summary}).strip())


@app.command("run-automated-judge")
def run_automated_judge_command(
    generation: Path = typer.Option(..., exists=True, file_okay=False),
    authority: Path = typer.Option(..., exists=True, dir_okay=False),
    inputs: Path = typer.Option(..., exists=True, dir_okay=False),
    output: Path = typer.Option(...),
    acknowledge_provider_costs: bool = typer.Option(False, "--acknowledge-provider-costs"),
) -> None:
    """Run/resume paid automated judging only after explicit bounded approval."""
    if not acknowledge_provider_costs:
        typer.echo("run-automated-judge requires --acknowledge-provider-costs", err=True)
        raise typer.Exit(code=_EXIT_INPUT)
    try:
        frozen_authority = _automated_authority(authority)
        frozen_inputs = _automated_inputs(inputs)
        _preflight_automated(generation, frozen_authority, frozen_inputs)
        settings = load_settings()
        if settings.dashscope_generation_model != frozen_authority.judge_model_version:
            raise ValueError("configured judge model does not match authority")
        api_key = settings.dashscope_api_key
        if not api_key or not api_key.strip():
            raise ValueError("judge credential is unavailable")
        if settings.dashscope_generation_base_url != frozen_authority.judge_base_url:
            raise ValueError("configured judge endpoint does not match authority")
        with httpx.Client() as client:
            provider = DashScopeAutomatedJudgeProvider(
                api_key=api_key,
                base_url=frozen_authority.judge_base_url,
                authority=frozen_authority,
                transport=DashScopeChatTransport(client),
            )
            decisions = run_automated_judge(
                output=output,
                authority=frozen_authority,
                inputs=frozen_inputs,
                provider=provider,
            )
    except (OSError, ValidationError, AutomatedJudgeError, ValueError):
        typer.echo("Automated judge run failed: authority, budget, or provider gate", err=True)
        raise typer.Exit(code=_EXIT_REVIEW) from None
    typer.echo(f"Completed {len(decisions)} automated assertion decisions: {output}")


@app.command("score-automated")
def score_automated_command(
    prepared: Path = typer.Option(..., exists=True, file_okay=False),
    output: Path = typer.Option(...),
) -> None:
    """Score and seal complete LLM-as-Judge authorities offline."""
    try:
        seal_automated_citation_package(prepared, output)
    except (OSError, ValidationError, AutomatedJudgeError, EvidencePackageError, ValueError):
        typer.echo("Automated scoring failed: incomplete or corrupt authority", err=True)
        raise typer.Exit(code=_EXIT_INTEGRITY) from None
    typer.echo(f"Sealed LLM-as-Judge citation package: {output}")


@app.command("recompute-automated")
def recompute_automated_command(
    package: Path = typer.Option(..., exists=True, file_okay=False),
    output: Path = typer.Option(...),
) -> None:
    """Recompute LLM-as-Judge projections from sealed authorities offline."""
    try:
        mismatches = recompute_automated_citation_package(package, output)
    except (OSError, ValidationError, AutomatedJudgeError, EvidencePackageError, ValueError):
        typer.echo("Automated recompute failed: corrupt authority", err=True)
        raise typer.Exit(code=_EXIT_INTEGRITY) from None
    if mismatches:
        typer.echo(f"Automated projection mismatch: {', '.join(mismatches)}", err=True)
        raise typer.Exit(code=_EXIT_INTEGRITY)
    typer.echo(f"Recomputed LLM-as-Judge projections: {output}")


@app.command("verify-automated")
def verify_automated_command(
    package: Path = typer.Argument(..., exists=True, file_okay=False),
) -> None:
    """Verify seal, method, provenance, and projections offline."""
    try:
        verify_automated_citation_package(package)
    except (OSError, ValidationError, AutomatedJudgeError, EvidencePackageError, ValueError):
        typer.echo("Automated verification failed: integrity or method mismatch", err=True)
        raise typer.Exit(code=_EXIT_INTEGRITY) from None
    typer.echo(f"Verified LLM-as-Judge citation package: {package}")


def _live_generation_config(
    *,
    model_authority: Path,
    campaign_id: str,
    execution_id: str,
    temperature: float,
    max_tokens: int,
    attempt_timeout_seconds: float,
    case_limit: int,
    case_id: list[str] | None,
    max_sends_per_case: int,
    max_total_sends: int,
    max_prompt_tokens_per_send: int,
    max_total_prompt_tokens: int,
    max_total_completion_tokens: int,
    max_cost_usd: float,
) -> LiveGenerationConfig:
    authority = load_provider_model_authority(model_authority)
    return LiveGenerationConfig(
        request_model=authority.request_model,
        expected_response_model=authority.expected_response_model,
        model_authority_sha256=hashlib.sha256(model_authority.read_bytes()).hexdigest(),
        campaign_id=campaign_id,
        execution_id=execution_id,
        temperature=temperature,
        max_tokens=max_tokens,
        attempt_timeout_seconds=attempt_timeout_seconds,
        max_sends_per_case=max_sends_per_case,
        max_total_sends=max_total_sends,
        case_limit=case_limit,
        selected_case_ids=tuple(case_id or ()),
        max_prompt_tokens_per_send=max_prompt_tokens_per_send,
        max_total_prompt_tokens=max_total_prompt_tokens,
        max_total_completion_tokens=max_total_completion_tokens,
        pricing_authority=authority.pricing_document_url,
        input_usd_per_million_tokens=authority.input_usd_per_million_tokens,
        output_usd_per_million_tokens=authority.output_usd_per_million_tokens,
        max_cost_usd=max_cost_usd,
    )


@app.command("create-campaign-ledger")
def create_campaign_ledger_command(
    output: Path = typer.Option(...),
    campaign_id: str = typer.Option(...),
    prior_ledger: list[Path] = typer.Option(
        ..., "--prior-ledger", exists=True, dir_okay=False
    ),
) -> None:
    """Consolidate every prior provider send into one offline campaign ledger."""

    try:
        summary = create_campaign_ledger(
            output=output, campaign_id=campaign_id, prior_ledgers=prior_ledger
        )
    except (OSError, ValueError):
        typer.echo(
            "Campaign ledger creation failed: invalid or unsafe prior ledger", err=True
        )
        raise typer.Exit(code=_EXIT_INPUT) from None
    typer.echo(_canonical_json(summary).strip())


@app.command("preflight-live-generation")
def preflight_live_generation_command(
    prepared: Path = typer.Option(..., exists=True, file_okay=False),
    output: Path = typer.Option(...),
    model_authority: Path = typer.Option(..., exists=True, dir_okay=False),
    campaign_ledger: Path = typer.Option(..., exists=True, dir_okay=False),
    campaign_id: str = typer.Option(...),
    execution_id: str = typer.Option(...),
    temperature: float = typer.Option(0.0, min=0.0, max=2.0),
    max_tokens: int = typer.Option(..., min=1),
    attempt_timeout_seconds: float = typer.Option(60.0, min=0.001),
    case_limit: int = typer.Option(2, min=1),
    case_id: list[str] | None = typer.Option(
        None,
        "--case-id",
        help="Select an exact frozen case; repeat in the intended execution order.",
    ),
    max_sends_per_case: int = typer.Option(4, min=1, max=4),
    max_total_sends: int = typer.Option(..., min=1),
    max_prompt_tokens_per_send: int = typer.Option(..., min=1),
    max_total_prompt_tokens: int = typer.Option(..., min=1),
    max_total_completion_tokens: int = typer.Option(..., min=1),
    max_cost_usd: float = typer.Option(0.25, min=0.000001),
) -> None:
    """Run every deterministic launch gate without reading credentials or sending."""

    try:
        config = _live_generation_config(
            model_authority=model_authority,
            campaign_id=campaign_id,
            execution_id=execution_id,
            temperature=temperature,
            max_tokens=max_tokens,
            attempt_timeout_seconds=attempt_timeout_seconds,
            case_limit=case_limit,
            case_id=case_id,
            max_sends_per_case=max_sends_per_case,
            max_total_sends=max_total_sends,
            max_prompt_tokens_per_send=max_prompt_tokens_per_send,
            max_total_prompt_tokens=max_total_prompt_tokens,
            max_total_completion_tokens=max_total_completion_tokens,
            max_cost_usd=max_cost_usd,
        )
        selected_ids = preflight_live_generation(
            prepared=prepared,
            output=output,
            config=config,
            environment=_git_environment(),
            model_authority=model_authority,
            campaign_ledger=campaign_ledger,
        )
    except (OSError, subprocess.SubprocessError, ValidationError, ValueError):
        typer.echo(
            "Live generation preflight failed: authority, budget, path, or Git gate",
            err=True,
        )
        raise typer.Exit(code=_EXIT_INPUT) from None
    typer.echo(
        f"PASS: {len(selected_ids)} cases are offline-preflight ready; "
        "no provider call was made"
    )


@app.command("run-live-generation")
def run_live_generation_command(
    prepared: Path = typer.Option(..., exists=True, file_okay=False),
    output: Path = typer.Option(...),
    model_authority: Path = typer.Option(..., exists=True, dir_okay=False),
    campaign_ledger: Path = typer.Option(..., exists=True, dir_okay=False),
    campaign_id: str = typer.Option(...),
    execution_id: str = typer.Option(...),
    temperature: float = typer.Option(0.0, min=0.0, max=2.0),
    max_tokens: int = typer.Option(..., min=1),
    attempt_timeout_seconds: float = typer.Option(60.0, min=0.001),
    case_limit: int = typer.Option(2, min=1),
    case_id: list[str] | None = typer.Option(None, "--case-id"),
    max_sends_per_case: int = typer.Option(4, min=1, max=4),
    max_total_sends: int = typer.Option(..., min=1),
    max_prompt_tokens_per_send: int = typer.Option(..., min=1),
    max_total_prompt_tokens: int = typer.Option(..., min=1),
    max_total_completion_tokens: int = typer.Option(..., min=1),
    max_cost_usd: float = typer.Option(0.25, min=0.000001),
    acknowledge_provider_costs: bool = typer.Option(
        False,
        "--acknowledge-provider-costs",
        help="Acknowledge the frozen provider call and USD ceilings.",
    ),
) -> None:
    """Run or resume frozen Citation cases with hard send and cost authorization."""

    if not acknowledge_provider_costs:
        typer.echo(
            "run-live-generation requires --acknowledge-provider-costs", err=True
        )
        raise typer.Exit(code=_EXIT_INPUT)
    try:
        config = _live_generation_config(
            model_authority=model_authority,
            campaign_id=campaign_id,
            execution_id=execution_id,
            temperature=temperature,
            max_tokens=max_tokens,
            attempt_timeout_seconds=attempt_timeout_seconds,
            max_sends_per_case=max_sends_per_case,
            max_total_sends=max_total_sends,
            case_limit=case_limit,
            case_id=case_id,
            max_prompt_tokens_per_send=max_prompt_tokens_per_send,
            max_total_prompt_tokens=max_total_prompt_tokens,
            max_total_completion_tokens=max_total_completion_tokens,
            max_cost_usd=max_cost_usd,
        )
        environment = _git_environment()
        selected_ids = preflight_live_generation(
            prepared=prepared,
            output=output,
            config=config,
            environment=environment,
            model_authority=model_authority,
            campaign_ledger=campaign_ledger,
        )
        settings = load_settings()
        if settings.dashscope_generation_model != config.request_model:
            raise ValueError("configured request model does not match frozen settings")
        api_key = settings.dashscope_api_key
        if not api_key or not api_key.strip():
            raise ValueError("generation provider credential is unavailable")

        with httpx.Client() as client:
            transport = DashScopeChatTransport(client)

            def provider_factory(case_id, ledger):
                return DashScopeGenerationProvider(
                    api_key=api_key,
                    model=config.request_model,
                    base_url=settings.dashscope_generation_base_url,
                    transport=BudgetedDashScopeTransport(transport, ledger, case_id),
                    temperature=config.temperature,
                    max_tokens=config.max_tokens,
                )

            manifest = run_live_generation(
                prepared=prepared,
                output=output,
                config=config,
                environment=environment,
                model_authority=model_authority,
                campaign_ledger=campaign_ledger,
                provider_factory=provider_factory,
            )
    except (OSError, subprocess.SubprocessError, ValidationError, ValueError):
        typer.echo(
            "Live generation preflight failed: invalid, unsafe, dirty, or unavailable inputs",
            err=True,
        )
        raise typer.Exit(code=_EXIT_INPUT) from None

    if manifest["status"] != "completed":
        typer.echo(
            f"Live generation incomplete; completed cases were preserved: {output}",
            err=True,
        )
        raise typer.Exit(code=_EXIT_REVIEW)
    typer.echo(f"Generated {len(selected_ids)} frozen Citation cases: {output}")


@app.command()
def recompute(
    package: Path = typer.Option(..., exists=True, file_okay=False),
    output: Path = typer.Option(...),
) -> None:
    """Recompute every projection from sealed authorities offline."""
    if output.exists():
        typer.echo("Recompute failed: output path already exists", err=True)
        raise typer.Exit(code=_EXIT_INPUT)
    try:
        mismatches = _recompute(package, output)
    except (EvidencePackageError, OSError, ValidationError, ReviewIntegrityError, ValueError):
        typer.echo("Recompute integrity failure: corrupt sealed package", err=True)
        raise typer.Exit(code=_EXIT_INTEGRITY) from None
    if mismatches:
        typer.echo(f"Projection mismatch: {', '.join(mismatches)}", err=True)
        raise typer.Exit(code=_EXIT_INTEGRITY)
    typer.echo(f"Recomputed byte-identical projections: {output}")


@app.command()
def verify(
    package: Path = typer.Argument(..., exists=True, file_okay=False),
) -> None:
    """Verify seal integrity and byte-identical offline recomputation."""
    try:
        with tempfile.TemporaryDirectory(prefix="citation-baseline-verify-") as root:
            mismatches = _recompute(package, Path(root) / "projections")
    except (EvidencePackageError, OSError, ValidationError, ReviewIntegrityError, ValueError):
        typer.echo("Verification failed: corrupt sealed package", err=True)
        raise typer.Exit(code=_EXIT_INTEGRITY) from None
    if mismatches:
        typer.echo(f"Verification projection mismatch: {', '.join(mismatches)}", err=True)
        raise typer.Exit(code=_EXIT_INTEGRITY)
    typer.echo(f"Verified citation package: {package}")


__all__ = ["app"]
