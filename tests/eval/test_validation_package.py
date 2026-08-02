from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from paper_agent.eval.evidence_package import EvidencePackageBuilder
from paper_agent.eval.validation_package import (
    SourceRecompute,
    ValidationPackageError,
    assemble_validation_package,
    preflight_validation_sources,
    verify_validation_package,
)


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_package(
    root: Path,
    *,
    track: str,
    case_ids: list[str],
    data_kind: str = "synthetic",
) -> Path:
    package = root / track
    builder = EvidencePackageBuilder(package)
    dataset = {
        "dataset_id": "momo-eval-v1",
        "dataset_version": "2026-07-26",
        "selected_split": "validation",
        "data_kind": data_kind,
        "dataset_fingerprint_sha256": ("a" if track == "retrieval" else "b") * 64,
    }
    config = {
        "schema_version": "1.0",
        "metric_versions": [f"{track}-metrics/1.0"],
    }
    if track == "retrieval":
        config["ordered_case_ids"] = case_ids
        config["ordered_chunk_sha256"] = ["c" * 64]
        package_kind = "retrieval_benchmark"
    else:
        config["cases"] = [
            {
                "case_id": case_id,
                "duration_ms": 1.0,
                "unscorable_assertion_ids": [],
                "failure_reason_code": None,
            }
            for case_id in case_ids
        ]
        config["ordered_chunk_sha256"] = ["d" * 64]
        package_kind = "citation_baseline"

    values: dict[str, object] = {
        "dataset-manifest.json": dataset,
        "corpus-manifest.json": {
            "corpus_sha256": ("e" if track == "retrieval" else "f") * 64
        },
        "gold-judgments.jsonl": "",
        "resolved-config.json": config,
        "environment.json": {
            "git_sha": "1" * 40,
            "git_dirty": False,
            "models": {track: f"{track}-model@fixture"},
        },
        "raw-rankings.jsonl": "",
        "case-metrics.jsonl": "",
        "aggregate.json": {"track": track},
        "confidence-intervals.json": {"track": track},
        "failures.jsonl": "",
        "logs.jsonl": "",
        "traces.jsonl": "",
        "report.md": f"# {track.title()} fixture report\n",
        "resume-evidence.md": "# Resume Evidence\n\nNo resume-ready numeric claims.\n",
        "assertions.jsonl": "",
        "citation-occurrences.jsonl": "",
        "evidence-matches.jsonl": "",
        "review-rubric.json": {},
        "calibration.jsonl": "",
        "judgments.jsonl": "",
        "adjudications.jsonl": "",
    }
    for name, value in values.items():
        if isinstance(value, str):
            builder.write_text(name, value)
        else:
            builder.write_json(name, value)
    builder.seal(package_kind=package_kind)
    return package


def _copy_recompute(package: Path, output: Path) -> list[str]:
    output.mkdir()
    for name in SourceRecompute.PROJECTIONS:
        (output / name).write_bytes((package / name).read_bytes())
    return []


def test_synthetic_preflight_validates_full_40_plus_20_contract_without_publishable_claims(
    tmp_path: Path,
) -> None:
    retrieval = _source_package(
        tmp_path,
        track="retrieval",
        case_ids=[f"retrieval-{index:02d}" for index in range(40)],
    )
    citation = _source_package(
        tmp_path,
        track="citation",
        case_ids=[f"citation-{index:02d}" for index in range(20)],
    )

    result = preflight_validation_sources(
        retrieval,
        citation,
        recomputers={"retrieval": _copy_recompute, "citation": _copy_recompute},
    )

    assert result.case_count == 60
    assert result.track_case_counts == {"retrieval": 40, "citation": 20}
    assert result.recomputed is True
    assert result.publishable is False
    assert result.blockers == ("retrieval source is synthetic", "citation source is synthetic")
    assert result.sources["retrieval"].manifest_sha256 == _sha256(
        retrieval / "artifact-manifest.json"
    )


def test_preflight_rejects_overlap_and_projection_recompute_mismatch(tmp_path: Path) -> None:
    retrieval = _source_package(
        tmp_path / "overlap",
        track="retrieval",
        case_ids=["shared", *[f"r-{index}" for index in range(39)]],
    )
    citation = _source_package(
        tmp_path / "overlap",
        track="citation",
        case_ids=["shared", *[f"c-{index}" for index in range(19)]],
    )
    with pytest.raises(ValidationPackageError, match="overlap"):
        preflight_validation_sources(
            retrieval,
            citation,
            recomputers={"retrieval": _copy_recompute, "citation": _copy_recompute},
        )

    clean = tmp_path / "mismatch"
    retrieval = _source_package(
        clean,
        track="retrieval",
        case_ids=[f"r-{index}" for index in range(40)],
    )
    citation = _source_package(
        clean,
        track="citation",
        case_ids=[f"c-{index}" for index in range(20)],
    )

    def mismatching_recompute(package: Path, output: Path) -> list[str]:
        _copy_recompute(package, output)
        (output / "aggregate.json").write_text(_json({"changed": True}), encoding="utf-8")
        return []

    with pytest.raises(ValidationPackageError, match="recomputed projection mismatch"):
        preflight_validation_sources(
            retrieval,
            citation,
            recomputers={
                "retrieval": mismatching_recompute,
                "citation": _copy_recompute,
            },
        )


def test_assembly_refuses_synthetic_sources_and_verifier_detects_report_mutation(
    tmp_path: Path,
) -> None:
    retrieval = _source_package(
        tmp_path / "sources",
        track="retrieval",
        case_ids=[f"r-{index}" for index in range(40)],
    )
    citation = _source_package(
        tmp_path / "sources",
        track="citation",
        case_ids=[f"c-{index}" for index in range(20)],
    )
    with pytest.raises(ValidationPackageError, match="not publishable"):
        assemble_validation_package(
            retrieval,
            citation,
            tmp_path / "validation",
            recomputers={"retrieval": _copy_recompute, "citation": _copy_recompute},
        )

    # Exercise the deterministic writer without pretending fixture inputs are real.
    package = assemble_validation_package(
        retrieval,
        citation,
        tmp_path / "fixture-dry-run",
        recomputers={"retrieval": _copy_recompute, "citation": _copy_recompute},
        fixture_dry_run=True,
    )
    manifest = verify_validation_package(package)
    assert manifest["publishable"] is False
    assert "No resume-ready numeric claims" in (package / "resume-evidence.md").read_text()
    assert "fixture report" not in (package / "resume-evidence.md").read_text()

    source_manifest = retrieval / "artifact-manifest.json"
    original_source_manifest = source_manifest.read_bytes()
    source_manifest.write_bytes(original_source_manifest + b" ")
    with pytest.raises(ValidationPackageError, match="retrieval source hash mismatch"):
        verify_validation_package(package)
    source_manifest.write_bytes(original_source_manifest)

    with (package / "report.md").open("a", encoding="utf-8") as handle:
        handle.write("mutated\n")
    with pytest.raises(ValidationPackageError, match="(length|hash) mismatch"):
        verify_validation_package(package)
