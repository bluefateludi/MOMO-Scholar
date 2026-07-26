from __future__ import annotations

import json
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
]
