from __future__ import annotations

import hashlib
import json
import re
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import typer

from paper_agent.eval.evidence_package import (
    EvidencePackageError,
    verify_evidence_package,
)


_MANIFEST = "artifact-manifest.json"
_OUTPUT_ARTIFACTS = ("report.md", "resume-evidence.md")
_SAFE_REASON_CODE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


class ValidationPackageError(ValueError):
    """A sanitized Task 9 source-integrity or compatibility failure."""


class SourceRecompute:
    PROJECTIONS = (
        "case-metrics.jsonl",
        "aggregate.json",
        "confidence-intervals.json",
        "report.md",
        "resume-evidence.md",
    )


Recomputer = Callable[[Path, Path], list[str]]

app = typer.Typer(help="Preflight, assemble, and verify the final validation package.")


@dataclass(frozen=True)
class ValidationSource:
    track: str
    path: Path
    package_kind: str
    manifest_sha256: str
    case_ids: tuple[str, ...]
    dataset_id: str
    dataset_version: str
    selected_split: str
    dataset_fingerprint_sha256: str
    corpus_sha256: str
    config_sha256: str
    metric_versions: tuple[str, ...]
    git_sha: str
    data_kind: str
    report: str
    resume_evidence: str


@dataclass(frozen=True)
class ValidationPreflight:
    sources: Mapping[str, ValidationSource]
    case_count: int
    track_case_counts: Mapping[str, int]
    recomputed: bool
    publishable: bool
    blockers: tuple[str, ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValidationPackageError(f"{path.name} is missing or invalid") from error
    if not isinstance(value, dict):
        raise ValidationPackageError(f"{path.name} must contain an object")
    return value


def _load_jsonl(path: Path) -> list[dict[str, object]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise ValidationPackageError(f"{path.name} is missing or invalid") from error
    values: list[dict[str, object]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValidationPackageError(
                f"{path.name} contains invalid JSON at line {line_number}"
            ) from error
        if not isinstance(value, dict):
            raise ValidationPackageError(f"{path.name} rows must be objects")
        values.append(value)
    return values


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationPackageError(f"{label} is missing or invalid")
    return value


def _required_sha256(value: object, label: str) -> str:
    text = _required_text(value, label)
    if not _SHA256.fullmatch(text):
        raise ValidationPackageError(f"{label} is missing or invalid")
    return text


def _case_ids(track: str, config: dict[str, object]) -> tuple[str, ...]:
    if track == "retrieval":
        values = config.get("ordered_case_ids")
    else:
        cases = config.get("cases")
        values = (
            [item.get("case_id") for item in cases if isinstance(item, dict)]
            if isinstance(cases, list) and all(isinstance(item, dict) for item in cases)
            else None
        )
    if (
        not isinstance(values, list)
        or any(not isinstance(value, str) or not value.strip() for value in values)
        or len(values) != len(set(values))
    ):
        raise ValidationPackageError(f"{track} ordered case IDs are invalid")
    return tuple(values)


def _metric_versions(track: str, config: dict[str, object]) -> tuple[str, ...]:
    values = config.get("metric_versions")
    if (
        not isinstance(values, list)
        or not values
        or any(not isinstance(value, str) or not value.strip() for value in values)
        or len(values) != len(set(values))
    ):
        raise ValidationPackageError(f"{track} metric versions are missing or invalid")
    return tuple(values)


def _validate_chunk_authority(
    track: str,
    config: dict[str, object],
    corpus: dict[str, object],
) -> None:
    values = config.get("ordered_chunk_sha256")
    if values is None:
        chunks = corpus.get("chunks")
        if isinstance(chunks, list):
            values = [
                item.get("chunk_sha256")
                for item in chunks
                if isinstance(item, dict) and "chunk_sha256" in item
            ]
    if (
        not isinstance(values, list)
        or not values
        or any(not isinstance(value, str) or not _SHA256.fullmatch(value) for value in values)
    ):
        raise ValidationPackageError(f"{track} chunk hash authority is missing or invalid")


def _validate_failures(track: str, root: Path) -> None:
    for row in _load_jsonl(root / "failures.jsonl"):
        reason = row.get("reason_code")
        if not isinstance(reason, str) or not _SAFE_REASON_CODE.fullmatch(reason):
            raise ValidationPackageError(
                f"{track} failures must contain sanitized reason_code values"
            )


def _default_recomputers() -> dict[str, Recomputer]:
    # Lazy imports keep this module provider-independent. Both functions are offline.
    from paper_agent.eval.citation_baseline.cli import _recompute as recompute_citation
    from paper_agent.eval.retrieval_benchmark.cli import _recompute as recompute_retrieval

    return {"retrieval": recompute_retrieval, "citation": recompute_citation}


def _verify_recomputed(
    track: str,
    package: Path,
    recomputer: Recomputer,
) -> tuple[str, str]:
    with tempfile.TemporaryDirectory(prefix=f"momo-{track}-verify-") as temporary:
        output = Path(temporary) / "projections"
        try:
            mismatches = recomputer(package, output)
        except (EvidencePackageError, OSError, ValueError) as error:
            raise ValidationPackageError(f"{track} offline recomputation failed") from error
        if mismatches:
            raise ValidationPackageError(f"{track} offline recomputation reported mismatches")
        for name in SourceRecompute.PROJECTIONS[:3]:
            try:
                matches = (output / name).read_bytes() == (package / name).read_bytes()
            except OSError as error:
                raise ValidationPackageError(
                    f"{track} recomputed projection is missing: {name}"
                ) from error
            if not matches:
                raise ValidationPackageError(
                    f"{track} recomputed projection mismatch: {name}"
                )
        try:
            report = (output / "report.md").read_text(encoding="utf-8")
            resume = (output / "resume-evidence.md").read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise ValidationPackageError(
                f"{track} recomputed report projections are invalid"
            ) from error
        return report, resume


def _load_source(
    track: str,
    root: Path,
    recomputer: Recomputer,
) -> ValidationSource:
    expected_kind = {
        "retrieval": "retrieval_benchmark",
        "citation": "citation_baseline",
    }[track]
    try:
        manifest = verify_evidence_package(root)
    except EvidencePackageError as error:
        raise ValidationPackageError(f"{track} source package verification failed") from error
    if manifest.get("package_kind") != expected_kind:
        raise ValidationPackageError(f"{track} source package kind is invalid")

    dataset = _load_json(root / "dataset-manifest.json")
    corpus = _load_json(root / "corpus-manifest.json")
    config = _load_json(root / "resolved-config.json")
    environment = _load_json(root / "environment.json")
    if environment.get("git_dirty") is not False:
        raise ValidationPackageError(f"{track} source Git state is dirty or missing")
    models = environment.get("models")
    if (
        not isinstance(models, dict)
        or not models
        or any(not isinstance(value, str) or not value.strip() for value in models.values())
    ):
        raise ValidationPackageError(f"{track} source model versions are missing")

    _validate_chunk_authority(track, config, corpus)
    _validate_failures(track, root)
    report, resume = _verify_recomputed(track, root, recomputer)
    return ValidationSource(
        track=track,
        path=root.resolve(),
        package_kind=expected_kind,
        manifest_sha256=_sha256(root / _MANIFEST),
        case_ids=_case_ids(track, config),
        dataset_id=_required_text(dataset.get("dataset_id"), f"{track} dataset ID"),
        dataset_version=_required_text(
            dataset.get("dataset_version"), f"{track} dataset version"
        ),
        selected_split=_required_text(
            dataset.get("selected_split"), f"{track} selected split"
        ),
        dataset_fingerprint_sha256=_required_sha256(
            dataset.get("dataset_fingerprint_sha256"),
            f"{track} dataset fingerprint",
        ),
        corpus_sha256=_required_sha256(
            corpus.get("corpus_sha256"), f"{track} corpus hash"
        ),
        config_sha256=_sha256(root / "resolved-config.json"),
        metric_versions=_metric_versions(track, config),
        git_sha=_required_text(environment.get("git_sha"), f"{track} Git SHA"),
        data_kind=_required_text(dataset.get("data_kind"), f"{track} data kind"),
        report=report,
        resume_evidence=resume,
    )


def preflight_validation_sources(
    retrieval_package: str | Path,
    citation_package: str | Path,
    *,
    recomputers: Mapping[str, Recomputer] | None = None,
) -> ValidationPreflight:
    selected = dict(recomputers or _default_recomputers())
    if set(selected) != {"retrieval", "citation"}:
        raise ValidationPackageError("both track recomputers are required")
    sources = {
        "retrieval": _load_source(
            "retrieval", Path(retrieval_package), selected["retrieval"]
        ),
        "citation": _load_source(
            "citation", Path(citation_package), selected["citation"]
        ),
    }
    retrieval = sources["retrieval"]
    citation = sources["citation"]
    if not _GIT_SHA.fullmatch(retrieval.git_sha) or not _GIT_SHA.fullmatch(
        citation.git_sha
    ):
        raise ValidationPackageError("source Git SHA values are invalid")
    if len(retrieval.case_ids) != 40:
        raise ValidationPackageError("retrieval source must contain exactly 40 cases")
    if len(citation.case_ids) != 20:
        raise ValidationPackageError("citation source must contain exactly 20 cases")
    if set(retrieval.case_ids) & set(citation.case_ids):
        raise ValidationPackageError("retrieval and citation case IDs overlap")
    for field, label in (
        ("dataset_id", "dataset ID"),
        ("dataset_version", "dataset version"),
        ("selected_split", "selected split"),
        ("git_sha", "Git SHA"),
    ):
        if getattr(retrieval, field) != getattr(citation, field):
            raise ValidationPackageError(f"source {label} values are incompatible")
    if retrieval.selected_split != "validation":
        raise ValidationPackageError("source selected split must be validation")

    blockers = tuple(
        f"{track} source is synthetic"
        for track, source in sources.items()
        if source.data_kind != "real"
    )
    if any(source.data_kind not in {"real", "synthetic"} for source in sources.values()):
        raise ValidationPackageError("source data kind values are invalid")
    return ValidationPreflight(
        sources=sources,
        case_count=60,
        track_case_counts={"retrieval": 40, "citation": 20},
        recomputed=True,
        publishable=not blockers,
        blockers=blockers,
    )


def _source_record(source: ValidationSource) -> dict[str, object]:
    return {
        "path": str(source.path),
        "package_kind": source.package_kind,
        "artifact_manifest_sha256": source.manifest_sha256,
        "case_count": len(source.case_ids),
        "ordered_case_ids": list(source.case_ids),
        "dataset_fingerprint_sha256": source.dataset_fingerprint_sha256,
        "corpus_sha256": source.corpus_sha256,
        "resolved_config_sha256": source.config_sha256,
        "metric_versions": list(source.metric_versions),
    }


def _render_report(preflight: ValidationPreflight) -> str:
    retrieval = preflight.sources["retrieval"]
    citation = preflight.sources["citation"]
    lines = [
        "# MOMO Scholar 60-Case Validation Report",
        "",
        f"Package status: {'publishable' if preflight.publishable else 'fixture dry-run only'}",
        "Cases: 60 total (40 retrieval + 20 citation; no overlap)",
        f"Dataset: {retrieval.dataset_id} {retrieval.dataset_version} / {retrieval.selected_split}",
        f"Git: `{retrieval.git_sha}` (clean in both sources)",
        "",
        "Track metrics are intentionally not averaged into a composite score.",
        "Latency and failure rates retain each track's attempted/completed/failed denominators.",
        "Failure details are accepted only as sanitized reason codes.",
        "",
        "## Source packages",
        "",
        "| Track | Cases | Manifest SHA-256 | Corpus SHA-256 | Config SHA-256 |",
        "|---|---:|---|---|---|",
    ]
    for source in (retrieval, citation):
        lines.append(
            f"| {source.track} | {len(source.case_ids)} | `{source.manifest_sha256}` | "
            f"`{source.corpus_sha256}` | `{source.config_sha256}` |"
        )
    if preflight.blockers:
        lines.extend(["", "## Publication blockers", ""])
        lines.extend(f"- {blocker}" for blocker in preflight.blockers)
    for source in (retrieval, citation):
        lines.extend(
            [
                "",
                f"## {source.track.title()} track (verified source projection)",
                "",
                f"Source manifest: `{source.manifest_sha256}`",
                "",
                source.report.rstrip(),
            ]
        )
    lines.append("")
    return "\n".join(lines)


def _render_resume(preflight: ValidationPreflight) -> str:
    lines = ["# Resume Evidence", ""]
    if not preflight.publishable:
        lines.append("No resume-ready numeric claims.")
        lines.extend(f"- {blocker}" for blocker in preflight.blockers)
        lines.append("")
        return "\n".join(lines)
    for source in (preflight.sources["retrieval"], preflight.sources["citation"]):
        prefix = source.manifest_sha256[:12]
        claims = [
            line.strip()
            for line in source.resume_evidence.splitlines()
            if line.strip() and not line.startswith("#")
        ]
        if not claims or any("No resume-ready numeric claims" in line for line in claims):
            raise ValidationPackageError(
                f"{source.track} source has no verified resume-ready claims"
            )
        lines.append(f"## {source.track.title()} track")
        lines.append("")
        for claim in claims:
            text = claim[1:].strip() if claim.startswith("-") else claim
            lines.append(f"- {text} Source manifest `{prefix}`.")
        lines.append("")
    return "\n".join(lines)


def _atomic_write(path: Path, content: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_bytes(content)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def assemble_validation_package(
    retrieval_package: str | Path,
    citation_package: str | Path,
    output: str | Path,
    *,
    recomputers: Mapping[str, Recomputer] | None = None,
    fixture_dry_run: bool = False,
) -> Path:
    preflight = preflight_validation_sources(
        retrieval_package,
        citation_package,
        recomputers=recomputers,
    )
    if not preflight.publishable and not fixture_dry_run:
        raise ValidationPackageError(
            "validation package is not publishable: synthetic source package"
        )
    if preflight.publishable and fixture_dry_run:
        raise ValidationPackageError("fixture dry-run requires non-publishable inputs")

    root = Path(output)
    if root.exists():
        raise ValidationPackageError("validation output path already exists")
    root.mkdir(parents=True)
    report = _render_report(preflight)
    resume = _render_resume(preflight)
    _atomic_write(root / "report.md", report.encode("utf-8"))
    _atomic_write(root / "resume-evidence.md", resume.encode("utf-8"))
    artifacts = [
        {
            "path": name,
            "role": "projection",
            "byte_length": (root / name).stat().st_size,
            "sha256": _sha256(root / name),
        }
        for name in _OUTPUT_ARTIFACTS
    ]
    retrieval = preflight.sources["retrieval"]
    manifest = {
        "schema_version": "1.0",
        "package_kind": (
            "validation_baseline" if preflight.publishable else "validation_fixture_dry_run"
        ),
        "sealed": True,
        "publishable": preflight.publishable,
        "sealed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "case_count": 60,
        "track_case_counts": dict(preflight.track_case_counts),
        "dataset": {
            "dataset_id": retrieval.dataset_id,
            "dataset_version": retrieval.dataset_version,
            "selected_split": retrieval.selected_split,
        },
        "git_sha": retrieval.git_sha,
        "sources": {
            track: _source_record(source)
            for track, source in preflight.sources.items()
        },
        "artifacts": artifacts,
    }
    _atomic_write(
        root / _MANIFEST,
        (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode(
            "utf-8"
        ),
    )
    return root


def verify_validation_package(root: str | Path) -> dict[str, object]:
    package = Path(root)
    manifest = _load_json(package / _MANIFEST)
    if manifest.get("sealed") is not True or manifest.get("package_kind") not in {
        "validation_baseline",
        "validation_fixture_dry_run",
    }:
        raise ValidationPackageError("validation artifact manifest is not sealed")
    if manifest.get("case_count") != 60 or manifest.get("track_case_counts") != {
        "retrieval": 40,
        "citation": 20,
    }:
        raise ValidationPackageError("validation case counts are invalid")
    publishable = manifest.get("publishable")
    expected_kind = (
        "validation_baseline" if publishable is True else "validation_fixture_dry_run"
    )
    if not isinstance(publishable, bool) or manifest.get("package_kind") != expected_kind:
        raise ValidationPackageError("validation publication status is inconsistent")
    sources = manifest.get("sources")
    if not isinstance(sources, dict) or set(sources) != {"retrieval", "citation"}:
        raise ValidationPackageError("validation source references are invalid")
    case_ids: dict[str, list[str]] = {}
    for track, expected_count in (("retrieval", 40), ("citation", 20)):
        source = sources[track]
        if not isinstance(source, dict):
            raise ValidationPackageError("validation source references are invalid")
        source_path = source.get("path")
        source_hash = source.get("artifact_manifest_sha256")
        ids = source.get("ordered_case_ids")
        if (
            not isinstance(source_path, str)
            or not isinstance(source_hash, str)
            or not _SHA256.fullmatch(source_hash)
            or not isinstance(ids, list)
            or len(ids) != expected_count
            or any(not isinstance(item, str) or not item.strip() for item in ids)
            or len(ids) != len(set(ids))
        ):
            raise ValidationPackageError("validation source references are invalid")
        source_manifest = Path(source_path) / _MANIFEST
        if not source_manifest.is_file() or _sha256(source_manifest) != source_hash:
            raise ValidationPackageError(f"validation {track} source hash mismatch")
        case_ids[track] = ids
    if set(case_ids["retrieval"]) & set(case_ids["citation"]):
        raise ValidationPackageError("validation source case IDs overlap")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != len(_OUTPUT_ARTIFACTS):
        raise ValidationPackageError("validation artifact entries are invalid")
    seen: set[str] = set()
    for entry in artifacts:
        if not isinstance(entry, dict) or entry.get("path") not in _OUTPUT_ARTIFACTS:
            raise ValidationPackageError("validation artifact entries are invalid")
        name = str(entry["path"])
        if name in seen:
            raise ValidationPackageError("validation artifact entries contain duplicates")
        seen.add(name)
        path = package / name
        if not path.is_file():
            raise ValidationPackageError(f"validation artifact is missing: {name}")
        if path.stat().st_size != entry.get("byte_length"):
            raise ValidationPackageError(f"validation artifact length mismatch: {name}")
        if _sha256(path) != entry.get("sha256"):
            raise ValidationPackageError(f"validation artifact hash mismatch: {name}")
    if seen != set(_OUTPUT_ARTIFACTS):
        raise ValidationPackageError("validation artifact coverage is incomplete")
    return manifest


@app.command()
def preflight(
    retrieval: Path = typer.Option(..., exists=True, file_okay=False),
    citation: Path = typer.Option(..., exists=True, file_okay=False),
) -> None:
    """Verify both sealed sources and rerun every offline projection."""
    try:
        result = preflight_validation_sources(retrieval, citation)
    except ValidationPackageError as error:
        typer.echo(f"Validation preflight failed: {error}", err=True)
        raise typer.Exit(code=3) from None
    typer.echo("Validated 60 unique cases: retrieval=40, citation=20")
    for track, source in result.sources.items():
        typer.echo(
            f"{track}: {source.path / _MANIFEST} sha256={source.manifest_sha256}"
        )
    if result.blockers:
        typer.echo("Not publishable: " + "; ".join(result.blockers))
        raise typer.Exit(code=1)
    typer.echo("Sources are publishable and ready for assembly")


@app.command()
def assemble(
    retrieval: Path = typer.Option(..., exists=True, file_okay=False),
    citation: Path = typer.Option(..., exists=True, file_okay=False),
    output: Path = typer.Option(...),
    fixture_dry_run: bool = typer.Option(
        False,
        "--fixture-dry-run",
        help="Permit a sealed, explicitly non-publishable synthetic dry-run package.",
    ),
) -> None:
    """Assemble reports and a source-referencing manifest without provider access."""
    try:
        package = assemble_validation_package(
            retrieval,
            citation,
            output,
            fixture_dry_run=fixture_dry_run,
        )
    except ValidationPackageError as error:
        typer.echo(f"Validation assembly failed: {error}", err=True)
        raise typer.Exit(code=3) from None
    typer.echo(f"Assembled validation package: {package}")


@app.command()
def verify(
    package: Path = typer.Argument(..., exists=True, file_okay=False),
) -> None:
    """Verify the combined manifest, report, and resume projection hashes."""
    try:
        verify_validation_package(package)
    except ValidationPackageError as error:
        typer.echo(f"Validation verification failed: {error}", err=True)
        raise typer.Exit(code=3) from None
    typer.echo(f"Verified validation package: {package}")


__all__ = [
    "SourceRecompute",
    "ValidationPackageError",
    "ValidationPreflight",
    "ValidationSource",
    "assemble_validation_package",
    "app",
    "preflight_validation_sources",
    "verify_validation_package",
]
