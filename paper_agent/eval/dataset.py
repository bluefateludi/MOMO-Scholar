from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from pydantic import ValidationError

from paper_agent.eval.contracts import (
    AuditedSplit,
    DatasetManifest,
    EvalCase,
    EvaluationDataset,
    EvaluationDatasetAudit,
    SplitName,
)


class DatasetValidationError(ValueError):
    """Raised when an evaluation dataset cannot be selected safely."""


def _resolve_selected_path(dataset_root: Path, declared_path: str) -> Path:
    relative_path = Path(declared_path)
    if relative_path.is_absolute():
        raise DatasetValidationError("selected split path must be relative, not absolute")
    try:
        resolved_root = dataset_root.resolve()
        candidate = (resolved_root / relative_path).resolve(strict=False)
    except OSError as error:
        raise DatasetValidationError("selected split path has an I/O error") from error
    try:
        candidate.relative_to(resolved_root)
    except ValueError as error:
        raise DatasetValidationError("selected split path resolves outside dataset root") from error
    if candidate == resolved_root:
        raise DatasetValidationError("selected split path must identify a file")
    return candidate


def _read_utf8(path: Path, identity: str) -> str:
    display_name = Path(identity).name
    if path.is_dir():
        raise DatasetValidationError(f"{display_name} is not a file")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeError as error:
        raise DatasetValidationError(
            f"{display_name} is not valid UTF-8"
        ) from error
    except FileNotFoundError as error:
        raise DatasetValidationError(f"{display_name} is missing") from error
    except IsADirectoryError as error:
        raise DatasetValidationError(f"{display_name} is not a file") from error
    except OSError as error:
        raise DatasetValidationError(f"{display_name} has an I/O error") from error


def _load_manifest(dataset_root: Path) -> DatasetManifest:
    try:
        manifest_data = json.loads(
            _read_utf8(dataset_root / "dataset.json", "dataset.json")
        )
    except json.JSONDecodeError as error:
        raise DatasetValidationError("dataset.json contains invalid JSON") from error
    try:
        return DatasetManifest.model_validate(manifest_data)
    except ValidationError as error:
        raise DatasetValidationError(
            "dataset.json has an unsupported schema or invalid manifest"
        ) from error


def _load_selected_dataset(
    dataset_root: Path,
    manifest: DatasetManifest,
    split: SplitName,
    *,
    case_path: Path | None = None,
) -> EvaluationDataset:
    declaration = getattr(manifest.splits, split)
    if case_path is None:
        case_path = _resolve_selected_path(dataset_root, declaration.path)
    case_identity = Path(declaration.path).name
    case_text = _read_utf8(case_path, case_identity)
    parsed_cases: list[EvalCase] = []
    for line_number, line in enumerate(case_text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            case_data = json.loads(line)
        except json.JSONDecodeError as error:
            raise DatasetValidationError(
                f"{case_identity} contains invalid JSON at line {line_number}"
            ) from error
        try:
            parsed_cases.append(EvalCase.model_validate(case_data))
        except ValidationError as error:
            raise DatasetValidationError(
                f"{case_identity} has an invalid case at line {line_number}"
            ) from error
    cases = tuple(parsed_cases)

    if len(cases) != declaration.count:
        raise DatasetValidationError(
            f"{case_identity} case count does not match the manifest"
        )
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise DatasetValidationError(f"{case_identity} contains duplicate case IDs")
    if any(case.metadata.split != split for case in cases):
        raise DatasetValidationError(
            f"{case_identity} contains a case for a different split"
        )

    declared_sources = {source.name: source for source in manifest.sources}
    actual_source_counts = Counter(case.metadata.source for case in cases)
    for source_name in actual_source_counts:
        source = declared_sources.get(source_name)
        if source is None:
            raise DatasetValidationError(
                f"{case_identity} contains an undeclared source"
            )
        if not source.assets:
            raise DatasetValidationError(
                f"{case_identity} source has no licensed provenance assets"
            )
    expected_source_counts = {
        row.source: getattr(row, split) for row in manifest.source_split_counts
    }
    expected_nonzero = {
        source: count for source, count in expected_source_counts.items() if count
    }
    if dict(actual_source_counts) != expected_nonzero:
        raise DatasetValidationError(
            f"{case_identity} source counts do not match the manifest"
        )

    payload = {
        "manifest": manifest.model_dump(mode="json"),
        "split": split,
        "cases": [case.model_dump(mode="json") for case in cases],
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    fingerprint = hashlib.sha256(canonical).hexdigest()

    try:
        return EvaluationDataset(
            manifest=manifest,
            split=split,
            cases=cases,
            fingerprint_sha256=fingerprint,
        )
    except ValidationError as error:
        raise DatasetValidationError(
            f"{case_identity} is inconsistent with the selected split"
        ) from error


def load_evaluation_dataset(
    root: str | Path,
    *,
    split: SplitName,
    allow_test_labels: bool = False,
) -> EvaluationDataset:
    if split == "test" and allow_test_labels is not True:
        raise DatasetValidationError("test labels require allow_test_labels=True")

    dataset_root = Path(root)
    manifest = _load_manifest(dataset_root)
    return _load_selected_dataset(dataset_root, manifest, split)


def audit_evaluation_dataset(
    root: str | Path,
    *,
    include_test_labels: bool = False,
) -> EvaluationDatasetAudit:
    dataset_root = Path(root)
    manifest = _load_manifest(dataset_root)
    audited_splits: tuple[SplitName, ...] = (
        ("development", "validation", "test")
        if include_test_labels is True
        else ("development", "validation")
    )

    selected_paths: dict[SplitName, Path] = {}
    for split in audited_splits:
        declaration = getattr(manifest.splits, split)
        selected_paths[split] = _resolve_selected_path(
            dataset_root, declaration.path
        )
    if len(set(selected_paths.values())) != len(selected_paths):
        raise DatasetValidationError("audited split paths must resolve uniquely")

    datasets = tuple(
        _load_selected_dataset(
            dataset_root,
            manifest,
            split,
            case_path=selected_paths[split],
        )
        for split in audited_splits
    )
    all_case_ids = [case.case_id for dataset in datasets for case in dataset.cases]
    if len(all_case_ids) != len(set(all_case_ids)):
        raise DatasetValidationError("audited splits contain duplicate case IDs")

    split_results = tuple(
        AuditedSplit(
            split=dataset.split,
            case_ids=tuple(case.case_id for case in dataset.cases),
            fingerprint_sha256=dataset.fingerprint_sha256,
        )
        for dataset in datasets
    )
    payload = {
        "manifest": manifest.model_dump(mode="json"),
        "audited_splits": list(audited_splits),
        "split_fingerprints": [
            result.fingerprint_sha256 for result in split_results
        ],
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    fingerprint = hashlib.sha256(canonical).hexdigest()
    return EvaluationDatasetAudit(
        root=str(dataset_root.resolve()),
        manifest=manifest,
        audited_splits=audited_splits,
        splits=split_results,
        fingerprint_sha256=fingerprint,
    )

__all__ = [
    "DatasetValidationError",
    "audit_evaluation_dataset",
    "load_evaluation_dataset",
]
