from __future__ import annotations

import hashlib
import json
import shutil
from copy import deepcopy
from pathlib import Path

import pytest

from paper_agent.eval.contracts import DatasetManifest, EvalCase
from paper_agent.eval import (
    DatasetValidationError,
    audit_evaluation_dataset,
    load_evaluation_dataset,
)


FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "evaluation" / "minimal-dataset"


def _read_fixture_payload(root: Path, split: str) -> tuple[dict[str, object], list[dict[str, object]]]:
    manifest = json.loads((root / "dataset.json").read_text(encoding="utf-8"))
    split_path = manifest["splits"][split]["path"]
    cases = [json.loads(line) for line in (root / split_path).read_text(encoding="utf-8").splitlines()]
    return manifest, cases


def _expected_fingerprint(manifest: dict[str, object], split: str, cases: list[dict[str, object]]) -> str:
    canonical_manifest = DatasetManifest.model_validate(manifest).model_dump(mode="json")
    canonical_cases = [EvalCase.model_validate(case).model_dump(mode="json") for case in cases]
    payload = {"manifest": canonical_manifest, "split": split, "cases": canonical_cases}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _rewrite_cases(path: Path, cases: list[dict[str, object]], *, pretty: bool = False) -> None:
    if pretty:
        lines = [json.dumps(case, ensure_ascii=False, sort_keys=False) for case in cases]
    else:
        lines = [json.dumps(case, ensure_ascii=False, separators=(",", ":")) for case in cases]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_selected_development_loads_ordered_cases_and_declared_count() -> None:
    dataset = load_evaluation_dataset(FIXTURE_ROOT, split="development")

    assert dataset.split == "development"
    assert tuple(case.case_id for case in dataset.cases) == (
        "scifact-development-001",
        "qasper-development-001",
    )
    assert len(dataset.cases) == dataset.manifest.splits.development.count == 2


def test_fingerprint_is_repeatable_and_matches_independent_literal() -> None:
    manifest, cases = _read_fixture_payload(FIXTURE_ROOT, "development")
    expected = _expected_fingerprint(manifest, "development", cases)

    first = load_evaluation_dataset(FIXTURE_ROOT, split="development")
    second = load_evaluation_dataset(FIXTURE_ROOT, split="development")

    assert expected == "e1b1b66cc38c031a680ba8e0519c243b72ab87c7db65d1662df35d2f4b8e2cfa"
    assert first.fingerprint_sha256 == second.fingerprint_sha256 == expected


def test_fingerprint_changes_when_selected_case_order_changes(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    shutil.copytree(FIXTURE_ROOT, root)
    _, cases = _read_fixture_payload(root, "development")
    _rewrite_cases(root / "development.jsonl", list(reversed(cases)))

    original = load_evaluation_dataset(FIXTURE_ROOT, split="development")
    reordered = load_evaluation_dataset(root, split="development")

    assert reordered.fingerprint_sha256 != original.fingerprint_sha256


def test_fingerprint_changes_when_selected_gold_label_changes(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    shutil.copytree(FIXTURE_ROOT, root)
    _, cases = _read_fixture_payload(root, "development")
    cases[1]["reference"]["answer"] = "A different licensed gold label."  # type: ignore[index]
    _rewrite_cases(root / "development.jsonl", cases)

    original = load_evaluation_dataset(FIXTURE_ROOT, split="development")
    changed = load_evaluation_dataset(root, split="development")

    assert changed.fingerprint_sha256 != original.fingerprint_sha256


def test_fingerprint_excludes_dataset_root(tmp_path: Path) -> None:
    moved_root = tmp_path / "moved" / "minimal-dataset"
    shutil.copytree(FIXTURE_ROOT, moved_root)

    original = load_evaluation_dataset(FIXTURE_ROOT, split="development")
    moved = load_evaluation_dataset(moved_root, split="development")

    assert moved.fingerprint_sha256 == original.fingerprint_sha256


def test_fingerprint_excludes_json_formatting_and_key_order(tmp_path: Path) -> None:
    root = tmp_path / "reformatted"
    shutil.copytree(FIXTURE_ROOT, root)
    manifest, cases = _read_fixture_payload(root, "development")
    reversed_manifest = dict(reversed(list(manifest.items())))
    (root / "dataset.json").write_text(
        json.dumps(reversed_manifest, indent=4, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    reversed_cases = [dict(reversed(list(case.items()))) for case in cases]
    _rewrite_cases(root / "development.jsonl", reversed_cases, pretty=True)

    original = load_evaluation_dataset(FIXTURE_ROOT, split="development")
    reformatted = load_evaluation_dataset(root, split="development")

    assert reformatted.fingerprint_sha256 == original.fingerprint_sha256


@pytest.mark.parametrize("test_file_state", ["missing", "malformed"])
@pytest.mark.parametrize("selected_split", ["development", "validation"])
def test_selected_non_test_split_ignores_unselected_test_file(
    tmp_path: Path, test_file_state: str, selected_split: str
) -> None:
    root = tmp_path / "dataset"
    shutil.copytree(FIXTURE_ROOT, root)
    test_path = root / "test.jsonl"
    if test_file_state == "missing":
        test_path.unlink()
    else:
        test_path.write_text("{malformed\n", encoding="utf-8")

    dataset = load_evaluation_dataset(root, split=selected_split)

    assert dataset.split == selected_split
    assert len(dataset.cases) == 2


@pytest.mark.parametrize("selected_split", ["development", "validation"])
def test_selected_non_test_split_never_opens_test_file(
    monkeypatch: pytest.MonkeyPatch, selected_split: str
) -> None:
    original_open = Path.open
    guarded_path = (FIXTURE_ROOT / "test.jsonl").resolve()

    def guarded_open(path: Path, *args: object, **kwargs: object):
        if path.resolve() == guarded_path:
            raise AssertionError("unselected test labels were opened")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)

    dataset = load_evaluation_dataset(FIXTURE_ROOT, split=selected_split)

    assert dataset.split == selected_split


def test_selected_test_split_requires_explicit_label_authorization() -> None:
    with pytest.raises(DatasetValidationError, match="allow_test_labels"):
        load_evaluation_dataset(FIXTURE_ROOT, split="test")


@pytest.mark.parametrize(
    "allow_test_labels",
    [
        pytest.param(False, id="false"),
        pytest.param(1, id="integer-one"),
        pytest.param("false", id="truthy-string"),
        pytest.param(object(), id="object"),
    ],
)
def test_selected_test_split_rejects_non_true_label_authorization(
    allow_test_labels: object,
) -> None:
    with pytest.raises(DatasetValidationError, match="allow_test_labels"):
        load_evaluation_dataset(
            FIXTURE_ROOT,
            split="test",
            allow_test_labels=allow_test_labels,  # type: ignore[arg-type]
        )


def test_selected_test_split_loads_when_labels_are_authorized() -> None:
    dataset = load_evaluation_dataset(
        FIXTURE_ROOT, split="test", allow_test_labels=True
    )

    assert tuple(case.case_id for case in dataset.cases) == (
        "scifact-test-001",
        "qasper-test-001",
    )

@pytest.mark.parametrize("schema_version", ["2.0", "1.1"])
def test_schema_version_is_reported_with_manifest_context(
    tmp_path: Path, schema_version: str
) -> None:
    root = tmp_path / "dataset"
    shutil.copytree(FIXTURE_ROOT, root)
    manifest, _ = _read_fixture_payload(root, "development")
    manifest["schema_version"] = schema_version
    (root / "dataset.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(DatasetValidationError) as caught:
        load_evaluation_dataset(root, split="development")

    message = str(caught.value)
    assert "dataset.json" in message
    assert "schema" in message.lower()

def test_malformed_manifest_json_is_sanitized(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    shutil.copytree(FIXTURE_ROOT, root)
    (root / "dataset.json").write_text('{"SECRET_MANIFEST":', encoding="utf-8")

    with pytest.raises(DatasetValidationError) as caught:
        load_evaluation_dataset(root, split="development")

    message = str(caught.value)
    assert "dataset.json" in message
    assert "json" in message.lower()
    assert "SECRET_MANIFEST" not in message


def test_malformed_selected_jsonl_reports_physical_line_without_content(
    tmp_path: Path,
) -> None:
    root = tmp_path / "dataset"
    shutil.copytree(FIXTURE_ROOT, root)
    (root / "development.jsonl").write_text(
        '\n\n{"SECRET_GOLD_LABEL":', encoding="utf-8"
    )

    with pytest.raises(DatasetValidationError) as caught:
        load_evaluation_dataset(root, split="development")

    message = str(caught.value)
    assert "development.jsonl" in message
    assert "line 3" in message.lower()
    assert "json" in message.lower()
    assert "SECRET_GOLD_LABEL" not in message

@pytest.mark.parametrize("file_name", ["dataset.json", "development.jsonl"])
def test_invalid_utf8_is_wrapped_with_file_context(
    tmp_path: Path, file_name: str
) -> None:
    root = tmp_path / "dataset"
    shutil.copytree(FIXTURE_ROOT, root)
    (root / file_name).write_bytes(b"\xffSECRET_UTF8")

    with pytest.raises(DatasetValidationError) as caught:
        load_evaluation_dataset(root, split="development")

    message = str(caught.value)
    assert file_name in message
    assert "utf-8" in message.lower()
    assert "SECRET_UTF8" not in message


@pytest.mark.parametrize("file_name", ["dataset.json", "development.jsonl"])
def test_directory_path_is_wrapped_with_file_context(
    tmp_path: Path, file_name: str
) -> None:
    root = tmp_path / "dataset"
    shutil.copytree(FIXTURE_ROOT, root)
    target = root / file_name
    target.unlink()
    target.mkdir()

    with pytest.raises(DatasetValidationError) as caught:
        load_evaluation_dataset(root, split="development")

    message = str(caught.value)
    assert file_name in message
    assert "file" in message.lower()


@pytest.mark.parametrize("file_name", ["dataset.json", "development.jsonl"])
def test_missing_path_is_wrapped_with_file_context(
    tmp_path: Path, file_name: str
) -> None:
    root = tmp_path / "dataset"
    shutil.copytree(FIXTURE_ROOT, root)
    (root / file_name).unlink()

    with pytest.raises(DatasetValidationError) as caught:
        load_evaluation_dataset(root, split="development")

    message = str(caught.value)
    assert file_name in message
    assert "missing" in message.lower()


@pytest.mark.parametrize("file_name", ["dataset.json", "development.jsonl"])
def test_os_error_is_wrapped_without_leaking_detail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    file_name: str,
) -> None:
    root = tmp_path / "dataset"
    shutil.copytree(FIXTURE_ROOT, root)
    target = (root / file_name).resolve()
    original_open = Path.open

    def failing_open(path: Path, *args: object, **kwargs: object):
        if path.resolve() == target:
            raise OSError("SECRET_OS_DETAIL")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failing_open)

    with pytest.raises(DatasetValidationError) as caught:
        load_evaluation_dataset(root, split="development")

    message = str(caught.value)
    assert file_name in message
    assert "i/o" in message.lower()
    assert "SECRET_OS_DETAIL" not in message

def _declare_split_path(root: Path, split: str, declared_path: str) -> None:
    manifest = json.loads((root / "dataset.json").read_text(encoding="utf-8"))
    manifest["splits"][split]["path"] = declared_path
    (root / "dataset.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_selected_path_rejects_absolute_declaration(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    external = tmp_path / "external.jsonl"
    shutil.copytree(FIXTURE_ROOT, root)
    shutil.copyfile(root / "development.jsonl", external)
    _declare_split_path(root, "development", str(external.resolve()))

    with pytest.raises(DatasetValidationError, match="absolute"):
        load_evaluation_dataset(root, split="development")


def test_selected_path_rejects_parent_traversal(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    external = tmp_path / "external.jsonl"
    shutil.copytree(FIXTURE_ROOT, root)
    shutil.copyfile(root / "development.jsonl", external)
    _declare_split_path(root, "development", "../external.jsonl")

    with pytest.raises(DatasetValidationError, match="outside"):
        load_evaluation_dataset(root, split="development")


def test_selected_path_rejects_sibling_prefix_escape(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    sibling = tmp_path / "dataset-evil"
    shutil.copytree(FIXTURE_ROOT, root)
    sibling.mkdir()
    shutil.copyfile(root / "development.jsonl", sibling / "development.jsonl")
    _declare_split_path(
        root, "development", "../dataset-evil/development.jsonl"
    )

    with pytest.raises(DatasetValidationError, match="outside"):
        load_evaluation_dataset(root, split="development")


def test_selected_path_rejects_symlink_escape_when_supported(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    external = tmp_path / "external"
    shutil.copytree(FIXTURE_ROOT, root)
    external.mkdir()
    shutil.copyfile(root / "development.jsonl", external / "development.jsonl")
    link = root / "external-link"
    try:
        link.symlink_to(external, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlinks are unavailable: {type(error).__name__}")
    _declare_split_path(root, "development", "external-link/development.jsonl")

    with pytest.raises(DatasetValidationError, match="outside"):
        load_evaluation_dataset(root, split="development")


def test_selected_path_accepts_safe_nested_declaration(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    nested = root / "nested"
    shutil.copytree(FIXTURE_ROOT, root)
    nested.mkdir()
    (root / "development.jsonl").replace(nested / "development.jsonl")
    _declare_split_path(root, "development", "nested/development.jsonl")

    dataset = load_evaluation_dataset(root, split="development")

    assert tuple(case.case_id for case in dataset.cases) == (
        "scifact-development-001",
        "qasper-development-001",
    )


@pytest.mark.parametrize("selected_split", ["development", "validation"])
def test_selected_path_never_resolves_or_opens_test_labels(
    monkeypatch: pytest.MonkeyPatch, selected_split: str
) -> None:
    guarded_path = FIXTURE_ROOT / "test.jsonl"
    original_resolve = Path.resolve
    original_open = Path.open

    def guarded_resolve(path: Path, *args: object, **kwargs: object) -> Path:
        if path == guarded_path:
            raise AssertionError("unselected test labels were resolved")
        return original_resolve(path, *args, **kwargs)

    def guarded_open(path: Path, *args: object, **kwargs: object):
        if path == guarded_path:
            raise AssertionError("unselected test labels were opened")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", guarded_resolve)
    monkeypatch.setattr(Path, "open", guarded_open)

    dataset = load_evaluation_dataset(FIXTURE_ROOT, split=selected_split)

    assert dataset.split == selected_split

def _write_manifest(root: Path, manifest: dict[str, object]) -> None:
    (root / "dataset.json").write_text(json.dumps(manifest), encoding="utf-8")


@pytest.mark.parametrize(
    ("violation", "message"),
    [
        ("count", "case count"),
        ("metadata split", "different split"),
        ("duplicate ID", "duplicate case IDs"),
        ("undeclared source", "undeclared source"),
        ("missing provenance", "licensed provenance"),
        ("source count", "source counts"),
    ],
)
def test_selected_split_rejects_manifest_and_case_membership_violations(
    tmp_path: Path, violation: str, message: str
) -> None:
    root = tmp_path / "dataset"
    shutil.copytree(FIXTURE_ROOT, root)
    manifest, cases = _read_fixture_payload(root, "development")
    if violation == "count":
        manifest["splits"]["development"]["count"] = 3  # type: ignore[index]
        manifest["source_split_counts"][0]["development"] = 2  # type: ignore[index]
        _write_manifest(root, manifest)
    elif violation == "metadata split":
        cases[0]["metadata"]["split"] = "validation"  # type: ignore[index]
        _rewrite_cases(root / "development.jsonl", cases)
    elif violation == "duplicate ID":
        cases[1]["case_id"] = cases[0]["case_id"]  # type: ignore[index]
        _rewrite_cases(root / "development.jsonl", cases)
    elif violation == "undeclared source":
        cases[0]["metadata"]["source"] = "Unknown"  # type: ignore[index]
        _rewrite_cases(root / "development.jsonl", cases)
    elif violation == "missing provenance":
        manifest["sources"][0]["assets"] = []  # type: ignore[index]
        _write_manifest(root, manifest)
    else:
        cases[1]["metadata"]["source"] = "SciFact"  # type: ignore[index]
        _rewrite_cases(root / "development.jsonl", cases)

    with pytest.raises(DatasetValidationError, match=message):
        load_evaluation_dataset(root, split="development")


def test_default_audit_returns_canonical_splits_and_selected_fingerprints() -> None:
    audit = audit_evaluation_dataset(FIXTURE_ROOT)
    development = load_evaluation_dataset(FIXTURE_ROOT, split="development")
    validation = load_evaluation_dataset(FIXTURE_ROOT, split="validation")

    assert audit.audited_splits == ("development", "validation")
    assert tuple(item.fingerprint_sha256 for item in audit.splits) == (
        development.fingerprint_sha256,
        validation.fingerprint_sha256,
    )
    payload = {
        "manifest": audit.manifest.model_dump(mode="json"),
        "audited_splits": ["development", "validation"],
        "split_fingerprints": [
            development.fingerprint_sha256,
            validation.fingerprint_sha256,
        ],
    }
    expected = hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    assert audit.fingerprint_sha256 == expected


def test_default_audit_ignores_unauthorized_test_path_and_content(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    shutil.copytree(FIXTURE_ROOT, root)
    manifest, _ = _read_fixture_payload(root, "development")
    manifest["splits"]["test"]["path"] = str((tmp_path / "outside.jsonl").resolve())  # type: ignore[index]
    _write_manifest(root, manifest)
    (root / "test.jsonl").write_text("{malformed", encoding="utf-8")

    audit = audit_evaluation_dataset(root)

    assert audit.audited_splits == ("development", "validation")


def test_audit_rejects_duplicate_ids_across_audited_splits(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    shutil.copytree(FIXTURE_ROOT, root)
    _, development = _read_fixture_payload(root, "development")
    _, validation = _read_fixture_payload(root, "validation")
    validation[0]["case_id"] = development[0]["case_id"]
    _rewrite_cases(root / "validation.jsonl", validation)

    with pytest.raises(DatasetValidationError, match="duplicate case IDs"):
        audit_evaluation_dataset(root)


def test_audit_rejects_resolved_path_aliases_before_parsing(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    shutil.copytree(FIXTURE_ROOT, root)
    (root / "nested").mkdir()
    manifest, _ = _read_fixture_payload(root, "development")
    manifest["splits"]["validation"]["path"] = "nested/../development.jsonl"  # type: ignore[index]
    _write_manifest(root, manifest)

    with pytest.raises(DatasetValidationError, match="resolve uniquely"):
        audit_evaluation_dataset(root)


@pytest.mark.parametrize("authorization", [False, 1, "true", object()])
def test_audit_only_includes_test_for_literal_true(authorization: object) -> None:
    audit = audit_evaluation_dataset(
        FIXTURE_ROOT,
        include_test_labels=authorization,  # type: ignore[arg-type]
    )

    assert audit.audited_splits == ("development", "validation")


def test_authorized_test_audit_includes_all_splits_and_changes_fingerprint() -> None:
    default = audit_evaluation_dataset(FIXTURE_ROOT)
    authorized = audit_evaluation_dataset(FIXTURE_ROOT, include_test_labels=True)

    assert authorized.audited_splits == ("development", "validation", "test")
    assert authorized.fingerprint_sha256 != default.fingerprint_sha256
    assert authorized.splits[2].fingerprint_sha256 == load_evaluation_dataset(
        FIXTURE_ROOT, split="test", allow_test_labels=True
    ).fingerprint_sha256


def test_audit_fingerprint_changes_with_audited_gold_content(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    shutil.copytree(FIXTURE_ROOT, root)
    _, cases = _read_fixture_payload(root, "validation")
    cases[1]["reference"]["answer"] = "Changed audited answer."  # type: ignore[index]
    _rewrite_cases(root / "validation.jsonl", cases)

    assert (
        audit_evaluation_dataset(root).fingerprint_sha256
        != audit_evaluation_dataset(FIXTURE_ROOT).fingerprint_sha256
    )
