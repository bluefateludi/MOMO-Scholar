from __future__ import annotations

import os
from typing import Literal

from pydantic import (
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)

from paper_agent.modeling import StrictModel


SplitName = Literal["development", "validation", "test"]
_CANONICAL_SPLIT_ORDER: tuple[SplitName, ...] = (
    "development",
    "validation",
    "test",
)


def _require_non_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


class FrozenEvalModel(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceAsset(FrozenEvalModel):
    asset_type: str
    source_url: str
    license_id: str
    redistribution: str

    _non_blank_fields = field_validator(
        "asset_type", "source_url", "license_id", "redistribution"
    )(_require_non_blank)


class DatasetSource(FrozenEvalModel):
    name: str
    upstream_version: str
    assets: tuple[SourceAsset, ...]

    _non_blank_fields = field_validator("name", "upstream_version")
    _non_blank_fields = _non_blank_fields(_require_non_blank)

    @model_validator(mode="after")
    def _asset_types_are_unique(self) -> DatasetSource:
        asset_types = [asset.asset_type for asset in self.assets]
        if len(asset_types) != len(set(asset_types)):
            raise ValueError("asset types must be unique within a source")
        return self


class SplitDeclaration(FrozenEvalModel):
    path: str
    count: StrictInt = Field(ge=0)

    _path_is_non_blank = field_validator("path")(_require_non_blank)


class SplitDeclarations(FrozenEvalModel):
    development: SplitDeclaration
    validation: SplitDeclaration
    test: SplitDeclaration

    @model_validator(mode="after")
    def _paths_are_unique(self) -> SplitDeclarations:
        paths = [
            os.path.normcase(self.development.path),
            os.path.normcase(self.validation.path),
            os.path.normcase(self.test.path),
        ]
        if len(paths) != len(set(paths)):
            raise ValueError("split paths must be unique")
        return self


class SourceSplitCount(FrozenEvalModel):
    source: str
    development: StrictInt = Field(ge=0)
    validation: StrictInt = Field(ge=0)
    test: StrictInt = Field(ge=0)

    _source_is_non_blank = field_validator("source")(_require_non_blank)


class DatasetManifest(FrozenEvalModel):
    schema_version: Literal["1.0"]
    dataset_id: str
    dataset_version: str
    sources: tuple[DatasetSource, ...]
    splits: SplitDeclarations
    source_split_counts: tuple[SourceSplitCount, ...]
    conversion_version: str

    _non_blank_fields = field_validator(
        "dataset_id", "dataset_version", "conversion_version"
    )(_require_non_blank)

    @model_validator(mode="after")
    def _source_matrix_is_consistent(self) -> DatasetManifest:
        source_names = [source.name for source in self.sources]
        if len(source_names) != len(set(source_names)):
            raise ValueError("source names must be unique")

        matrix_names = [row.source for row in self.source_split_counts]
        if len(matrix_names) != len(set(matrix_names)):
            raise ValueError("source split matrix sources must be unique")
        if set(matrix_names) != set(source_names):
            raise ValueError("source split matrix must exactly match declared sources")

        for split in _CANONICAL_SPLIT_ORDER:
            matrix_total = sum(
                getattr(source_count, split)
                for source_count in self.source_split_counts
            )
            if matrix_total != getattr(self.splits, split).count:
                raise ValueError(
                    f"source split matrix total for {split} must match split count"
                )
        return self


class AuditedSplit(FrozenEvalModel):
    split: SplitName
    case_ids: tuple[str, ...]
    fingerprint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("case_ids")
    @classmethod
    def _case_ids_are_non_blank_and_unique(
        cls, case_ids: tuple[str, ...]
    ) -> tuple[str, ...]:
        if any(not case_id.strip() for case_id in case_ids):
            raise ValueError("case IDs must not be blank")
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("case IDs must be unique within a split")
        return case_ids


class EvaluationDatasetAudit(FrozenEvalModel):
    root: str
    manifest: DatasetManifest
    audited_splits: tuple[SplitName, ...]
    splits: tuple[AuditedSplit, ...]
    fingerprint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    _root_is_non_blank = field_validator("root")(_require_non_blank)

    @model_validator(mode="after")
    def _splits_are_canonical_and_consistent(self) -> EvaluationDatasetAudit:
        authorized = set(self.audited_splits)
        canonical = tuple(
            split for split in _CANONICAL_SPLIT_ORDER if split in authorized
        )
        if self.audited_splits != canonical:
            raise ValueError("audited splits must be unique and in canonical order")

        split_names = tuple(split.split for split in self.splits)
        if split_names != self.audited_splits:
            raise ValueError("audit split results must match audited splits in order")
        return self

TaskType = Literal[
    "paper_retrieval",
    "evidence_retrieval",
    "single_paper_qa",
    "claim_verification",
    "multi_paper_synthesis",
]


class CorpusPaper(FrozenEvalModel):
    paper_id: str
    title: str
    authors: tuple[str, ...]
    year: StrictInt | None = None
    abstract: str
    url: str
    pdf_url: str | None = None
    source: str
    content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    _non_blank_fields = field_validator("paper_id", "title", "url", "source")(
        _require_non_blank
    )

    @field_validator("authors")
    @classmethod
    def _authors_are_non_blank(cls, authors: tuple[str, ...]) -> tuple[str, ...]:
        if any(not author.strip() for author in authors):
            raise ValueError("authors must not contain blank values")
        return authors

    @field_validator("pdf_url")
    @classmethod
    def _pdf_url_is_non_blank_when_present(cls, value: str | None) -> str | None:
        return _require_non_blank(value) if value is not None else None


class CorpusConstraint(FrozenEvalModel):
    papers: tuple[CorpusPaper, ...]

    @model_validator(mode="after")
    def _paper_ids_are_unique(self) -> CorpusConstraint:
        paper_ids = [paper.paper_id for paper in self.papers]
        if len(paper_ids) != len(set(paper_ids)):
            raise ValueError("corpus paper IDs must be unique")
        return self


class ReferenceEvidence(FrozenEvalModel):
    evidence_id: str
    paper_id: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_type: str
    upstream_locator: str | None = None
    page: StrictInt | None = None
    section: str | None = None
    quote: str
    relevance_grade: StrictInt
    required: StrictBool

    _non_blank_fields = field_validator(
        "evidence_id", "paper_id", "source_type", "quote"
    )(_require_non_blank)

    @field_validator("upstream_locator", "section")
    @classmethod
    def _optional_text_is_non_blank(cls, value: str | None) -> str | None:
        return _require_non_blank(value) if value is not None else None


class ReferenceClaim(FrozenEvalModel):
    claim_id: str
    text: str
    importance: Literal["critical", "normal"]
    stance: Literal["supported", "refuted", "forbidden"]
    required: StrictBool
    supporting_evidence_ids: tuple[str, ...]

    _non_blank_fields = field_validator("claim_id", "text")(_require_non_blank)

    @field_validator("supporting_evidence_ids")
    @classmethod
    def _supporting_ids_are_valid(cls, ids: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item.strip() for item in ids):
            raise ValueError("supporting evidence IDs must not be blank")
        if len(ids) != len(set(ids)):
            raise ValueError("supporting evidence IDs must be unique")
        return ids


class CaseReference(FrozenEvalModel):
    relevant_paper_ids: tuple[str, ...] | None = None
    evidence: tuple[ReferenceEvidence, ...] | None = None
    claims: tuple[ReferenceClaim, ...] | None = None
    answer: str | None = None
    unanswerable: StrictBool

    @field_validator("relevant_paper_ids")
    @classmethod
    def _relevant_ids_are_valid(
        cls, ids: tuple[str, ...] | None
    ) -> tuple[str, ...] | None:
        if ids is None:
            return None
        if not ids:
            raise ValueError("relevant paper IDs must be absent or non-empty")
        if any(not item.strip() for item in ids):
            raise ValueError("relevant paper IDs must not be blank")
        if len(ids) != len(set(ids)):
            raise ValueError("relevant paper IDs must be unique")
        return ids

    @field_validator("evidence")
    @classmethod
    def _evidence_is_valid(
        cls, items: tuple[ReferenceEvidence, ...] | None
    ) -> tuple[ReferenceEvidence, ...] | None:
        if items is None:
            return None
        if not items:
            raise ValueError("evidence must be absent or non-empty")
        ids = [item.evidence_id for item in items]
        if len(ids) != len(set(ids)):
            raise ValueError("evidence IDs must be unique")
        return items

    @field_validator("claims")
    @classmethod
    def _claims_are_valid(
        cls, items: tuple[ReferenceClaim, ...] | None
    ) -> tuple[ReferenceClaim, ...] | None:
        if items is None:
            return None
        if not items:
            raise ValueError("claims must be absent or non-empty")
        ids = [item.claim_id for item in items]
        if len(ids) != len(set(ids)):
            raise ValueError("claim IDs must be unique")
        return items

    @field_validator("answer")
    @classmethod
    def _answer_is_valid(cls, answer: str | None) -> str | None:
        return _require_non_blank(answer) if answer is not None else None

    @model_validator(mode="after")
    def _unanswerable_has_no_answer(self) -> CaseReference:
        if self.unanswerable and self.answer is not None:
            raise ValueError("unanswerable reference must not include an answer")
        return self


class RubricItem(FrozenEvalModel):
    rubric_id: str
    description: str
    required: StrictBool

    _non_blank_fields = field_validator("rubric_id", "description")(
        _require_non_blank
    )


class CaseMetadata(FrozenEvalModel):
    source: str
    split: SplitName
    domain: str
    difficulty: str

    _non_blank_fields = field_validator("source", "domain", "difficulty")(
        _require_non_blank
    )


class EvalCase(FrozenEvalModel):
    schema_version: Literal["1.0"]
    case_id: str
    task_type: TaskType
    question: str
    corpus: CorpusConstraint
    reference: CaseReference
    rubric: tuple[RubricItem, ...] = ()
    metadata: CaseMetadata

    _non_blank_fields = field_validator("case_id", "question")(_require_non_blank)

    @model_validator(mode="after")
    def _case_is_consistent(self) -> EvalCase:
        self._validate_applicability()
        self._validate_references()
        rubric_ids = [item.rubric_id for item in self.rubric]
        if len(rubric_ids) != len(set(rubric_ids)):
            raise ValueError("rubric IDs must be unique")
        return self

    def _validate_applicability(self) -> None:
        count = len(self.corpus.papers)
        if count < 1:
            raise ValueError("task corpus must contain at least one paper")
        if self.task_type == "single_paper_qa" and count != 1:
            raise ValueError("single_paper_qa corpus must contain exactly one paper")
        if self.task_type == "multi_paper_synthesis" and count < 2:
            raise ValueError("multi_paper_synthesis corpus must contain at least two papers")
        if self.task_type != "paper_retrieval" and any(
            paper.content_sha256 is None for paper in self.corpus.papers
        ):
            raise ValueError("content-dependent task corpus requires every content hash")

        present = {
            "relevant_paper_ids": self.reference.relevant_paper_ids is not None,
            "evidence": self.reference.evidence is not None,
            "claims": self.reference.claims is not None,
            "answer": self.reference.answer is not None,
        }
        required = {
            "paper_retrieval": ("relevant_paper_ids",),
            "evidence_retrieval": ("evidence",),
            "single_paper_qa": ("evidence",),
            "claim_verification": ("relevant_paper_ids", "evidence", "claims"),
            "multi_paper_synthesis": (
                "relevant_paper_ids", "evidence", "claims", "answer"
            ),
        }
        forbidden = {
            "paper_retrieval": ("evidence", "claims", "answer"),
            "evidence_retrieval": ("claims", "answer"),
            "single_paper_qa": ("claims",),
            "claim_verification": (),
            "multi_paper_synthesis": (),
        }
        missing = [field for field in required[self.task_type] if not present[field]]
        if missing:
            raise ValueError(f"{self.task_type} required fields missing: {', '.join(missing)}")
        invalid = [field for field in forbidden[self.task_type] if present[field]]
        if invalid:
            raise ValueError(f"{self.task_type} forbidden fields present: {', '.join(invalid)}")
        if (
            self.task_type == "single_paper_qa"
            and not self.reference.unanswerable
            and self.reference.answer is None
        ):
            raise ValueError("answerable single_paper_qa requires an answer")

    def _validate_references(self) -> None:
        papers = {paper.paper_id: paper for paper in self.corpus.papers}
        relevant = self.reference.relevant_paper_ids
        if relevant is not None and set(relevant) - papers.keys():
            raise ValueError("relevant paper IDs must belong to the corpus")

        evidence_ids: set[str] = set()
        if self.reference.evidence is not None:
            for evidence in self.reference.evidence:
                paper = papers.get(evidence.paper_id)
                if paper is None:
                    raise ValueError("reference evidence paper must belong to the corpus")
                if evidence.content_sha256 != paper.content_sha256:
                    raise ValueError("reference evidence content hash must match corpus paper")
                evidence_ids.add(evidence.evidence_id)
        if self.reference.claims is not None:
            for claim in self.reference.claims:
                if not set(claim.supporting_evidence_ids) <= evidence_ids:
                    raise ValueError("claim supporting evidence must exist in reference evidence")


class EvaluationDataset(FrozenEvalModel):
    manifest: DatasetManifest
    split: SplitName
    cases: tuple[EvalCase, ...]
    fingerprint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _cases_match_split(self) -> EvaluationDataset:
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("case IDs must be unique within a dataset split")
        if any(case.metadata.split != self.split for case in self.cases):
            raise ValueError("case metadata split must match selected dataset split")
        return self

__all__ = [
    "AuditedSplit",
    "CaseMetadata",
    "CaseReference",
    "CorpusConstraint",
    "CorpusPaper",
    "DatasetManifest",
    "DatasetSource",
    "EvalCase",
    "EvaluationDataset",
    "EvaluationDatasetAudit",
    "FrozenEvalModel",
    "ReferenceClaim",
    "ReferenceEvidence",
    "RubricItem",
    "SourceAsset",
    "SourceSplitCount",
    "SplitDeclaration",
    "SplitDeclarations",
    "SplitName",
    "TaskType",
]
