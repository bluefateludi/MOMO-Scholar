from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from paper_agent.eval.contracts import EvalCase
from paper_agent.eval.datasets.conversion import (
    ConversionValidationError,
    canonical_jsonl_bytes,
)
from paper_agent.eval.datasets.scifact import (
    convert_scifact,
    materialize_scifact_content,
)


FIXTURE_ROOT = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "evaluation"
    / "upstream-format"
    / "scifact"
)


def _fixture_bytes() -> tuple[bytes, bytes]:
    return (
        (FIXTURE_ROOT / "claims.jsonl").read_bytes(),
        (FIXTURE_ROOT / "corpus.jsonl").read_bytes(),
    )


def _convert() -> tuple[EvalCase, ...]:
    claims, corpus = _fixture_bytes()
    return convert_scifact(
        split="development",
        claims_bytes=claims,
        corpus_bytes=corpus,
    )


def _rewrite_jsonl(payload: bytes, mutate: object) -> bytes:
    rows = [
        json.loads(line)
        for line in payload.decode("utf-8").splitlines()
        if line.strip()
    ]
    mutate(rows)
    return b"".join(
        json.dumps(row, separators=(",", ":")).encode("utf-8") + b"\n"
        for row in rows
    )


@pytest.mark.parametrize(
    ("asset", "mutate", "message"),
    [
        (
            "claims",
            lambda rows: rows[0].update({"unknown": True}),
            "claims.jsonl",
        ),
        (
            "claims",
            lambda rows: rows[0]["evidence"]["101"][0].update(
                {"unknown": True}
            ),
            "claims.jsonl",
        ),
        (
            "corpus",
            lambda rows: rows[0].update({"unknown": True}),
            "corpus.jsonl",
        ),
        (
            "claims",
            lambda rows: rows[1].update({"id": rows[0]["id"]}),
            "claim IDs",
        ),
        (
            "corpus",
            lambda rows: rows[1].update({"doc_id": rows[0]["doc_id"]}),
            "document IDs",
        ),
        (
            "claims",
            lambda rows: rows[0].update({"cited_doc_ids": [999]}),
            "cited document",
        ),
        (
            "claims",
            lambda rows: rows[0]["evidence"].update(
                {"102": rows[0]["evidence"].pop("101")}
            ),
            "cited_doc_ids",
        ),
        (
            "claims",
            lambda rows: rows[0]["evidence"]["101"][0].update(
                {"label": "REFUTE"}
            ),
            "claims.jsonl",
        ),
        (
            "claims",
            lambda rows: rows[0]["evidence"]["101"][0].update(
                {"sentences": []}
            ),
            "claims.jsonl",
        ),
        (
            "claims",
            lambda rows: rows[0]["evidence"]["101"][0].update(
                {"sentences": [-1]}
            ),
            "claims.jsonl",
        ),
        (
            "claims",
            lambda rows: rows[0]["evidence"]["101"][0].update(
                {"sentences": [1, 1]}
            ),
            "claims.jsonl",
        ),
        (
            "claims",
            lambda rows: rows[0]["evidence"]["101"][0].update(
                {"sentences": [99]}
            ),
            "sentence",
        ),
    ],
)
def test_scifact_rejects_invalid_shape_and_references(
    asset: str,
    mutate: object,
    message: str,
) -> None:
    claims, corpus = _fixture_bytes()
    if asset == "claims":
        claims = _rewrite_jsonl(claims, mutate)
    else:
        corpus = _rewrite_jsonl(corpus, mutate)

    with pytest.raises(ConversionValidationError, match=message):
        convert_scifact(
            split="development",
            claims_bytes=claims,
            corpus_bytes=corpus,
        )


@pytest.mark.parametrize(
    ("asset", "payload", "message"),
    [
        ("claims", b"\n\n{malformed\n", "claims.jsonl.*line 3"),
        ("corpus", b"\xffSECRET_CORPUS", "corpus.jsonl.*UTF-8"),
    ],
)
def test_scifact_rejects_malformed_bytes_without_leaking_content(
    asset: str,
    payload: bytes,
    message: str,
) -> None:
    claims, corpus = _fixture_bytes()
    if asset == "claims":
        claims = payload
    else:
        corpus = payload

    with pytest.raises(ConversionValidationError, match=message) as caught:
        convert_scifact(
            split="development",
            claims_bytes=claims,
            corpus_bytes=corpus,
        )

    assert "SECRET_CORPUS" not in str(caught.value)


def test_scifact_materialization_preserves_sentence_bytes() -> None:
    from paper_agent.eval.datasets.scifact import SciFactCorpusRecord

    record = SciFactCorpusRecord.model_validate(
        {
            "doc_id": 1,
            "title": "Synthetic",
            "abstract": [" first ", "second"],
            "structured": False,
        }
    )

    assert materialize_scifact_content(record) == b" first \nsecond\n"


def test_scifact_maps_each_evidence_set_to_a_strict_case() -> None:
    cases = _convert()

    assert tuple(case.case_id for case in cases) == (
        "scifact-development-claim-201-document-101-evidence-0",
        "scifact-development-claim-202-document-102-evidence-0",
        "scifact-development-claim-203-document-101-evidence-0",
        "scifact-development-claim-203-document-101-evidence-1",
    )
    assert all(EvalCase.model_validate(case.model_dump()) == case for case in cases)

    first = cases[0].model_dump(mode="json")
    expected_hash = hashlib.sha256(
        b"Synthetic observations were recorded.\n"
        b"The intervention improved the synthetic outcome.\n"
    ).hexdigest()
    assert first == {
        "schema_version": "1.0",
        "case_id": "scifact-development-claim-201-document-101-evidence-0",
        "task_type": "claim_verification",
        "question": "The intervention improved the synthetic outcome.",
        "corpus": {
            "papers": [
                {
                    "paper_id": "scifact-document-101",
                    "title": "Synthetic intervention study",
                    "authors": [],
                    "year": None,
                    "abstract": (
                        "Synthetic observations were recorded.\n"
                        "The intervention improved the synthetic outcome."
                    ),
                    "url": "https://example.test/scifact/document/101",
                    "pdf_url": None,
                    "source": "SciFact",
                    "content_sha256": expected_hash,
                }
            ]
        },
        "reference": {
            "relevant_paper_ids": ["scifact-document-101"],
            "evidence": [
                {
                    "evidence_id": (
                        "scifact-claim-201-document-101-evidence-0-sentence-1"
                    ),
                    "paper_id": "scifact-document-101",
                    "content_sha256": expected_hash,
                    "source_type": "rationale",
                    "upstream_locator": (
                        "claim/201/evidence/101/set/0/sentence/1"
                    ),
                    "page": None,
                    "section": "Abstract",
                    "quote": "The intervention improved the synthetic outcome.",
                    "relevance_grade": 3,
                    "required": True,
                }
            ],
            "claims": [
                {
                    "claim_id": (
                        "scifact-claim-201-document-101-evidence-0-claim"
                    ),
                    "text": "The intervention improved the synthetic outcome.",
                    "importance": "critical",
                    "stance": "supported",
                    "required": True,
                    "supporting_evidence_ids": [
                        "scifact-claim-201-document-101-evidence-0-sentence-1"
                    ],
                }
            ],
            "answer": None,
            "unanswerable": False,
        },
        "rubric": [],
        "metadata": {
            "source": "SciFact",
            "split": "development",
            "domain": "biomedicine",
            "difficulty": "upstream",
        },
    }
    assert cases[1].reference.claims is not None
    assert cases[1].reference.claims[0].stance == "refuted"


def test_scifact_conversion_is_byte_stable() -> None:
    first = canonical_jsonl_bytes(_convert())
    second = canonical_jsonl_bytes(_convert())

    assert first == second
