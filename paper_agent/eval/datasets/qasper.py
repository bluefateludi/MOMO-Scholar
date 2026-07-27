from __future__ import annotations

import hashlib
import json
import re

from pydantic import (
    StrictBool,
    ValidationError,
    field_validator,
    model_validator,
)

from paper_agent.eval.contracts import EvalCase, FrozenEvalModel, SplitName
from paper_agent.eval.datasets.conversion import ConversionValidationError


_STABLE_ID = re.compile(r"^[A-Za-z0-9._-]+$")


def _require_non_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


def _require_stable_id(value: str) -> str:
    _require_non_blank(value)
    if _STABLE_ID.fullmatch(value) is None:
        raise ValueError("must contain only stable ID characters")
    return value


class QasperSection(FrozenEvalModel):
    section_name: str
    paragraphs: tuple[str, ...]

    _section_is_non_blank = field_validator("section_name")(
        _require_non_blank
    )

    @field_validator("paragraphs")
    @classmethod
    def _paragraphs_are_valid(
        cls, paragraphs: tuple[str, ...]
    ) -> tuple[str, ...]:
        if not paragraphs:
            raise ValueError("paragraphs must not be empty")
        if any(not paragraph.strip() for paragraph in paragraphs):
            raise ValueError("paragraphs must not contain blank text")
        return paragraphs


class QasperAnswer(FrozenEvalModel):
    unanswerable: StrictBool
    extractive_spans: tuple[str, ...]
    yes_no: StrictBool | None
    free_form_answer: str
    evidence: tuple[str, ...]

    @field_validator("extractive_spans", "evidence")
    @classmethod
    def _text_items_are_non_blank_and_unique(
        cls, items: tuple[str, ...]
    ) -> tuple[str, ...]:
        if any(not item.strip() for item in items):
            raise ValueError("answer text items must not be blank")
        if len(items) != len(set(items)):
            raise ValueError("answer text items must be unique")
        return items

    @model_validator(mode="after")
    def _answer_representation_is_unambiguous(self) -> QasperAnswer:
        free_form_present = bool(self.free_form_answer.strip())
        extractive_present = bool(self.extractive_spans)
        yes_no_present = self.yes_no is not None
        if not self.evidence:
            raise ValueError("annotation evidence must not be empty")
        if self.unanswerable:
            if free_form_present or extractive_present or yes_no_present:
                raise ValueError(
                    "unanswerable annotation has an answer representation"
                )
            return self
        if sum(
            (free_form_present, extractive_present, yes_no_present)
        ) != 1:
            raise ValueError(
                "answerable annotation requires one answer representation"
            )
        return self

    def projected_answer(self) -> str | None:
        if self.unanswerable:
            return None
        if self.free_form_answer.strip():
            return self.free_form_answer
        if self.extractive_spans:
            return "\n".join(self.extractive_spans)
        if self.yes_no is not None:
            return "yes" if self.yes_no else "no"
        raise AssertionError("validated answer has no representation")


class QasperAnnotation(FrozenEvalModel):
    answer: QasperAnswer
    annotation_id: str
    worker_id: str

    _annotation_id_is_stable = field_validator("annotation_id")(
        _require_stable_id
    )
    _worker_id_is_non_blank = field_validator("worker_id")(
        _require_non_blank
    )


class QasperQuestion(FrozenEvalModel):
    question: str
    question_id: str
    nlp_background: str
    topic_background: str
    paper_read: StrictBool
    search_query: str
    answers: tuple[QasperAnnotation, ...]

    _question_is_non_blank = field_validator("question")(_require_non_blank)
    _question_id_is_stable = field_validator("question_id")(
        _require_stable_id
    )

    @model_validator(mode="after")
    def _annotation_ids_are_unique(self) -> QasperQuestion:
        ids = [annotation.annotation_id for annotation in self.answers]
        if len(ids) != len(set(ids)):
            raise ValueError("annotation IDs must be unique")
        return self


class QasperPaperRecord(FrozenEvalModel):
    title: str
    abstract: str
    full_text: tuple[QasperSection, ...]
    qas: tuple[QasperQuestion, ...]

    _title_is_non_blank = field_validator("title")(_require_non_blank)

    @field_validator("full_text")
    @classmethod
    def _full_text_is_non_empty(
        cls, sections: tuple[QasperSection, ...]
    ) -> tuple[QasperSection, ...]:
        if not sections:
            raise ValueError("full_text must not be empty")
        return sections

    @model_validator(mode="after")
    def _question_ids_are_unique(self) -> QasperPaperRecord:
        ids = [question.question_id for question in self.qas]
        if len(ids) != len(set(ids)):
            raise ValueError("question IDs must be unique")
        return self


class _DuplicateJsonKey(ValueError):
    pass


def _reject_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey(key)
        result[key] = value
    return result


def _parse_dataset(payload: bytes) -> dict[str, QasperPaperRecord]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ConversionValidationError(
            "qasper.json is not valid UTF-8"
        ) from error
    try:
        raw = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except (json.JSONDecodeError, _DuplicateJsonKey) as error:
        raise ConversionValidationError(
            "qasper.json contains invalid JSON"
        ) from error
    if not isinstance(raw, dict):
        raise ConversionValidationError(
            "qasper.json has an invalid top-level object"
        )

    papers: dict[str, QasperPaperRecord] = {}
    for paper_id, record in raw.items():
        try:
            _require_stable_id(paper_id)
            papers[paper_id] = QasperPaperRecord.model_validate(record)
        except (ValueError, ValidationError) as error:
            raise ConversionValidationError(
                "qasper.json has an invalid paper record"
            ) from error
    return papers


def materialize_qasper_content(record: QasperPaperRecord) -> bytes:
    paragraphs = [
        paragraph
        for section in record.full_text
        for paragraph in section.paragraphs
    ]
    return ("\n".join(paragraphs) + "\n").encode("utf-8")


def _resolve_evidence(
    record: QasperPaperRecord,
    evidence_text: str,
) -> tuple[int, int, str]:
    matches = [
        (section_index, paragraph_index, section.section_name)
        for section_index, section in enumerate(record.full_text)
        for paragraph_index, paragraph in enumerate(section.paragraphs)
        if paragraph == evidence_text
    ]
    if len(matches) != 1:
        raise ConversionValidationError(
            "annotation evidence must match exactly one paragraph"
        )
    return matches[0]


def _map_annotation(
    *,
    split: SplitName,
    paper_id: str,
    paper: QasperPaperRecord,
    question: QasperQuestion,
    annotation: QasperAnnotation,
) -> EvalCase:
    canonical_paper_id = f"qasper-paper-{paper_id}"
    case_id = (
        f"qasper-{split}-paper-{paper_id}-question-{question.question_id}"
        f"-annotation-{annotation.annotation_id}"
    )
    content_hash = hashlib.sha256(
        materialize_qasper_content(paper)
    ).hexdigest()
    evidence = []
    for evidence_index, quote in enumerate(annotation.answer.evidence):
        section_index, paragraph_index, section_name = _resolve_evidence(
            paper, quote
        )
        evidence.append(
            {
                "evidence_id": (
                    f"qasper-paper-{paper_id}-question-{question.question_id}"
                    f"-annotation-{annotation.annotation_id}"
                    f"-evidence-{evidence_index}"
                ),
                "paper_id": canonical_paper_id,
                "content_sha256": content_hash,
                "source_type": "annotation",
                "upstream_locator": (
                    f"paper/{paper_id}/section/{section_index}"
                    f"/paragraph/{paragraph_index}"
                ),
                "page": None,
                "section": section_name,
                "quote": quote,
                "relevance_grade": 3,
                "required": True,
            }
        )
    return EvalCase.model_validate(
        {
            "schema_version": "1.0",
            "case_id": case_id,
            "task_type": "single_paper_qa",
            "question": question.question,
            "corpus": {
                "papers": [
                    {
                        "paper_id": canonical_paper_id,
                        "title": paper.title,
                        "authors": [],
                        "year": None,
                        "abstract": paper.abstract,
                        "url": (
                            "https://example.test/qasper/paper/"
                            f"{paper_id}"
                        ),
                        "pdf_url": None,
                        "source": "QASPER",
                        "content_sha256": content_hash,
                    }
                ]
            },
            "reference": {
                "relevant_paper_ids": None,
                "evidence": evidence,
                "claims": None,
                "answer": annotation.answer.projected_answer(),
                "unanswerable": annotation.answer.unanswerable,
            },
            "rubric": [],
            "metadata": {
                "source": "QASPER",
                "split": split,
                "domain": "computer-science",
                "difficulty": "upstream",
            },
        }
    )


def convert_qasper(
    *,
    split: SplitName,
    dataset_bytes: bytes,
) -> tuple[EvalCase, ...]:
    papers = _parse_dataset(dataset_bytes)
    cases = [
        _map_annotation(
            split=split,
            paper_id=paper_id,
            paper=paper,
            question=question,
            annotation=annotation,
        )
        for paper_id, paper in sorted(papers.items())
        for question in sorted(
            paper.qas, key=lambda item: item.question_id
        )
        for annotation in sorted(
            question.answers, key=lambda item: item.annotation_id
        )
    ]
    return tuple(sorted(cases, key=lambda item: item.case_id))


__all__ = [
    "QasperAnnotation",
    "QasperAnswer",
    "QasperPaperRecord",
    "QasperQuestion",
    "QasperSection",
    "convert_qasper",
    "materialize_qasper_content",
]
