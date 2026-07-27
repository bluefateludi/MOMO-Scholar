from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal, NamedTuple

from pydantic import (
    BaseModel,
    Field,
    StrictBool,
    StrictInt,
    field_serializer,
    field_validator,
    model_validator,
)

from paper_agent.eval.contracts import (
    EvalCase,
    FrozenEvalModel,
    SplitName,
)


DatasetName = Literal["scifact", "qasper"]
RedistributionDecision = Literal["allowed", "disallowed", "metadata-only"]
_SHA256_PATTERN = r"^[0-9a-f]{64}$"


class ConversionValidationError(ValueError):
    """Raised when upstream bytes cannot be converted safely."""


def _require_non_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


def _normalize_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("converted_at must include a timezone")
    return value.astimezone(timezone.utc).replace(microsecond=0)


class ConversionAssetInput(FrozenEvalModel):
    asset_type: str
    path: Path
    expected_sha256: str = Field(pattern=_SHA256_PATTERN)
    source_url: str
    license_id: str
    redistribution: RedistributionDecision
    reviewer: str
    review_date: date

    _non_blank_fields = field_validator(
        "asset_type", "source_url", "license_id", "reviewer"
    )(_require_non_blank)


class ConversionAssetReceipt(FrozenEvalModel):
    asset_type: str
    source_url: str
    license_id: str
    redistribution: RedistributionDecision
    reviewer: str
    review_date: date
    upstream_sha256: str = Field(pattern=_SHA256_PATTERN)
    byte_length: StrictInt = Field(ge=0)

    _non_blank_fields = field_validator(
        "asset_type", "source_url", "license_id", "reviewer"
    )(_require_non_blank)


class ConversionRequest(FrozenEvalModel):
    dataset: DatasetName
    split: SplitName
    upstream_version: str
    adapter_version: str
    converted_at: datetime
    assets: tuple[ConversionAssetInput, ...]

    _non_blank_fields = field_validator("upstream_version", "adapter_version")(
        _require_non_blank
    )
    _converted_at_is_utc = field_validator("converted_at")(_normalize_timestamp)

    @model_validator(mode="after")
    def _asset_types_are_unique(self) -> ConversionRequest:
        asset_types = [asset.asset_type for asset in self.assets]
        if len(asset_types) != len(set(asset_types)):
            raise ValueError("asset types must be unique")
        return self


class ConversionReceipt(FrozenEvalModel):
    schema_version: Literal["1.0"]
    dataset: DatasetName
    split: SplitName
    upstream_version: str
    adapter_version: str
    converted_at: datetime
    assets: tuple[ConversionAssetReceipt, ...]
    case_ids: tuple[str, ...]
    case_count: StrictInt = Field(ge=0)
    cases_sha256: str = Field(pattern=_SHA256_PATTERN)
    may_commit_transformed: StrictBool

    _non_blank_fields = field_validator("upstream_version", "adapter_version")(
        _require_non_blank
    )
    _converted_at_is_utc = field_validator("converted_at")(_normalize_timestamp)

    @field_validator("case_ids")
    @classmethod
    def _case_ids_are_valid(cls, case_ids: tuple[str, ...]) -> tuple[str, ...]:
        if any(not case_id.strip() for case_id in case_ids):
            raise ValueError("case IDs must not be blank")
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("case IDs must be unique")
        return case_ids

    @field_serializer("converted_at")
    def _serialize_converted_at(self, value: datetime) -> str:
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")

    @model_validator(mode="after")
    def _receipt_is_consistent(self) -> ConversionReceipt:
        asset_types = [asset.asset_type for asset in self.assets]
        if len(asset_types) != len(set(asset_types)):
            raise ValueError("asset types must be unique")
        if self.case_count != len(self.case_ids):
            raise ValueError("case count must match case IDs")
        return self


class ConversionResult(NamedTuple):
    cases: tuple[EvalCase, ...]
    cases_jsonl: bytes
    receipt: ConversionReceipt
    receipt_json: bytes


def _json_payload(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            _json_payload(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        + b"\n"
    )


def canonical_jsonl_bytes(cases: tuple[EvalCase, ...]) -> bytes:
    return b"".join(
        canonical_json_bytes(case)
        for case in sorted(cases, key=lambda item: item.case_id)
    )


def _read_and_verify_assets(
    request: ConversionRequest,
    *,
    expected_asset_types: frozenset[str],
) -> tuple[
    dict[str, bytes],
    tuple[ConversionAssetReceipt, ...],
]:
    assets_by_type = {asset.asset_type: asset for asset in request.assets}
    if set(assets_by_type) != expected_asset_types:
        raise ConversionValidationError(
            f"{request.dataset} asset types do not match the required set"
        )

    payloads: dict[str, bytes] = {}
    receipts: list[ConversionAssetReceipt] = []
    for asset_type in sorted(assets_by_type):
        asset = assets_by_type[asset_type]
        try:
            payload = asset.path.read_bytes()
        except FileNotFoundError as error:
            raise ConversionValidationError(
                f"{asset.path.name} is missing"
            ) from error
        except IsADirectoryError as error:
            raise ConversionValidationError(
                f"{asset.path.name} is not a file"
            ) from error
        except OSError as error:
            raise ConversionValidationError(
                f"{asset.path.name} has an I/O error"
            ) from error
        actual_hash = hashlib.sha256(payload).hexdigest()
        if actual_hash != asset.expected_sha256:
            raise ConversionValidationError(
                f"{asset.path.name} hash mismatch"
            )
        payloads[asset_type] = payload
        receipts.append(
            ConversionAssetReceipt(
                asset_type=asset.asset_type,
                source_url=asset.source_url,
                license_id=asset.license_id,
                redistribution=asset.redistribution,
                reviewer=asset.reviewer,
                review_date=asset.review_date,
                upstream_sha256=actual_hash,
                byte_length=len(payload),
            )
        )
    return payloads, tuple(receipts)


def _build_result(
    request: ConversionRequest,
    *,
    cases: tuple[EvalCase, ...],
    asset_receipts: tuple[ConversionAssetReceipt, ...],
) -> ConversionResult:
    ordered_cases = tuple(sorted(cases, key=lambda item: item.case_id))
    case_ids = tuple(case.case_id for case in ordered_cases)
    if len(case_ids) != len(set(case_ids)):
        raise ConversionValidationError("converted case IDs must be unique")
    cases_jsonl = canonical_jsonl_bytes(ordered_cases)
    receipt = ConversionReceipt(
        schema_version="1.0",
        dataset=request.dataset,
        split=request.split,
        upstream_version=request.upstream_version,
        adapter_version=request.adapter_version,
        converted_at=request.converted_at,
        assets=tuple(
            sorted(asset_receipts, key=lambda item: item.asset_type)
        ),
        case_ids=case_ids,
        case_count=len(case_ids),
        cases_sha256=hashlib.sha256(cases_jsonl).hexdigest(),
        may_commit_transformed=all(
            asset.redistribution == "allowed" for asset in asset_receipts
        ),
    )
    return ConversionResult(
        cases=ordered_cases,
        cases_jsonl=cases_jsonl,
        receipt=receipt,
        receipt_json=canonical_json_bytes(receipt),
    )


def convert_dataset(request: ConversionRequest) -> ConversionResult:
    if request.dataset == "scifact":
        from paper_agent.eval.datasets.scifact import convert_scifact

        payloads, receipts = _read_and_verify_assets(
            request,
            expected_asset_types=frozenset(
                {"claims-evidence", "abstracts"}
            ),
        )
        cases = convert_scifact(
            split=request.split,
            claims_bytes=payloads["claims-evidence"],
            corpus_bytes=payloads["abstracts"],
        )
    else:
        from paper_agent.eval.datasets.qasper import convert_qasper

        payloads, receipts = _read_and_verify_assets(
            request,
            expected_asset_types=frozenset(
                {"questions-answers-and-corpus"}
            ),
        )
        cases = convert_qasper(
            split=request.split,
            dataset_bytes=payloads["questions-answers-and-corpus"],
        )
    return _build_result(
        request,
        cases=cases,
        asset_receipts=receipts,
    )


def _resolve_output_destination(
    output_root: Path,
    destination: Path,
) -> Path:
    candidate = destination if destination.is_absolute() else output_root / destination
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(output_root)
    except (OSError, ValueError) as error:
        raise ConversionValidationError(
            f"{destination.name} resolves outside output root"
        ) from error
    if resolved == output_root:
        raise ConversionValidationError(
            f"{destination.name} must identify a file"
        )
    if not resolved.parent.is_dir():
        raise ConversionValidationError(
            f"{destination.name} parent directory is missing"
        )
    if resolved.exists():
        raise ConversionValidationError(
            f"{destination.name} already exists"
        )
    return resolved


def _write_temporary(destination: Path, payload: bytes) -> Path:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return temporary_path


def write_conversion(
    result: ConversionResult,
    *,
    output_root: Path,
    cases_path: Path,
    receipt_path: Path,
) -> None:
    try:
        resolved_root = output_root.resolve(strict=True)
    except OSError as error:
        raise ConversionValidationError("output root is missing") from error
    if not resolved_root.is_dir():
        raise ConversionValidationError("output root is not a directory")

    cases_destination = _resolve_output_destination(
        resolved_root, cases_path
    )
    receipt_destination = _resolve_output_destination(
        resolved_root, receipt_path
    )
    if cases_destination == receipt_destination:
        raise ConversionValidationError(
            "cases and receipt destinations must be distinct"
        )

    cases_temporary: Path | None = None
    receipt_temporary: Path | None = None
    publishing = cases_destination
    try:
        cases_temporary = _write_temporary(
            cases_destination, result.cases_jsonl
        )
        receipt_temporary = _write_temporary(
            receipt_destination, result.receipt_json
        )
        os.replace(cases_temporary, cases_destination)
        cases_temporary = None
        publishing = receipt_destination
        os.replace(receipt_temporary, receipt_destination)
        receipt_temporary = None
    except OSError as error:
        raise ConversionValidationError(
            f"{publishing.name} could not be published"
        ) from error
    finally:
        if cases_temporary is not None:
            cases_temporary.unlink(missing_ok=True)
        if receipt_temporary is not None:
            receipt_temporary.unlink(missing_ok=True)


__all__ = [
    "ConversionAssetInput",
    "ConversionAssetReceipt",
    "ConversionReceipt",
    "ConversionRequest",
    "ConversionResult",
    "ConversionValidationError",
    "DatasetName",
    "RedistributionDecision",
    "canonical_json_bytes",
    "canonical_jsonl_bytes",
    "convert_dataset",
    "write_conversion",
]
