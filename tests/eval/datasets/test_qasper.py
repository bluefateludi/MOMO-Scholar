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
from paper_agent.eval.datasets.qasper import (
    QasperPaperRecord,
    convert_qasper,
    materialize_qasper_content,
)


FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "evaluation"
    / "upstream-format"
    / "qasper"
    / "qasper.json"
)


def _fixture_payload() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _encoded(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        + b"\n"
    )


def _convert() -> tuple[EvalCase, ...]:
    return convert_qasper(
        split="development",
        dataset_bytes=FIXTURE_PATH.read_bytes(),
        dataset_source_url="https://example.test/qasper/qasper.json",
    )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda paper, question, annotation: paper.update({"unknown": 1}),
            "qasper.json",
        ),
        (
            lambda paper, question, annotation: question.update({"unknown": 1}),
            "qasper.json",
        ),
        (
            lambda paper, question, annotation: annotation["answer"].update(
                {"unknown": 1}
            ),
            "qasper.json",
        ),
        (
            lambda paper, question, annotation: paper["qas"].append(
                dict(question)
            ),
            "qasper.json",
        ),
        (
            lambda paper, question, annotation: question["answers"].append(
                dict(annotation)
            ),
            "qasper.json",
        ),
        (
            lambda paper, question, annotation: question.update(
                {"question": " "}
            ),
            "qasper.json",
        ),
        (
            lambda paper, question, annotation: annotation["answer"].update(
                {
                    "free_form_answer": "both",
                    "extractive_spans": ["positive"],
                }
            ),
            "qasper.json",
        ),
        (
            lambda paper, question, annotation: paper.update(
                {"full_text": []}
            ),
            "qasper.json",
        ),
    ],
)
def test_qasper_rejects_invalid_shape_answers_and_references(
    mutate: object,
    message: str,
) -> None:
    payload = _fixture_payload()
    paper = payload["synthetic-paper-1"]
    question = paper["qas"][0]
    annotation = question["answers"][0]
    mutate(paper, question, annotation)

    with pytest.raises(ConversionValidationError, match=message):
        convert_qasper(
            split="development",
            dataset_bytes=_encoded(payload),
            dataset_source_url="https://example.test/qasper/qasper.json",
        )


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b'{"synthetic-paper-1":', "invalid JSON"),
        (b"\xffSECRET_QASPER", "UTF-8"),
    ],
)
def test_qasper_rejects_malformed_bytes_without_leaking_content(
    payload: bytes,
    message: str,
) -> None:
    with pytest.raises(ConversionValidationError, match=message) as caught:
        convert_qasper(
            split="development",
            dataset_bytes=payload,
            dataset_source_url="https://example.test/qasper/qasper.json",
        )

    assert "SECRET_QASPER" not in str(caught.value)


def test_qasper_materialization_preserves_paragraph_bytes() -> None:
    record = QasperPaperRecord.model_validate(
        {
            "title": "Synthetic",
            "abstract": "Abstract",
            "full_text": [
                {
                    "section_name": "One",
                    "paragraphs": [" first ", "second"],
                }
            ],
            "qas": [],
        }
    )

    assert materialize_qasper_content(record) == b" first \nsecond\n"


def test_qasper_accepts_v03_metadata_fields() -> None:
    payload = _fixture_payload()
    paper = payload["synthetic-paper-1"]
    question = paper["qas"][0]
    question.update(
        {
            "nlp_background": "",
            "topic_background": "",
            "paper_read": "",
            "question_writer": "writer-1",
        }
    )
    paper["figures_and_tables"] = [
        {"file": "figure-1.png", "caption": "Synthetic figure."}
    ]
    paper["full_text"].append(
        {"section_name": None, "paragraphs": [""]}
    )
    question["answers"][0]["answer"]["highlighted_evidence"] = [
        "The synthetic outcome was positive.",
        "The synthetic outcome was positive.",
    ]

    cases = convert_qasper(
        split="development",
        dataset_bytes=_encoded(payload),
        dataset_source_url="https://example.test/qasper/qasper.json",
    )

    assert len(cases) == 4


@pytest.mark.parametrize(
    "mutate",
    [
        lambda paper, answer: answer.update({"evidence": []}),
        lambda paper, answer: answer.update(
            {"evidence": ["missing paragraph"]}
        ),
        lambda paper, answer: paper["full_text"][0]["paragraphs"].append(
            answer["evidence"][0]
        ),
    ],
)
def test_qasper_skips_annotation_without_resolvable_evidence(
    mutate: object,
) -> None:
    payload = _fixture_payload()
    paper = payload["synthetic-paper-1"]
    annotations = paper["qas"][0]["answers"]
    skipped_id = annotations[0]["annotation_id"]
    mutate(paper, annotations[0]["answer"])

    cases = convert_qasper(
        split="development",
        dataset_bytes=_encoded(payload),
        dataset_source_url="https://example.test/qasper/qasper.json",
    )

    assert len(cases) < 4
    assert not any(
        item.case_id.endswith(f"annotation-{skipped_id}") for item in cases
    )


def test_qasper_maps_each_annotation_to_one_strict_case() -> None:
    cases = _convert()

    assert tuple(case.case_id for case in cases) == (
        (
            "qasper-development-paper-synthetic-paper-1-question-question-1"
            "-annotation-annotation-extractive"
        ),
        (
            "qasper-development-paper-synthetic-paper-1-question-question-1"
            "-annotation-annotation-free"
        ),
        (
            "qasper-development-paper-synthetic-paper-1-question-question-1"
            "-annotation-annotation-unanswerable"
        ),
        (
            "qasper-development-paper-synthetic-paper-1-question-question-1"
            "-annotation-annotation-yes-no"
        ),
    )
    assert all(EvalCase.model_validate(case.model_dump()) == case for case in cases)
    answers = {
        case.case_id.rsplit("-annotation-", maxsplit=1)[1]: (
            case.reference.answer,
            case.reference.unanswerable,
        )
        for case in cases
    }
    assert answers == {
        "extractive": ("positive\nstable", False),
        "free": ("It reports a positive synthetic outcome.", False),
        "unanswerable": (None, True),
        "yes-no": ("yes", False),
    }


def test_qasper_maps_content_hash_and_stable_evidence_locator() -> None:
    cases = _convert()
    free_form = next(
        case for case in cases if case.case_id.endswith("annotation-free")
    )
    materialized = (
        b"The synthetic system is introduced.\n"
        b"No real dataset or experiment is described.\n"
        b"The synthetic outcome was positive.\n"
        b"A second synthetic observation was stable.\n"
        b"The fixture cannot support conclusions about real systems.\n"
    )
    expected_hash = hashlib.sha256(materialized).hexdigest()

    assert free_form.corpus.papers[0].content_sha256 == expected_hash
    assert free_form.reference.evidence is not None
    assert free_form.reference.evidence[0].model_dump(mode="json") == {
        "evidence_id": (
            "qasper-paper-synthetic-paper-1-question-question-1"
            "-annotation-annotation-free-evidence-0"
        ),
        "paper_id": "qasper-paper-synthetic-paper-1",
        "content_sha256": expected_hash,
        "source_type": "annotation",
        "upstream_locator": (
            "paper/synthetic-paper-1/section/1/paragraph/0"
        ),
        "page": None,
        "section": "Results",
        "quote": "The synthetic outcome was positive.",
        "relevance_grade": 3,
        "required": True,
    }


def test_qasper_conversion_is_byte_stable() -> None:
    assert canonical_jsonl_bytes(_convert()) == canonical_jsonl_bytes(_convert())
