from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Iterable, Mapping


_SCHEMA_VERSION = "1.0"
_PACKAGE_KIND = "citation_generation_authority"
_AUTHORITY_FILE = "generation-authority.json"
_PACKAGE_MANIFEST = "package-manifest.json"
_SECRET_PATTERN = re.compile(
    r'(?i)(?:"(?:api[_-]?key|authorization)"\s*:|bearer\s+[a-z0-9._-]+|sk-[a-z0-9])'
)
_BASE_SOURCE_FILES = (
    "case-results.jsonl",
    "corpus-manifest.json",
    "dataset-manifest.json",
    "environment.json",
    "evidence.jsonl",
    "failures.jsonl",
    "generation-config.json",
    "generation-drafts.jsonl",
    "generation-manifest.json",
    "gold-judgments.jsonl",
    "logs.jsonl",
    "model-authority.json",
    "pipeline-outputs.jsonl",
    "prepared-cases.jsonl",
    "provider-sends.jsonl",
    "resolved-config.json",
    "run-state.json",
    "traces.jsonl",
)


class GenerationAuthorityError(ValueError):
    pass


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _canonical_jsonl(values: Iterable[object]) -> bytes:
    return b"".join(_canonical_json(value) for value in values)


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _load_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise GenerationAuthorityError(f"invalid JSON authority: {path.name}") from error
    if not isinstance(value, dict):
        raise GenerationAuthorityError(f"JSON authority must be an object: {path.name}")
    return value


def _load_jsonl(path: Path) -> list[dict[str, object]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise GenerationAuthorityError(f"invalid JSONL authority: {path.name}") from error
    rows: list[dict[str, object]] = []
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise GenerationAuthorityError(
                f"invalid JSONL authority: {path.name}"
            ) from error
        if not isinstance(value, dict):
            raise GenerationAuthorityError(
                f"JSONL authority rows must be objects: {path.name}"
            )
        rows.append(value)
    return rows


def _artifact(path: Path, *, relative_path: str) -> dict[str, object]:
    if not path.is_file() or path.is_symlink():
        raise GenerationAuthorityError(f"missing or unsafe authority: {relative_path}")
    content = path.read_bytes()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise GenerationAuthorityError(f"non-UTF-8 authority: {relative_path}") from error
    if _SECRET_PATTERN.search(text):
        raise GenerationAuthorityError(f"secret-like material: {relative_path}")
    return {
        "absolute_path": str(path),
        "byte_length": len(content),
        "relative_path": relative_path,
        "sha256": _sha256_bytes(content),
    }


def _source_file_names(model_authority: Mapping[str, object]) -> tuple[str, ...]:
    snapshot_names: list[str] = []
    for field in (
        "deployment_authority_file",
        "model_document_file",
        "pricing_document_file",
    ):
        value = model_authority.get(field)
        if (
            not isinstance(value, str)
            or not value
            or Path(value).name != value
            or value in {".", ".."}
            or "/" in value
            or "\\" in value
        ):
            raise GenerationAuthorityError("model authority snapshot path is invalid")
        snapshot_names.append(value)
    return tuple(sorted(set(_BASE_SOURCE_FILES) | set(snapshot_names)))


def _ordered_case_rows(
    source: Path, name: str, selected_case_ids: list[str]
) -> list[dict[str, object]]:
    rows = _load_jsonl(source / name)
    ids = [row.get("case_id") for row in rows]
    if ids != selected_case_ids:
        raise GenerationAuthorityError(f"case IDs or order differ: {name}")
    return rows


def _accounted_cost(row: Mapping[str, object]) -> tuple[str, float]:
    currency = row.get("cost_currency")
    if currency is None and (
        "actual_cost_usd" in row or "authorized_cost_ceiling_usd" in row
    ):
        currency = "USD"
        actual = row.get("actual_cost_usd")
        ceiling = row.get("authorized_cost_ceiling_usd")
    else:
        actual = row.get("actual_cost")
        ceiling = row.get("authorized_cost_ceiling")
    if currency not in {"CNY", "USD"}:
        raise GenerationAuthorityError("ledger cost currency is missing or invalid")
    value = actual if actual is not None else ceiling
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GenerationAuthorityError("ledger cost accounting is incomplete")
    amount = float(value)
    if not math.isfinite(amount) or amount < 0:
        raise GenerationAuthorityError("ledger cost accounting is invalid")
    return str(currency), amount


def build_generation_authority(
    source: str | Path, campaign_ledger: str | Path
) -> dict[str, object]:
    source_root = Path(source).resolve(strict=True)
    ledger_path = Path(campaign_ledger).resolve(strict=True)
    if not source_root.is_dir() or source_root.is_symlink():
        raise GenerationAuthorityError("generation source is missing or unsafe")
    if not ledger_path.is_file() or ledger_path.is_symlink():
        raise GenerationAuthorityError("campaign ledger is missing or unsafe")

    manifest = _load_json(source_root / "generation-manifest.json")
    config = _load_json(source_root / "generation-config.json")
    environment = _load_json(source_root / "environment.json")
    run_state = _load_json(source_root / "run-state.json")
    model_authority = _load_json(source_root / "model-authority.json")
    source_artifacts = [
        _artifact(source_root / name, relative_path=name)
        for name in _source_file_names(model_authority)
    ]
    ledger_artifact = _artifact(ledger_path, relative_path="campaign-ledger.jsonl")
    if manifest.get("status") != "completed":
        raise GenerationAuthorityError("generation is not complete")
    selected = manifest.get("selected_case_ids")
    completed = manifest.get("completed_case_ids")
    if (
        not isinstance(selected, list)
        or not selected
        or any(not isinstance(case_id, str) or not case_id for case_id in selected)
        or len(selected) != len(set(selected))
        or completed != selected
        or manifest.get("failed_case_ids") != []
    ):
        raise GenerationAuthorityError("generation case authority is incomplete")

    case_results = _ordered_case_rows(source_root, "case-results.jsonl", selected)
    drafts = _ordered_case_rows(source_root, "generation-drafts.jsonl", selected)
    outputs = _ordered_case_rows(source_root, "pipeline-outputs.jsonl", selected)
    evidence = _ordered_case_rows(source_root, "evidence.jsonl", selected)
    prepared = _ordered_case_rows(source_root, "prepared-cases.jsonl", selected)
    if (source_root / "failures.jsonl").read_bytes() != b"":
        raise GenerationAuthorityError("generation failures are not empty")
    if any(row.get("status") != "completed" for row in case_results):
        raise GenerationAuthorityError("case-level persistence is incomplete")

    request_model = config.get("request_model")
    expected_model = config.get("expected_response_model")
    if (
        request_model != model_authority.get("request_model")
        or expected_model != model_authority.get("expected_response_model")
        or request_model != manifest.get("request_model")
        or manifest.get("resolved_response_models") != [expected_model]
        or any(row.get("response_model") != expected_model for row in case_results)
        or any(row.get("response_model") != expected_model for row in drafts)
    ):
        raise GenerationAuthorityError("generation model authority mismatch")

    for result, output, evidence_row in zip(case_results, outputs, evidence, strict=True):
        if result.get("output_sha256") != _sha256_bytes(
            _canonical_json(output.get("checked_output"))
        ):
            raise GenerationAuthorityError("case output hash mismatch")
        if result.get("evidence_sha256") != _sha256_bytes(
            _canonical_json(evidence_row.get("evidence"))
        ):
            raise GenerationAuthorityError("case evidence hash mismatch")

    aggregate_output_sha256 = _sha256_bytes(_canonical_jsonl(outputs))
    if aggregate_output_sha256 != manifest.get("output_sha256"):
        raise GenerationAuthorityError("aggregate output hash mismatch")

    sends = _load_jsonl(source_root / "provider-sends.jsonl")
    ledger_rows = _load_jsonl(ledger_path)
    execution_id = manifest.get("execution_id")
    execution_rows = [row for row in ledger_rows if row.get("execution_id") == execution_id]
    if sends != execution_rows or len(sends) != manifest.get("provider_send_count"):
        raise GenerationAuthorityError("execution send projection mismatch")
    if len(ledger_rows) != manifest.get("campaign_provider_send_count"):
        raise GenerationAuthorityError("campaign send count mismatch")
    if any(row.get("status") != "succeeded" for row in sends):
        raise GenerationAuthorityError("provider send ledger contains failures")
    if any(row.get("response_model") != expected_model for row in sends):
        raise GenerationAuthorityError("provider response model mismatch")
    attempts = sum(int(row.get("attempts", 0)) for row in case_results)
    retry_count = len(sends) - len(selected)
    if attempts != len(sends) or retry_count < 0:
        raise GenerationAuthorityError("generation attempt accounting mismatch")

    prompt_tokens = sum(int(row.get("prompt_tokens", 0)) for row in sends)
    completion_tokens = sum(int(row.get("completion_tokens", 0)) for row in sends)
    total_tokens = sum(int(row.get("total_tokens", 0)) for row in sends)
    costs: dict[str, float] = {}
    for row in ledger_rows:
        currency, amount = _accounted_cost(row)
        costs[currency] = costs.get(currency, 0.0) + amount
    declared_costs = {
        str(item["currency"]): float(item["amount"])
        for item in manifest.get("campaign_accounted_costs", [])
        if isinstance(item, dict)
        and item.get("currency") in {"CNY", "USD"}
        and isinstance(item.get("amount"), (int, float))
    }
    if costs.keys() != declared_costs.keys() or any(
        not math.isclose(amount, declared_costs[currency], abs_tol=1e-12)
        for currency, amount in costs.items()
    ):
        raise GenerationAuthorityError("campaign cost accounting mismatch")

    generation_config_sha256 = _sha256_bytes(
        (source_root / "generation-config.json").read_bytes()
    )
    if (
        generation_config_sha256 != manifest.get("generation_config_sha256")
        or generation_config_sha256 != run_state.get("generation_config_sha256")
        or environment.get("git_dirty") is not False
        or environment.get("git_sha") != run_state.get("git_sha")
    ):
        raise GenerationAuthorityError("generation config or Git authority mismatch")
    authority_hashes = run_state.get("authority_sha256")
    if not isinstance(authority_hashes, dict):
        raise GenerationAuthorityError("prepared authority hashes are missing")
    for name, expected_hash in authority_hashes.items():
        if not isinstance(name, str) or not isinstance(expected_hash, str):
            raise GenerationAuthorityError("prepared authority hashes are invalid")
        if _sha256_bytes((source_root / name).read_bytes()) != expected_hash:
            raise GenerationAuthorityError("prepared authority hash mismatch")

    return {
        "schema_version": _SCHEMA_VERSION,
        "package_kind": _PACKAGE_KIND,
        "source_root": str(source_root),
        "campaign_ledger_path": str(ledger_path),
        "source_artifacts": source_artifacts,
        "external_artifacts": [ledger_artifact],
        "generation": {
            "status": "completed",
            "case_count": len(selected),
            "ordered_case_ids": selected,
            "provider_send_count": len(sends),
            "retry_count": retry_count,
            "campaign_provider_send_count": len(ledger_rows),
            "request_model": request_model,
            "expected_response_model": expected_model,
            "response_models": [expected_model],
            "git_sha": environment.get("git_sha"),
            "git_dirty": False,
            "generation_config_sha256": generation_config_sha256,
            "aggregate_output_sha256": aggregate_output_sha256,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "campaign_accounted_costs": [
                {"currency": currency, "amount": amount}
                for currency, amount in sorted(costs.items())
            ],
        },
        "judge_inputs": [
            str(source_root / name)
            for name in (
                "dataset-manifest.json",
                "corpus-manifest.json",
                "gold-judgments.jsonl",
                "resolved-config.json",
                "environment.json",
                "generation-config.json",
                "generation-manifest.json",
                "model-authority.json",
                "prepared-cases.jsonl",
                "evidence.jsonl",
                "pipeline-outputs.jsonl",
                "case-results.jsonl",
                "provider-sends.jsonl",
                "failures.jsonl",
            )
        ],
        "resume_rules": {
            "provider_calls_forbidden": True,
            "source_is_read_only": True,
            "regeneration_forbidden": True,
            "judge_must_verify_package_before_use": True,
            "on_hash_mismatch": "stop_and_preserve_source",
        },
    }


def _package_manifest(authority_bytes: bytes) -> dict[str, object]:
    return {
        "schema_version": _SCHEMA_VERSION,
        "package_kind": _PACKAGE_KIND,
        "sealed": True,
        "artifacts": [
            {
                "path": _AUTHORITY_FILE,
                "byte_length": len(authority_bytes),
                "sha256": _sha256_bytes(authority_bytes),
            }
        ],
    }


def seal_generation_authority(
    source: str | Path, campaign_ledger: str | Path, output: str | Path
) -> dict[str, object]:
    source_root = Path(source).resolve(strict=True)
    output_root = Path(output).resolve()
    if output_root.exists():
        raise GenerationAuthorityError("generation authority output already exists")
    if output_root == source_root or source_root in output_root.parents:
        raise GenerationAuthorityError("generation authority output must be outside source")
    authority_bytes = _canonical_json(
        build_generation_authority(source_root, campaign_ledger)
    )
    manifest = _package_manifest(authority_bytes)
    output_root.mkdir(parents=True)
    (output_root / _AUTHORITY_FILE).write_bytes(authority_bytes)
    (output_root / _PACKAGE_MANIFEST).write_bytes(_canonical_json(manifest))
    return manifest


def verify_generation_authority(package: str | Path) -> dict[str, object]:
    root = Path(package).resolve(strict=True)
    if not root.is_dir() or root.is_symlink():
        raise GenerationAuthorityError("generation authority package is unsafe")
    if {path.name for path in root.iterdir()} != {_AUTHORITY_FILE, _PACKAGE_MANIFEST}:
        raise GenerationAuthorityError("generation authority package contents differ")
    stored_authority = (root / _AUTHORITY_FILE).read_bytes()
    authority = _load_json(root / _AUTHORITY_FILE)
    source = authority.get("source_root")
    ledger = authority.get("campaign_ledger_path")
    if not isinstance(source, str) or not Path(source).is_absolute():
        raise GenerationAuthorityError("source path authority is invalid")
    if not isinstance(ledger, str) or not Path(ledger).is_absolute():
        raise GenerationAuthorityError("ledger path authority is invalid")
    recomputed = _canonical_json(build_generation_authority(source, ledger))
    if recomputed != stored_authority:
        raise GenerationAuthorityError("generation authority recomputation differs")
    expected_manifest = _canonical_json(_package_manifest(stored_authority))
    if (root / _PACKAGE_MANIFEST).read_bytes() != expected_manifest:
        raise GenerationAuthorityError("generation package manifest differs")
    return {
        "authority_sha256": _sha256_bytes(stored_authority),
        "package_sha256": _sha256_bytes(expected_manifest),
        "case_count": authority["generation"]["case_count"],
    }


__all__ = [
    "GenerationAuthorityError",
    "build_generation_authority",
    "seal_generation_authority",
    "verify_generation_authority",
]
