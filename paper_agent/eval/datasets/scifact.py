from __future__ import annotations

import hashlib
import json
from typing import Literal, TypeVar

from pydantic import StrictBool, StrictInt, ValidationError, field_validator

from paper_agent.eval.contracts import EvalCase, FrozenEvalModel, SplitName
from paper_agent.eval.datasets.conversion import ConversionValidationError


def _require_non_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


class SciFactCorpusRecord(FrozenEvalModel):
    doc_id: StrictInt
    title: str
    abstract: tuple[str, ...]
    structured: StrictBool

    _title_is_non_blank = field_validator("title")(_require_non_blank)

    @field_validator("doc_id")
    @classmethod
    def _doc_id_is_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("doc_id must be non-negative")
        return value

    @field_validator("abstract")
    @classmethod
    def _abstract_is_non_empty(
        cls, abstract: tuple[str, ...]
    ) -> tuple[str, ...]:
        if not abstract:
            raise ValueError("abstract must not be empty")
        if any(not sentence.strip() for sentence in abstract):
            raise ValueError("abstract sentences must not be blank")
        return abstract


class SciFactEvidenceSet(FrozenEvalModel):
    label: Literal["SUPPORT", "CONTRADICT"]
    sentences: tuple[StrictInt, ...]

    @field_validator("sentences")
    @classmethod
    def _sentences_are_valid(
        cls, sentences: tuple[int, ...]
    ) -> tuple[int, ...]:
        if not sentences:
            raise ValueError("sentence indexes must not be empty")
        if any(index < 0 for index in sentences):
            raise ValueError("sentence indexes must be non-negative")
        if len(sentences) != len(set(sentences)):
            raise ValueError("sentence indexes must be unique")
        return sentences


class SciFactClaimRecord(FrozenEvalModel):
    id: StrictInt
    claim: str
    evidence: dict[str, tuple[SciFactEvidenceSet, ...]]
    cited_doc_ids: tuple[StrictInt, ...]

    _claim_is_non_blank = field_validator("claim")(_require_non_blank)

    @field_validator("id")
    @classmethod
    def _id_is_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("id must be non-negative")
        return value

    @field_validator("evidence")
    @classmethod
    def _evidence_keys_are_document_ids(
        cls,
        evidence: dict[str, tuple[SciFactEvidenceSet, ...]],
    ) -> dict[str, tuple[SciFactEvidenceSet, ...]]:
        if any(not key.isdigit() for key in evidence):
            raise ValueError("evidence keys must be document IDs")
        if any(not sets for sets in evidence.values()):
            raise ValueError("document evidence sets must not be empty")
        return evidence

    @field_validator("cited_doc_ids")
    @classmethod
    def _cited_ids_are_unique(
        cls, cited_doc_ids: tuple[int, ...]
    ) -> tuple[int, ...]:
        if any(doc_id < 0 for doc_id in cited_doc_ids):
            raise ValueError("cited document IDs must be non-negative")
        if len(cited_doc_ids) != len(set(cited_doc_ids)):
            raise ValueError("cited document IDs must be unique")
        return cited_doc_ids


_Record = TypeVar("_Record", bound=FrozenEvalModel)


def _parse_jsonl(
    payload: bytes,
    *,
    identity: str,
    model: type[_Record],
) -> tuple[_Record, ...]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ConversionValidationError(
            f"{identity} is not valid UTF-8"
        ) from error

    records: list[_Record] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as error:
            raise ConversionValidationError(
                f"{identity} contains invalid JSON at line {line_number}"
            ) from error
        try:
            records.append(model.model_validate(parsed))
        except ValidationError as error:
            raise ConversionValidationError(
                f"{identity} has an invalid record at line {line_number}"
            ) from error
    return tuple(records)


def materialize_scifact_content(record: SciFactCorpusRecord) -> bytes:
    return ("\n".join(record.abstract) + "\n").encode("utf-8")


def _validate_linkage(
    claims: tuple[SciFactClaimRecord, ...],
    corpus: tuple[SciFactCorpusRecord, ...],
) -> dict[int, SciFactCorpusRecord]:
    documents = {record.doc_id: record for record in corpus}
    if len(documents) != len(corpus):
        raise ConversionValidationError("corpus contains duplicate document IDs")

    claim_ids = [record.id for record in claims]
    if len(claim_ids) != len(set(claim_ids)):
        raise ConversionValidationError("claims contain duplicate claim IDs")

    for claim in claims:
        cited = set(claim.cited_doc_ids)
        if cited - documents.keys():
            raise ConversionValidationError(
                "claim cites a missing cited document"
            )
        evidence_documents = {int(doc_id) for doc_id in claim.evidence}
        if not evidence_documents <= cited:
            raise ConversionValidationError(
                "evidence document must belong to cited_doc_ids"
            )
        for doc_id_text, evidence_sets in claim.evidence.items():
            document = documents[int(doc_id_text)]
            for evidence_set in evidence_sets:
                if any(
                    index >= len(document.abstract)
                    for index in evidence_set.sentences
                ):
                    raise ConversionValidationError(
                        "evidence sentence index is outside the abstract"
                    )
    return documents


def _map_case(
    *,
    split: SplitName,
    claim: SciFactClaimRecord,
    document: SciFactCorpusRecord,
    evidence_set: SciFactEvidenceSet,
    evidence_set_index: int,
    corpus_source_url: str,
) -> EvalCase:
    paper_id = f"scifact-document-{document.doc_id}"
    case_id = (
        f"scifact-{split}-claim-{claim.id}-document-{document.doc_id}"
        f"-evidence-{evidence_set_index}"
    )
    content_hash = hashlib.sha256(
        materialize_scifact_content(document)
    ).hexdigest()
    evidence = [
        {
            "evidence_id": (
                f"scifact-claim-{claim.id}-document-{document.doc_id}"
                f"-evidence-{evidence_set_index}-sentence-{sentence_index}"
            ),
            "paper_id": paper_id,
            "content_sha256": content_hash,
            "source_type": "rationale",
            "upstream_locator": (
                f"claim/{claim.id}/evidence/{document.doc_id}"
                f"/set/{evidence_set_index}/sentence/{sentence_index}"
            ),
            "page": None,
            "section": "Abstract",
            "quote": document.abstract[sentence_index],
            "relevance_grade": 3,
            "required": True,
        }
        for sentence_index in evidence_set.sentences
    ]
    evidence_ids = [item["evidence_id"] for item in evidence]
    return EvalCase.model_validate(
        {
            "schema_version": "1.0",
            "case_id": case_id,
            "task_type": "claim_verification",
            "question": claim.claim,
            "corpus": {
                "papers": [
                    {
                        "paper_id": paper_id,
                        "title": document.title,
                        "authors": [],
                        "year": None,
                        "abstract": "\n".join(document.abstract),
                        "url": (
                            f"{corpus_source_url}#doc_id={document.doc_id}"
                        ),
                        "pdf_url": None,
                        "source": "SciFact",
                        "content_sha256": content_hash,
                    }
                ]
            },
            "reference": {
                "relevant_paper_ids": [paper_id],
                "evidence": evidence,
                "claims": [
                    {
                        "claim_id": (
                            f"scifact-claim-{claim.id}-document-{document.doc_id}"
                            f"-evidence-{evidence_set_index}-claim"
                        ),
                        "text": claim.claim,
                        "importance": "critical",
                        "stance": (
                            "supported"
                            if evidence_set.label == "SUPPORT"
                            else "refuted"
                        ),
                        "required": True,
                        "supporting_evidence_ids": evidence_ids,
                    }
                ],
                "answer": None,
                "unanswerable": False,
            },
            "rubric": [],
            "metadata": {
                "source": "SciFact",
                "split": split,
                "domain": "biomedicine",
                "difficulty": "upstream",
            },
        }
    )


def convert_scifact(
    *,
    split: SplitName,
    claims_bytes: bytes,
    corpus_bytes: bytes,
    corpus_source_url: str,
) -> tuple[EvalCase, ...]:
    _require_non_blank(corpus_source_url)
    claims = _parse_jsonl(
        claims_bytes,
        identity="claims.jsonl",
        model=SciFactClaimRecord,
    )
    corpus = _parse_jsonl(
        corpus_bytes,
        identity="corpus.jsonl",
        model=SciFactCorpusRecord,
    )
    documents = _validate_linkage(claims, corpus)

    cases = [
        _map_case(
            split=split,
            claim=claim,
            document=documents[int(doc_id)],
            evidence_set=evidence_set,
            evidence_set_index=evidence_set_index,
            corpus_source_url=corpus_source_url,
        )
        for claim in sorted(claims, key=lambda item: item.id)
        for doc_id, evidence_sets in sorted(
            claim.evidence.items(), key=lambda item: int(item[0])
        )
        for evidence_set_index, evidence_set in enumerate(evidence_sets)
    ]
    return tuple(sorted(cases, key=lambda item: item.case_id))


__all__ = [
    "SciFactClaimRecord",
    "SciFactCorpusRecord",
    "SciFactEvidenceSet",
    "convert_scifact",
    "materialize_scifact_content",
]
