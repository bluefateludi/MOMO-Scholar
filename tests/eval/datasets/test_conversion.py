from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from paper_agent.eval.contracts import EvalCase
from paper_agent.eval.datasets.conversion import (
    ConversionAssetInput,
    ConversionAssetReceipt,
    ConversionReceipt,
    ConversionRequest,
    ConversionValidationError,
    canonical_json_bytes,
    canonical_jsonl_bytes,
    convert_dataset,
    write_conversion,
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


SCIFACT_FIXTURE_ROOT = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "evaluation"
    / "upstream-format"
    / "scifact"
)
QASPER_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "evaluation"
    / "upstream-format"
    / "qasper"
    / "qasper.json"
)


def _scifact_request(**changes: object) -> ConversionRequest:
    assets = tuple(
        ConversionAssetInput.model_validate(
            {
                "asset_type": asset_type,
                "path": path,
                "expected_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "source_url": f"https://example.test/scifact/{path.name}",
                "license_id": "CC0-1.0",
                "redistribution": "allowed",
                "reviewer": "fixture-author",
                "review_date": date(2026, 7, 26),
            }
        )
        for asset_type, path in (
            ("claims-evidence", SCIFACT_FIXTURE_ROOT / "claims.jsonl"),
            ("abstracts", SCIFACT_FIXTURE_ROOT / "corpus.jsonl"),
        )
    )
    data: dict[str, object] = {
        "dataset": "scifact",
        "split": "development",
        "upstream_version": "synthetic-v1",
        "adapter_version": "scifact-v1",
        "converted_at": datetime(2026, 7, 26, 1, 2, 3, tzinfo=timezone.utc),
        "assets": assets,
    }
    data.update(changes)
    return ConversionRequest.model_validate(data)


def test_convert_dataset_hashes_exact_assets_and_emitted_case_bytes() -> None:
    result = convert_dataset(_scifact_request())

    assert len(result.cases) == 4
    assert result.cases_jsonl == canonical_jsonl_bytes(result.cases)
    assert result.receipt.case_ids == tuple(
        sorted(case.case_id for case in result.cases)
    )
    assert result.receipt.cases_sha256 == hashlib.sha256(
        result.cases_jsonl
    ).hexdigest()
    assert result.receipt.may_commit_transformed is True
    assert result.receipt_json == canonical_json_bytes(result.receipt)
    assert tuple(asset.asset_type for asset in result.receipt.assets) == (
        "abstracts",
        "claims-evidence",
    )
    assert tuple(asset.upstream_sha256 for asset in result.receipt.assets) == (
        hashlib.sha256(
            (SCIFACT_FIXTURE_ROOT / "corpus.jsonl").read_bytes()
        ).hexdigest(),
        hashlib.sha256(
            (SCIFACT_FIXTURE_ROOT / "claims.jsonl").read_bytes()
        ).hexdigest(),
    )


def test_convert_dataset_is_byte_stable_for_identical_request() -> None:
    first = convert_dataset(_scifact_request())
    second = convert_dataset(_scifact_request())

    assert first.cases_jsonl == second.cases_jsonl
    assert first.receipt_json == second.receipt_json


def test_convert_dataset_rejects_hash_before_parsing(tmp_path: Path) -> None:
    invalid = tmp_path / "claims.jsonl"
    invalid.write_bytes(b"SECRET_INVALID_SOURCE")
    original = _scifact_request()
    assets = tuple(
        asset.model_copy(
            update={
                "path": invalid,
                "expected_sha256": "0" * 64,
            }
        )
        if asset.asset_type == "claims-evidence"
        else asset
        for asset in original.assets
    )

    with pytest.raises(ConversionValidationError, match="hash mismatch") as caught:
        convert_dataset(original.model_copy(update={"assets": assets}))

    assert "SECRET_INVALID_SOURCE" not in str(caught.value)


@pytest.mark.parametrize("violation", ["missing", "extra"])
def test_convert_dataset_rejects_inexact_asset_set(violation: str) -> None:
    request = _scifact_request()
    if violation == "missing":
        assets = request.assets[:1]
    else:
        assets = request.assets + (
            request.assets[0].model_copy(update={"asset_type": "unexpected"}),
        )

    with pytest.raises(ConversionValidationError, match="asset types"):
        convert_dataset(request.model_copy(update={"assets": assets}))


def test_receipt_disallows_commit_when_any_asset_is_metadata_only() -> None:
    request = _scifact_request()
    assets = (
        request.assets[0].model_copy(
            update={"redistribution": "metadata-only"}
        ),
        request.assets[1],
    )

    result = convert_dataset(request.model_copy(update={"assets": assets}))

    assert result.receipt.may_commit_transformed is False


def test_convert_dataset_routes_qasper_and_hashes_its_asset() -> None:
    payload = QASPER_FIXTURE_PATH.read_bytes()
    request = ConversionRequest.model_validate(
        {
            "dataset": "qasper",
            "split": "validation",
            "upstream_version": "synthetic-v1",
            "adapter_version": "qasper-v1",
            "converted_at": datetime(
                2026, 7, 26, 1, 2, 3, tzinfo=timezone.utc
            ),
            "assets": [
                {
                    "asset_type": "questions-answers-and-corpus",
                    "path": QASPER_FIXTURE_PATH,
                    "expected_sha256": hashlib.sha256(payload).hexdigest(),
                    "source_url": "https://example.test/qasper/qasper.json",
                    "license_id": "CC0-1.0",
                    "redistribution": "allowed",
                    "reviewer": "fixture-author",
                    "review_date": date(2026, 7, 26),
                }
            ],
        }
    )

    result = convert_dataset(request)

    assert len(result.cases) == 4
    assert all(case.metadata.split == "validation" for case in result.cases)
    assert result.receipt.dataset == "qasper"
    assert result.receipt.assets[0].upstream_sha256 == hashlib.sha256(
        payload
    ).hexdigest()
    assert result.receipt.cases_sha256 == hashlib.sha256(
        result.cases_jsonl
    ).hexdigest()


def test_write_conversion_publishes_cases_then_receipt(tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    output_root.mkdir()
    result = convert_dataset(_scifact_request())

    write_conversion(
        result,
        output_root=output_root,
        cases_path=Path("cases.jsonl"),
        receipt_path=Path("receipt.json"),
    )

    assert (output_root / "cases.jsonl").read_bytes() == result.cases_jsonl
    assert (output_root / "receipt.json").read_bytes() == result.receipt_json
    assert list(output_root.glob(".*.tmp")) == []


@pytest.mark.parametrize(
    "violation",
    ["same", "existing", "outside", "missing-parent"],
)
def test_write_conversion_rejects_unsafe_destinations(
    tmp_path: Path,
    violation: str,
) -> None:
    output_root = tmp_path / "output"
    output_root.mkdir()
    cases_path = Path("cases.jsonl")
    receipt_path = Path("receipt.json")
    if violation == "same":
        receipt_path = cases_path
    elif violation == "existing":
        (output_root / cases_path).write_bytes(b"existing")
    elif violation == "outside":
        cases_path = Path("../outside.jsonl")
    else:
        cases_path = Path("missing/cases.jsonl")

    with pytest.raises(ConversionValidationError):
        write_conversion(
            convert_dataset(_scifact_request()),
            output_root=output_root,
            cases_path=cases_path,
            receipt_path=receipt_path,
        )

    if violation == "existing":
        assert (output_root / "cases.jsonl").read_bytes() == b"existing"


def test_write_conversion_publishes_receipt_last_on_replace_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_root = tmp_path / "output"
    output_root.mkdir()
    real_replace = os.replace
    replace_count = 0

    def fail_second_replace(source: object, destination: object) -> None:
        nonlocal replace_count
        replace_count += 1
        if replace_count == 2:
            raise OSError("SECRET_REPLACE_FAILURE")
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_second_replace)

    with pytest.raises(ConversionValidationError, match="receipt.json") as caught:
        write_conversion(
            convert_dataset(_scifact_request()),
            output_root=output_root,
            cases_path=Path("cases.jsonl"),
            receipt_path=Path("receipt.json"),
        )

    assert "SECRET_REPLACE_FAILURE" not in str(caught.value)
    assert (output_root / "cases.jsonl").is_file()
    assert not (output_root / "receipt.json").exists()
    assert list(output_root.glob(".*.tmp")) == []
