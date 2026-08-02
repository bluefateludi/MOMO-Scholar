from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

import typer
from pydantic import ValidationError

from paper_agent.config import load_settings
from paper_agent.eval.dataset import DatasetValidationError, load_evaluation_dataset
from paper_agent.eval.evidence_package import (
    EvidencePackageBuilder,
    EvidencePackageError,
    verify_evidence_package,
)
from paper_agent.evidence.retriever import LexicalCandidateSource
from paper_agent.evidence.vector_source import VectorCandidateSource
from paper_agent.schemas import Chunk
from paper_agent.vector import InMemoryVectorStore, VectorRetriever
from paper_agent.vector.bailian import BailianTextEmbedder

from .contracts import (
    CANONICAL_KS,
    CANONICAL_MODES,
    CaseRetrievalResult,
    ModeFailure,
    RawRanking,
    RetrievalBenchmarkConfig,
)
from .report import render_retrieval_reports
from .runner import RetrievalBenchmarkRunner
from .statistics import score_benchmark


app = typer.Typer(help="Prepare, execute, and verify retrieval benchmarks.")

_EXIT_INPUT = 1
_EXIT_ACKNOWLEDGEMENT = 2
_EXIT_INTEGRITY = 3
_CHUNKING_VERSION = "abstract-per-paper/1.0"
_METRIC_VERSION = "retrieval-metrics/1.0"
_RECOMPUTE_MANIFEST = "recompute-manifest.json"
_RECOMPUTE_ARTIFACTS = (
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
    return "".join(_canonical_json(value) for value in values)


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8", newline="\n")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _new_directory(path: Path) -> None:
    if path.exists():
        raise ValueError(f"output path already exists: {path}")
    path.mkdir(parents=True)


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{path.name} is missing or invalid") from error


def _load_jsonl(path: Path) -> list[object]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ValueError(f"{path.name} is missing or invalid") from error
    values = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            values.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise ValueError(
                f"{path.name} contains invalid JSON at line {line_number}"
            ) from error
    return values


def _prepared_inputs(dataset_path: Path, split: str) -> dict[str, object]:
    dataset = load_evaluation_dataset(
        dataset_path,
        split=split,  # type: ignore[arg-type]
        allow_test_labels=split == "test",
    )
    prepared_cases = []
    corpus_rows = []
    gold_rows = []
    chunk_hashes = []
    for case in dataset.cases:
        chunks = []
        paper_chunk_ids: dict[str, str] = {}
        for paper in case.corpus.papers:
            chunk = Chunk(
                chunk_id=f"{case.case_id}:{paper.paper_id}:abstract",
                paper_id=paper.paper_id,
                section="Abstract",
                page=None,
                text=paper.abstract,
                token_count=len(paper.abstract.split()),
            )
            chunk_data = chunk.model_dump(mode="json")
            chunk_hash = _sha256_bytes(
                _canonical_json(chunk_data).encode("utf-8")
            )
            chunks.append(chunk_data)
            paper_chunk_ids[paper.paper_id] = chunk.chunk_id
            chunk_hashes.append(chunk_hash)
            corpus_rows.append(
                {
                    "case_id": case.case_id,
                    "paper_id": paper.paper_id,
                    "chunk": chunk_data,
                    "chunk_sha256": chunk_hash,
                }
            )

        relevance: dict[str, int] = {}
        if case.reference.relevant_paper_ids is not None:
            for paper_id in case.reference.relevant_paper_ids:
                relevance[paper_chunk_ids[paper_id]] = 1
        if case.reference.evidence is not None:
            for evidence in case.reference.evidence:
                chunk_id = paper_chunk_ids[evidence.paper_id]
                relevance[chunk_id] = max(
                    relevance.get(chunk_id, 0), evidence.relevance_grade
                )
        prepared_cases.append(
            {
                "case_id": case.case_id,
                "question": case.question,
                "chunks": chunks,
            }
        )
        gold_rows.append({"case_id": case.case_id, "relevance": relevance})

    corpus_payload = {"schema_version": "1.0", "chunks": corpus_rows}
    corpus_sha256 = _sha256_bytes(
        _canonical_json(corpus_payload).encode("utf-8")
    )
    return {
        "dataset": dataset,
        "prepared_cases": prepared_cases,
        "corpus_manifest": {**corpus_payload, "corpus_sha256": corpus_sha256},
        "gold_rows": gold_rows,
        "chunk_hashes": tuple(chunk_hashes),
        "corpus_sha256": corpus_sha256,
    }


def _write_prepared(
    *,
    dataset_path: Path,
    split: str,
    output: Path,
    candidate_limit: int,
    timeout_seconds: float,
    rrf_k: int,
    embedding_model: str,
    embedding_model_version: str,
    data_kind: str = "synthetic",
) -> None:
    if data_kind not in {"real", "synthetic"}:
        raise ValueError("data kind must be real or synthetic")
    inputs = _prepared_inputs(dataset_path, split)
    dataset = inputs["dataset"]
    config = RetrievalBenchmarkConfig(
        schema_version="1.0",
        dataset_fingerprint_sha256=dataset.fingerprint_sha256,
        ordered_case_ids=tuple(case.case_id for case in dataset.cases),
        corpus_sha256=inputs["corpus_sha256"],
        ordered_chunk_sha256=inputs["chunk_hashes"],
        candidate_limit=candidate_limit,
        timeout_seconds=float(timeout_seconds),
        rrf_k=rrf_k,
        embedding_model=embedding_model,
        embedding_model_version=embedding_model_version,
        chunking_config_sha256=_sha256_bytes(_CHUNKING_VERSION.encode("utf-8")),
        metric_versions=(_METRIC_VERSION,),
        ks=CANONICAL_KS,
        primary_k=8,
        modes=CANONICAL_MODES,
    )
    artifacts = {
        "dataset-manifest.json": _canonical_json(
            {
                **dataset.manifest.model_dump(mode="json"),
                "data_kind": data_kind,
                "selected_split": split,
                "dataset_fingerprint_sha256": dataset.fingerprint_sha256,
            }
        ),
        "corpus-manifest.json": _canonical_json(inputs["corpus_manifest"]),
        "gold-judgments.jsonl": _jsonl(inputs["gold_rows"]),
        "resolved-config.json": _canonical_json(config.model_dump(mode="json")),
        "prepared-cases.jsonl": _jsonl(inputs["prepared_cases"]),
    }
    _new_directory(output)
    for name, content in artifacts.items():
        _atomic_write(output / name, content)


def _load_config(root: Path) -> RetrievalBenchmarkConfig:
    try:
        return RetrievalBenchmarkConfig.model_validate(
            _load_json(root / "resolved-config.json")
        )
    except ValidationError as error:
        raise ValueError("resolved-config.json is invalid") from error


def _load_prepared_cases(
    root: Path, config: RetrievalBenchmarkConfig
) -> tuple[tuple[str, str, tuple[Chunk, ...]], ...]:
    rows = _load_jsonl(root / "prepared-cases.jsonl")
    parsed = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("prepared-cases.jsonl rows must be objects")
        try:
            case_id = row["case_id"]
            question = row["question"]
            chunks = tuple(Chunk.model_validate(item) for item in row["chunks"])
        except (KeyError, TypeError, ValidationError) as error:
            raise ValueError("prepared-cases.jsonl is invalid") from error
        if not isinstance(case_id, str) or not isinstance(question, str):
            raise ValueError("prepared-cases.jsonl is invalid")
        parsed.append((case_id, question, chunks))
    if tuple(item[0] for item in parsed) != config.ordered_case_ids:
        raise ValueError("prepared case order does not match resolved config")
    return tuple(parsed)


def _git_environment(model_version: str) -> dict[str, object]:
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
        "models": {"embedding": model_version},
    }


def _statistics_projections(statistics: dict[str, object]) -> dict[str, str]:
    return {
        "case-metrics.jsonl": _jsonl(statistics["case_metrics"]),
        "aggregate.json": _canonical_json(
            {
                "ks": statistics["ks"],
                "primary_k": statistics["primary_k"],
                "aggregate": statistics["aggregate"],
                "operations": statistics["operations"],
            }
        ),
        "confidence-intervals.json": _canonical_json(
            {
                "bootstrap": statistics["bootstrap"],
                "aggregate_ci_95": statistics["aggregate_ci_95"],
                "paired_deltas": statistics["paired_deltas"],
            }
        ),
    }


def _report_metadata(
    *,
    package: Path,
    config: RetrievalBenchmarkConfig,
    statistics: dict[str, object],
    recomputed: bool,
) -> dict[str, object]:
    dataset_manifest = _load_json(package / "dataset-manifest.json")
    environment = _load_json(package / "environment.json")
    if not isinstance(dataset_manifest, dict) or not isinstance(environment, dict):
        raise ValueError("report metadata authorities are invalid")
    models = environment.get("models")
    model_version = (
        models.get("embedding")
        if isinstance(models, dict)
        else config.embedding_model_version
    )
    operations = statistics["operations"]
    return {
        "case_count": len(config.ordered_case_ids),
        "data_kind": dataset_manifest.get("data_kind", "unknown"),
        "git_sha": environment.get("git_sha", "unknown"),
        "git_dirty": environment.get("git_dirty"),
        "embedding_model_version": model_version,
        "dataset_fingerprint_sha256": config.dataset_fingerprint_sha256,
        "corpus_sha256": config.corpus_sha256,
        "artifact_manifest_sha256": _sha256_file(
            package / "artifact-manifest.json"
        ),
        "sealed": True,
        "recomputed": recomputed,
        "complete": all(
            operations[mode]["failed"] == 0 for mode in CANONICAL_MODES
        ),
        "limitations": dataset_manifest.get("limitations", []),
    }


def _parse_authorities(
    package: Path, config: RetrievalBenchmarkConfig
) -> tuple[tuple[CaseRetrievalResult, ...], dict[str, dict[str, int]]]:
    ranking_rows = _load_jsonl(package / "raw-rankings.jsonl")
    failure_rows = _load_jsonl(package / "failures.jsonl")
    rankings = [RawRanking.model_validate(row) for row in ranking_rows]
    failures = [ModeFailure.model_validate(row) for row in failure_rows]
    cases = []
    for case_id in config.ordered_case_ids:
        cases.append(
            CaseRetrievalResult(
                case_id=case_id,
                rankings=tuple(item for item in rankings if item.case_id == case_id),
                failures=tuple(item for item in failures if item.case_id == case_id),
            )
        )
    if len(rankings) != sum(len(case.rankings) for case in cases) or len(
        failures
    ) != sum(len(case.failures) for case in cases):
        raise ValueError("raw authorities contain unknown case IDs")

    relevance: dict[str, dict[str, int]] = {}
    for row in _load_jsonl(package / "gold-judgments.jsonl"):
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("case_id"), str)
            or not isinstance(row.get("relevance"), dict)
            or not all(
                isinstance(key, str)
                and isinstance(value, int)
                and not isinstance(value, bool)
                and value >= 0
                for key, value in row["relevance"].items()
            )
        ):
            raise ValueError("gold-judgments.jsonl is invalid")
        relevance[row["case_id"]] = row["relevance"]
    return tuple(cases), relevance


def _recompute_publishable(metadata: dict[str, object]) -> bool:
    return (
        metadata.get("data_kind") == "real"
        and metadata.get("case_count") == 40
        and metadata.get("git_dirty") is False
        and metadata.get("sealed") is True
        and metadata.get("recomputed") is True
        and metadata.get("complete", True) is True
    )


def _seal_recompute_authority(
    *,
    source: Path,
    output: Path,
    metadata: dict[str, object],
) -> None:
    manifest = {
        "schema_version": "1.0",
        "package_kind": "retrieval_benchmark_recompute",
        "sealed": True,
        "recomputed": True,
        "publishable": _recompute_publishable(metadata),
        "sealed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": {
            "path": str(source.resolve()),
            "package_kind": "retrieval_benchmark",
            "artifact_manifest_sha256": _sha256_file(
                source / "artifact-manifest.json"
            ),
        },
        "artifacts": [
            {
                "path": name,
                "role": "recomputed_projection",
                "byte_length": (output / name).stat().st_size,
                "sha256": _sha256_file(output / name),
            }
            for name in _RECOMPUTE_ARTIFACTS
        ],
    }
    _atomic_write(output / _RECOMPUTE_MANIFEST, _canonical_json(manifest))


def _verify_recompute_artifacts(
    root: Path, manifest: dict[str, object]
) -> None:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != len(
        _RECOMPUTE_ARTIFACTS
    ):
        raise ValueError("recompute artifact entries are invalid")
    seen: set[str] = set()
    for entry in artifacts:
        if (
            not isinstance(entry, dict)
            or entry.get("path") not in _RECOMPUTE_ARTIFACTS
            or entry.get("role") != "recomputed_projection"
        ):
            raise ValueError("recompute artifact entries are invalid")
        name = str(entry["path"])
        if name in seen:
            raise ValueError("recompute artifact entries contain duplicates")
        seen.add(name)
        path = root / name
        if not path.is_file():
            raise ValueError(f"recomputed artifact is missing: {name}")
        if path.stat().st_size != entry.get("byte_length"):
            raise ValueError(f"recomputed artifact length mismatch: {name}")
        if _sha256_file(path) != entry.get("sha256"):
            raise ValueError(f"recomputed artifact hash mismatch: {name}")
    if seen != set(_RECOMPUTE_ARTIFACTS):
        raise ValueError("recompute artifact coverage is incomplete")


def _verify_recompute_authority(root: Path) -> dict[str, object]:
    manifest = _load_json(root / _RECOMPUTE_MANIFEST)
    if not isinstance(manifest, dict):
        raise ValueError("recompute manifest is invalid")
    if (
        manifest.get("package_kind") != "retrieval_benchmark_recompute"
        or manifest.get("sealed") is not True
        or manifest.get("recomputed") is not True
        or not isinstance(manifest.get("publishable"), bool)
    ):
        raise ValueError("recompute authority state is invalid")
    source_record = manifest.get("source")
    if not isinstance(source_record, dict):
        raise ValueError("recompute source authority is invalid")
    source_path = source_record.get("path")
    source_hash = source_record.get("artifact_manifest_sha256")
    if (
        not isinstance(source_path, str)
        or not source_path.strip()
        or source_record.get("package_kind") != "retrieval_benchmark"
        or not isinstance(source_hash, str)
        or len(source_hash) != 64
        or any(character not in "0123456789abcdef" for character in source_hash)
    ):
        raise ValueError("recompute source authority is invalid")
    source = Path(source_path)
    source_manifest = verify_evidence_package(source)
    if source_manifest.get("package_kind") != "retrieval_benchmark":
        raise ValueError("recompute source package kind is invalid")
    if _sha256_file(source / "artifact-manifest.json") != source_hash:
        raise ValueError("recompute source hash mismatch")
    _verify_recompute_artifacts(root, manifest)

    with tempfile.TemporaryDirectory(prefix="momo-retrieval-authority-") as temporary:
        expected = Path(temporary) / "recomputed"
        mismatches = _recompute(source, expected)
        if mismatches:
            raise ValueError(
                "recompute source projections mismatch: " + ", ".join(mismatches)
            )
        expected_manifest = _load_json(expected / _RECOMPUTE_MANIFEST)
        if (
            not isinstance(expected_manifest, dict)
            or manifest["publishable"] != expected_manifest.get("publishable")
        ):
            raise ValueError("recompute publication status is inconsistent")
        for name in _RECOMPUTE_ARTIFACTS:
            if (root / name).read_bytes() != (expected / name).read_bytes():
                raise ValueError(f"recomputed projection mismatch: {name}")
    return manifest


def _write_live_package(prepared: Path, output: Path) -> None:
    config = _load_config(prepared)
    prepared_cases = _load_prepared_cases(prepared, config)
    settings = load_settings()
    api_key = settings.dashscope_api_key
    if not api_key or not api_key.strip():
        raise ValueError("DASHSCOPE_API_KEY is required for run-live")
    if settings.bailian_region != "beijing":
        raise ValueError("BAILIAN_REGION must be beijing for run-live")
    environment = _git_environment(config.embedding_model_version)
    if environment.get("git_dirty") is not False:
        raise ValueError("publishable package requires a clean Git worktree")

    embedder = BailianTextEmbedder(
        api_key=api_key,
        model=config.embedding_model,
        region=settings.bailian_region,
        timeout=config.timeout_seconds,
    )
    _new_directory(output)
    results = tuple(
        RetrievalBenchmarkRunner(
            lexical_source=LexicalCandidateSource(),
            vector_source=VectorCandidateSource(
                VectorRetriever(
                    embedder=embedder,
                    store=InMemoryVectorStore(
                        embedding_model=config.embedding_model
                    ),
                )
            ),
        ).run_case(
            case_id=case_id,
            query=question,
            chunks=chunks,
            candidate_limit=config.candidate_limit,
            rrf_k=config.rrf_k,
        )
        for case_id, question, chunks in prepared_cases
    )
    relevance = {
        row["case_id"]: row["relevance"]
        for row in _load_jsonl(prepared / "gold-judgments.jsonl")
        if isinstance(row, dict)
    }
    statistics = score_benchmark(cases=results, relevance_by_case=relevance)
    projections = _statistics_projections(statistics)
    builder = EvidencePackageBuilder(output)
    for name in (
        "dataset-manifest.json",
        "corpus-manifest.json",
        "gold-judgments.jsonl",
        "resolved-config.json",
    ):
        builder.write_text(name, (prepared / name).read_text(encoding="utf-8"))
    builder.write_json("environment.json", environment)
    builder.write_text(
        "raw-rankings.jsonl",
        _jsonl(
            ranking.model_dump(mode="json")
            for result in results
            for ranking in result.rankings
        ),
    )
    builder.write_text(
        "failures.jsonl",
        _jsonl(
            failure.model_dump(mode="json")
            for result in results
            for failure in result.failures
        ),
    )
    for name, content in projections.items():
        builder.write_text(name, content)
    builder.write_text("logs.jsonl", "")
    builder.write_text("traces.jsonl", "")
    # Citation track artifacts are empty for retrieval-only packages.
    builder.write_text("assertions.jsonl", "")
    builder.write_text("citation-occurrences.jsonl", "")
    builder.write_text("evidence-matches.jsonl", "")
    builder.write_json("review-rubric.json", {})
    builder.write_text("calibration.jsonl", "")
    builder.write_text("judgments.jsonl", "")
    builder.write_text("adjudications.jsonl", "")
    dataset_manifest = _load_json(prepared / "dataset-manifest.json")
    if not isinstance(dataset_manifest, dict):
        raise ValueError("dataset-manifest.json is invalid")
    report_metadata = {
        "case_count": len(config.ordered_case_ids),
        "data_kind": dataset_manifest.get("data_kind", "synthetic"),
        "git_sha": environment["git_sha"],
        "git_dirty": environment["git_dirty"],
        "embedding_model_version": config.embedding_model_version,
        "dataset_fingerprint_sha256": config.dataset_fingerprint_sha256,
        "corpus_sha256": config.corpus_sha256,
        "artifact_manifest_sha256": _sha256_bytes(
            builder.root.joinpath("raw-rankings.jsonl").read_bytes()
        ),
        "sealed": True,
        "recomputed": False,
        "complete": all(
            statistics["operations"][mode]["failed"] == 0
            for mode in CANONICAL_MODES
        ),
        "limitations": [],
    }
    report, resume = render_retrieval_reports(statistics, report_metadata)
    builder.write_text("report.md", report)
    builder.write_text("resume-evidence.md", resume)
    builder.seal(package_kind="retrieval_benchmark")


def _recompute(package: Path, output: Path) -> list[str]:
    verify_evidence_package(package)
    config = _load_config(package)
    cases, relevance = _parse_authorities(package, config)
    statistics = score_benchmark(cases=cases, relevance_by_case=relevance)
    projections = _statistics_projections(statistics)
    metadata = _report_metadata(
        package=package,
        config=config,
        statistics=statistics,
        recomputed=True,
    )
    report, resume = render_retrieval_reports(statistics, metadata)

    _new_directory(output)
    for name, content in projections.items():
        _atomic_write(output / name, content)
    _atomic_write(output / "report.md", report)
    _atomic_write(output / "resume-evidence.md", resume)
    mismatches = [
        name
        for name, content in projections.items()
        if (package / name).read_bytes() != content.encode("utf-8")
    ]
    if not mismatches:
        _seal_recompute_authority(
            source=package,
            output=output,
            metadata=metadata,
        )
    return mismatches


@app.command()
def prepare(
    dataset: Path = typer.Option(..., exists=True, file_okay=False),
    split: str = typer.Option("validation"),
    output: Path = typer.Option(...),
    candidate_limit: int = typer.Option(30, min=1),
    timeout_seconds: float = typer.Option(30.0, min=0.001),
    rrf_k: int = typer.Option(60, min=1),
    embedding_model: str = typer.Option("text-embedding-v4"),
    embedding_model_version: str = typer.Option(...),
    data_kind: str = typer.Option(
        "synthetic",
        help="Use 'real' only for a licensed, non-fixture dataset.",
    ),
) -> None:
    """Validate and freeze benchmark inputs without provider access."""
    try:
        _write_prepared(
            dataset_path=dataset,
            split=split,
            output=output,
            candidate_limit=candidate_limit,
            timeout_seconds=timeout_seconds,
            rrf_k=rrf_k,
            embedding_model=embedding_model,
            embedding_model_version=embedding_model_version,
            data_kind=data_kind,
        )
    except (DatasetValidationError, OSError, ValueError) as error:
        typer.echo(f"Preparation failed: {error}", err=True)
        raise typer.Exit(code=_EXIT_INPUT) from None
    typer.echo(f"Prepared benchmark: {output}")


@app.command("run-live")
def run_live(
    prepared: Path = typer.Option(..., exists=True, file_okay=False),
    output: Path = typer.Option(...),
    acknowledge_provider_costs: bool = typer.Option(
        False,
        "--acknowledge-provider-costs",
        help="Acknowledge that this command makes billable provider requests.",
    ),
) -> None:
    """Execute the explicit provider-backed retrieval benchmark."""
    if not acknowledge_provider_costs:
        typer.echo(
            "run-live requires --acknowledge-provider-costs",
            err=True,
        )
        raise typer.Exit(code=_EXIT_ACKNOWLEDGEMENT)
    try:
        _write_live_package(prepared, output)
    except (EvidencePackageError, OSError, ValueError) as error:
        typer.echo(f"Live benchmark preflight or execution failed: {error}", err=True)
        raise typer.Exit(code=_EXIT_INPUT) from None
    typer.echo(f"Sealed experiment: {output}")


@app.command()
def recompute(
    package: Path = typer.Option(..., exists=True, file_okay=False),
    output: Path = typer.Option(...),
) -> None:
    """Recompute projections from a sealed package without provider access."""
    try:
        mismatches = _recompute(package, output)
    except EvidencePackageError as error:
        typer.echo(f"Recompute integrity failure: {error}", err=True)
        raise typer.Exit(code=_EXIT_INTEGRITY) from None
    except (OSError, ValidationError, ValueError) as error:
        typer.echo(f"Recompute failed: {error}", err=True)
        raise typer.Exit(code=_EXIT_INPUT) from None
    if mismatches:
        typer.echo(
            f"Projection mismatch: {', '.join(mismatches)}",
            err=True,
        )
        raise typer.Exit(code=_EXIT_INTEGRITY)
    typer.echo(f"Sealed recomputed authority: {output}")


@app.command()
def verify(
    package: Path = typer.Argument(..., exists=True, file_okay=False),
) -> None:
    """Verify a sealed source package or recomputed publication authority."""
    try:
        if (package / _RECOMPUTE_MANIFEST).is_file():
            _verify_recompute_authority(package)
        else:
            verify_evidence_package(package)
    except (EvidencePackageError, OSError, ValueError) as error:
        typer.echo(f"Verification failed: {error}", err=True)
        raise typer.Exit(code=_EXIT_INTEGRITY) from None
    typer.echo(f"Verified package: {package}")


__all__ = ["app"]
