from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from paper_agent.eval.contracts import EvalCase
from paper_agent.eval.datasets.conversion import (
    ConversionAssetInput,
    ConversionAssetReceipt,
    ConversionReceipt,
    canonical_json_bytes,
    canonical_jsonl_bytes,
)


def _asset_input(tmp_path: Path, **changes: object) -> dict[str, object]:
    data: dict[str, object] = {
        "asset_type": "claims-evidence",
        "path": tmp_path / "claims.jsonl",
        "expected_sha256": "a" * 64,
        "source_url": "https://example.test/claims.jsonl",
        "license_id": "CC0-1.0",
        "redistribution": "allowed",
        "reviewer": "fixture-author",
        "review_date": date(2026, 7, 26),
    }
    data.update(changes)
    return data


def _asset_receipt(**changes: object) -> dict[str, object]:
    data: dict[str, object] = {
        "asset_type": "claims-evidence",
        "source_url": "https://example.test/claims.jsonl",
        "license_id": "CC0-1.0",
        "redistribution": "allowed",
        "reviewer": "fixture-author",
        "review_date": date(2026, 7, 26),
        "upstream_sha256": "a" * 64,
        "byte_length": 123,
    }
    data.update(changes)
    return data


def _receipt(**changes: object) -> dict[str, object]:
    data: dict[str, object] = {
        "schema_version": "1.0",
        "dataset": "scifact",
        "split": "development",
        "upstream_version": "synthetic-v1",
        "adapter_version": "scifact-v1",
        "converted_at": datetime(2026, 7, 26, 1, 2, 3, tzinfo=timezone.utc),
        "assets": (_asset_receipt(),),
        "case_ids": ("case-1",),
        "case_count": 1,
        "cases_sha256": "b" * 64,
        "may_commit_transformed": True,
    }
    data.update(changes)
    return data


def _case(case_id: str) -> EvalCase:
    content_hash = hashlib.sha256(b"synthetic\n").hexdigest()
    return EvalCase.model_validate(
        {
            "schema_version": "1.0",
            "case_id": case_id,
            "task_type": "single_paper_qa",
            "question": "What is reported?",
            "corpus": {
                "papers": [
                    {
                        "paper_id": "paper-1",
                        "title": "Synthetic paper",
                        "authors": [],
                        "year": None,
                        "abstract": "Synthetic abstract",
                        "url": "https://example.test/paper-1",
                        "pdf_url": None,
                        "source": "QASPER",
                        "content_sha256": content_hash,
                    }
                ]
            },
            "reference": {
                "relevant_paper_ids": None,
                "evidence": [
                    {
                        "evidence_id": f"{case_id}-evidence-1",
                        "paper_id": "paper-1",
                        "content_sha256": content_hash,
                        "source_type": "annotation",
                        "upstream_locator": "section-0/paragraph-0",
                        "page": None,
                        "section": "Results",
                        "quote": "Synthetic.",
                        "relevance_grade": 3,
                        "required": True,
                    }
                ],
                "claims": None,
                "answer": "Synthetic.",
                "unanswerable": False,
            },
            "rubric": [],
            "metadata": {
                "source": "QASPER",
                "split": "development",
                "domain": "computer-science",
                "difficulty": "upstream",
            },
        }
    )


@pytest.mark.parametrize(
    ("factory", "changes"),
    [
        (_asset_input, {"unexpected": "value"}),
        (_asset_input, {"asset_type": " "}),
        (_asset_input, {"expected_sha256": "A" * 64}),
        (_asset_input, {"expected_sha256": "a" * 63}),
        (_asset_input, {"reviewer": ""}),
        (_asset_receipt, {"unexpected": "value"}),
        (_asset_receipt, {"byte_length": True}),
        (_asset_receipt, {"upstream_sha256": "f" * 63}),
        (_receipt, {"unexpected": "value"}),
        (_receipt, {"case_count": True}),
        (_receipt, {"cases_sha256": "B" * 64}),
    ],
)
def test_conversion_models_reject_invalid_fields(
    tmp_path: Path,
    factory: object,
    changes: dict[str, object],
) -> None:
    if factory is _asset_input:
        payload = _asset_input(tmp_path, **changes)
        model = ConversionAssetInput
    elif factory is _asset_receipt:
        payload = _asset_receipt(**changes)
        model = ConversionAssetReceipt
    else:
        payload = _receipt(**changes)
        model = ConversionReceipt

    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_conversion_asset_input_rejects_naive_timestamp_in_request(
    tmp_path: Path,
) -> None:
    from paper_agent.eval.datasets.conversion import ConversionRequest

    with pytest.raises(ValidationError, match="timezone"):
        ConversionRequest.model_validate(
            {
                "dataset": "scifact",
                "split": "development",
                "upstream_version": "synthetic-v1",
                "adapter_version": "scifact-v1",
                "converted_at": datetime(2026, 7, 26, 1, 2, 3),
                "assets": (_asset_input(tmp_path),),
            }
        )


def test_receipt_rejects_duplicate_assets_case_ids_and_wrong_count() -> None:
    with pytest.raises(ValidationError, match="asset types"):
        ConversionReceipt.model_validate(
            _receipt(assets=(_asset_receipt(), _asset_receipt()))
        )
    with pytest.raises(ValidationError, match="case IDs"):
        ConversionReceipt.model_validate(
            _receipt(case_ids=("case-1", "case-1"), case_count=2)
        )
    with pytest.raises(ValidationError, match="case count"):
        ConversionReceipt.model_validate(_receipt(case_count=2))


def test_canonical_json_bytes_are_compact_sorted_utf8_and_lf_terminated() -> None:
    payload = {"z": "论文", "a": {"y": 2, "x": 1}}

    encoded = canonical_json_bytes(payload)

    assert encoded == '{"a":{"x":1,"y":2},"z":"论文"}\n'.encode()
    assert b"\r" not in encoded


def test_canonical_jsonl_sorts_cases_and_hashes_exact_bytes() -> None:
    cases = (_case("case-z"), _case("case-a"))

    encoded = canonical_jsonl_bytes(cases)

    lines = encoded.decode("utf-8").splitlines()
    assert [json.loads(line)["case_id"] for line in lines] == [
        "case-a",
        "case-z",
    ]
    assert encoded.endswith(b"\n")
    assert b"\r" not in encoded
    assert hashlib.sha256(encoded).hexdigest() == hashlib.sha256(
        b"".join(line.encode("utf-8") + b"\n" for line in lines)
    ).hexdigest()


def test_receipt_serialization_normalizes_utc_and_is_byte_stable() -> None:
    first = ConversionReceipt.model_validate(
        _receipt(
            converted_at=datetime.fromisoformat("2026-07-26T09:02:03+08:00")
        )
    )
    second = ConversionReceipt.model_validate(_receipt())

    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert b'"converted_at":"2026-07-26T01:02:03Z"' in canonical_json_bytes(
        first
    )
