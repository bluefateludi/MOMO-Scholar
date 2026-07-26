from __future__ import annotations

import os
from copy import deepcopy

import pytest
from pydantic import ValidationError

from paper_agent.eval.contracts import (
    AuditedSplit,
    DatasetManifest,
    EvalCase,
    EvaluationDatasetAudit,
)


def valid_manifest_data() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "dataset_id": "momo-rag-eval",
        "dataset_version": "2026-07-23",
        "sources": [
            {
                "name": "SciFact",
                "upstream_version": "2020-05-01",
                "assets": [
                    {
                        "asset_type": "claims-evidence",
                        "source_url": "https://example.test/scifact/claims.jsonl",
                        "license_id": "CC-BY-4.0",
                        "redistribution": "allowed-with-attribution",
                    },
                    {
                        "asset_type": "abstracts",
                        "source_url": "https://example.test/scifact/corpus.jsonl",
                        "license_id": "ODC-By-1.0",
                        "redistribution": "allowed-with-attribution",
                    },
                ],
            },
            {
                "name": "QASPER",
                "upstream_version": "1.0.0",
                "assets": [
                    {
                        "asset_type": "questions-answers",
                        "source_url": "https://example.test/qasper/data.json",
                        "license_id": "CC-BY-4.0",
                        "redistribution": "allowed-with-attribution",
                    }
                ],
            },
        ],
        "splits": {
            "development": {"path": "cases/development.jsonl", "count": 2},
            "validation": {"path": "cases/validation.jsonl", "count": 2},
            "test": {"path": "cases/test.jsonl", "count": 2},
        },
        "source_split_counts": [
            {"source": "SciFact", "development": 1, "validation": 1, "test": 1},
            {"source": "QASPER", "development": 1, "validation": 1, "test": 1},
        ],
        "conversion_version": "rag-eval-converter/1.0",
    }


def valid_manifest() -> DatasetManifest:
    return DatasetManifest.model_validate(valid_manifest_data())


def valid_audit_data() -> dict[str, object]:
    return {
        "root": "C:/dataset",
        "manifest": valid_manifest(),
        "audited_splits": ("development", "validation"),
        "splits": (
            {
                "split": "development",
                "case_ids": ("dev-1", "dev-2"),
                "fingerprint_sha256": "a" * 64,
            },
            {
                "split": "validation",
                "case_ids": ("val-1",),
                "fingerprint_sha256": "b" * 64,
            },
        ),
        "fingerprint_sha256": "c" * 64,
    }


def test_manifest_accepts_asset_provenance_and_source_split_matrix() -> None:
    manifest = valid_manifest()

    assert manifest.schema_version == "1.0"
    assert manifest.sources[0].assets[1].license_id == "ODC-By-1.0"
    assert manifest.source_split_counts[1].validation == 1
    assert isinstance(manifest.sources, tuple)
    assert isinstance(manifest.sources[0].assets, tuple)
    assert isinstance(manifest.source_split_counts, tuple)


@pytest.mark.parametrize(
    ("location", "value", "error_type"),
    [
        (("splits", "development", "count"), "2", "int_type"),
        (("splits", "development", "count"), True, "int_type"),
        (("splits", "validation", "count"), "2", "int_type"),
        (("splits", "validation", "count"), True, "int_type"),
        (("splits", "test", "count"), "2", "int_type"),
        (("splits", "test", "count"), False, "int_type"),
        (("splits", "test", "count"), -1, "greater_than_equal"),
        (("source_split_counts", 0, "development"), "1", "int_type"),
        (("source_split_counts", 0, "development"), True, "int_type"),
        (("source_split_counts", 0, "validation"), "1", "int_type"),
        (("source_split_counts", 0, "validation"), False, "int_type"),
        (("source_split_counts", 0, "test"), "1", "int_type"),
        (("source_split_counts", 0, "test"), True, "int_type"),
        (("source_split_counts", 0, "test"), -1, "greater_than_equal"),
    ],
)
def test_manifest_rejects_non_strict_or_negative_counts(
    location: tuple[str | int, ...], value: object, error_type: str
) -> None:
    data = valid_manifest_data()
    target: object = data
    for key in location[:-1]:
        target = target[key]  # type: ignore[index]
    target[location[-1]] = value  # type: ignore[index]

    with pytest.raises(ValidationError) as exc_info:
        DatasetManifest.model_validate(data)

    assert any(
        error["loc"] == location and error["type"] == error_type
        for error in exc_info.value.errors()
    )


@pytest.mark.parametrize(
    ("location", "value"),
    [
        (("dataset_id",), "  "),
        (("dataset_version",), ""),
        (("conversion_version",), "\t"),
        (("sources", 0, "name"), " "),
        (("sources", 0, "upstream_version"), ""),
        (("sources", 0, "assets", 0, "asset_type"), "\n"),
        (("sources", 0, "assets", 0, "source_url"), " "),
        (("sources", 0, "assets", 0, "license_id"), ""),
        (("sources", 0, "assets", 0, "redistribution"), "\t"),
        (("splits", "development", "path"), " "),

    ],
)
def test_manifest_rejects_blank_identifier_provenance_and_path_fields(
    location: tuple[str | int, ...], value: str
) -> None:
    data = valid_manifest_data()
    target: object = data
    for key in location[:-1]:
        target = target[key]  # type: ignore[index]
    target[location[-1]] = value  # type: ignore[index]

    with pytest.raises(ValidationError):
        DatasetManifest.model_validate(data)


def test_manifest_rejects_blank_matrix_source_at_source_field() -> None:
    data = valid_manifest_data()
    data["source_split_counts"][0]["source"] = " "  # type: ignore[index]

    with pytest.raises(ValidationError) as exc_info:
        DatasetManifest.model_validate(data)

    assert any(
        error["loc"] == ("source_split_counts", 0, "source")
        and "must not be blank" in error["msg"]
        for error in exc_info.value.errors()
    )


@pytest.mark.parametrize(
    ("location", "field"),
    [
        ((), "unexpected"),
        (("sources", 0), "unexpected"),
        (("sources", 0, "assets", 0), "unexpected"),
        (("splits",), "unexpected"),
        (("splits", "development"), "unexpected"),
        (("source_split_counts", 0), "unexpected"),
    ],
)
def test_manifest_rejects_unknown_fields(
    location: tuple[str | int, ...], field: str
) -> None:
    data = valid_manifest_data()
    target: object = data
    for key in location:
        target = target[key]  # type: ignore[index]
    target[field] = "surplus"  # type: ignore[index]

    with pytest.raises(ValidationError):
        DatasetManifest.model_validate(data)


def test_manifest_is_deeply_immutable() -> None:
    manifest = valid_manifest()

    with pytest.raises(ValidationError):
        manifest.dataset_id = "replacement"
    with pytest.raises(AttributeError):
        manifest.sources.append(manifest.sources[0])
    with pytest.raises(AttributeError):
        manifest.sources[0].assets.append(manifest.sources[0].assets[0])
    with pytest.raises(ValidationError):
        manifest.sources[0].name = "replacement"


def test_manifest_rejects_duplicate_source_names() -> None:
    data = valid_manifest_data()
    data["sources"][1]["name"] = "SciFact"  # type: ignore[index]

    with pytest.raises(ValidationError, match="source names must be unique"):
        DatasetManifest.model_validate(data)


def test_manifest_rejects_duplicate_asset_types_within_a_source() -> None:
    data = valid_manifest_data()
    duplicate = deepcopy(data["sources"][0]["assets"][0])  # type: ignore[index]
    data["sources"][0]["assets"].append(duplicate)  # type: ignore[index]

    with pytest.raises(ValidationError):
        DatasetManifest.model_validate(data)


def test_manifest_rejects_exact_duplicate_split_paths() -> None:
    data = valid_manifest_data()
    data["splits"]["validation"]["path"] = "cases/development.jsonl"  # type: ignore[index]

    with pytest.raises(ValidationError, match="split paths must be unique"):
        DatasetManifest.model_validate(data)


def test_manifest_treats_case_variant_paths_according_to_host_normcase() -> None:
    data = valid_manifest_data()
    original = data["splits"]["development"]["path"]  # type: ignore[index]
    variant = str(original).upper()
    data["splits"]["validation"]["path"] = variant  # type: ignore[index]

    if os.path.normcase(str(original)) == os.path.normcase(variant):
        with pytest.raises(ValidationError, match="split paths must be unique"):
            DatasetManifest.model_validate(data)
    else:
        manifest = DatasetManifest.model_validate(data)
        assert manifest.splits.validation.path == variant


@pytest.mark.parametrize(
    "matrix_change",
    [
        "missing",
        "extra",
        "duplicate",
    ],
)
def test_manifest_rejects_matrix_sources_that_do_not_exactly_match_sources(
    matrix_change: str,
) -> None:
    data = valid_manifest_data()
    matrix = data["source_split_counts"]  # type: ignore[assignment]
    if matrix_change == "missing":
        matrix.pop()
    elif matrix_change == "extra":
        matrix.append(
            {"source": "Extra", "development": 0, "validation": 0, "test": 0}
        )
    else:
        matrix[1]["source"] = "SciFact"

    with pytest.raises(ValidationError):
        DatasetManifest.model_validate(data)


@pytest.mark.parametrize("split", ["development", "validation", "test"])
def test_manifest_rejects_matrix_column_sum_different_from_split_total(
    split: str,
) -> None:
    data = valid_manifest_data()
    data["source_split_counts"][0][split] = 0  # type: ignore[index]

    with pytest.raises(ValidationError):
        DatasetManifest.model_validate(data)


def test_audit_accepts_canonical_authorized_splits() -> None:
    data = valid_audit_data()
    audit = EvaluationDatasetAudit.model_validate(data)

    assert audit.audited_splits == ("development", "validation")
    assert audit.splits[0] == AuditedSplit.model_validate(data["splits"][0])  # type: ignore[index]
    assert isinstance(audit.audited_splits, tuple)
    assert isinstance(audit.splits, tuple)
    assert isinstance(audit.splits[0].case_ids, tuple)


@pytest.mark.parametrize(
    "audited_splits",
    [
        ("development", "development"),
        ("validation", "development"),
        ("test", "validation"),
    ],
)
def test_audit_rejects_duplicate_or_noncanonical_split_order(
    audited_splits: tuple[str, ...],
) -> None:
    data = valid_audit_data()
    data["audited_splits"] = audited_splits

    with pytest.raises(
        ValidationError, match="audited splits must be unique and in canonical order"
    ):
        EvaluationDatasetAudit.model_validate(data)


@pytest.mark.parametrize(
    "splits",
    [
        (
            {
                "split": "validation",
                "case_ids": ("val-1",),
                "fingerprint_sha256": "b" * 64,
            },
            {
                "split": "development",
                "case_ids": ("dev-1",),
                "fingerprint_sha256": "a" * 64,
            },
        ),
        (
            {
                "split": "development",
                "case_ids": ("dev-1",),
                "fingerprint_sha256": "a" * 64,
            },
        ),
    ],
)
def test_audit_rejects_split_membership_or_order_disagreement(
    splits: tuple[dict[str, object], ...],
) -> None:
    data = valid_audit_data()
    data["splits"] = splits

    with pytest.raises(ValidationError):
        EvaluationDatasetAudit.model_validate(data)


@pytest.mark.parametrize("case_ids", [("dev-1", "dev-1"), ("dev-1", " ")])
def test_audit_rejects_duplicate_or_blank_case_ids(
    case_ids: tuple[str, ...],
) -> None:
    data = valid_audit_data()
    data["splits"][0]["case_ids"] = case_ids  # type: ignore[index]

    with pytest.raises(ValidationError):
        EvaluationDatasetAudit.model_validate(data)


@pytest.mark.parametrize(
    ("location", "value"),
    [
        (("fingerprint_sha256",), "A" * 64),
        (("fingerprint_sha256",), "a" * 63),
        (("splits", 0, "fingerprint_sha256"), "g" * 64),
        (("splits", 0, "fingerprint_sha256"), ""),
    ],
)
def test_audit_rejects_invalid_sha256_hashes(
    location: tuple[str | int, ...], value: str
) -> None:
    data = valid_audit_data()
    target: object = data
    for key in location[:-1]:
        target = target[key]  # type: ignore[index]
    target[location[-1]] = value  # type: ignore[index]

    with pytest.raises(ValidationError):
        EvaluationDatasetAudit.model_validate(data)


def test_audit_rejects_blank_root_and_unknown_fields() -> None:
    blank_root = valid_audit_data()
    blank_root["root"] = " "
    unknown_field = valid_audit_data()
    unknown_field["unexpected"] = "surplus"

    with pytest.raises(ValidationError):
        EvaluationDatasetAudit.model_validate(blank_root)
    with pytest.raises(ValidationError):
        EvaluationDatasetAudit.model_validate(unknown_field)


def test_audit_is_deeply_immutable() -> None:
    audit = EvaluationDatasetAudit.model_validate(valid_audit_data())

    with pytest.raises(ValidationError):
        audit.root = "C:/replacement"
    with pytest.raises(AttributeError):
        audit.audited_splits.append("test")
    with pytest.raises(AttributeError):
        audit.splits[0].case_ids.append("dev-3")
    with pytest.raises(ValidationError):
        audit.splits[0].split = "validation"

CONTENT_HASH = "1" * 64
SECOND_CONTENT_HASH = "2" * 64


def corpus_paper_data(
    paper_id: str = "paper-1", *, content_sha256: str | None = CONTENT_HASH
) -> dict[str, object]:
    return {
        "paper_id": paper_id,
        "title": f"Title for {paper_id}",
        "authors": ["Ada Author"],
        "year": 2024,
        "abstract": "A frozen public abstract.",
        "url": f"https://example.test/papers/{paper_id}",
        "pdf_url": f"https://example.test/papers/{paper_id}.pdf",
        "source": "SciFact",
        "content_sha256": content_sha256,
    }


def evidence_data(
    evidence_id: str = "evidence-1",
    *,
    paper_id: str = "paper-1",
    content_sha256: str = CONTENT_HASH,
) -> dict[str, object]:
    return {
        "evidence_id": evidence_id,
        "paper_id": paper_id,
        "content_sha256": content_sha256,
        "source_type": "rationale",
        "upstream_locator": "claim-17/rationale-0",
        "page": 3,
        "section": "Results",
        "quote": "The intervention improved the measured outcome.",
        "relevance_grade": 3,
        "required": True,
    }


def claim_data(
    claim_id: str = "claim-1", *, supporting_evidence_ids: list[str] | None = None
) -> dict[str, object]:
    return {
        "claim_id": claim_id,
        "text": "The intervention improves the measured outcome.",
        "importance": "critical",
        "stance": "supported",
        "required": True,
        "supporting_evidence_ids": supporting_evidence_ids or ["evidence-1"],
    }


def valid_case_data(task_type: str = "claim_verification") -> dict[str, object]:
    papers = [corpus_paper_data()]
    if task_type == "multi_paper_synthesis":
        papers.append(corpus_paper_data("paper-2", content_sha256=SECOND_CONTENT_HASH))

    reference: dict[str, object] = {"unanswerable": False}
    if task_type in {"paper_retrieval", "claim_verification", "multi_paper_synthesis"}:
        reference["relevant_paper_ids"] = [paper["paper_id"] for paper in papers]
    if task_type in {
        "evidence_retrieval",
        "single_paper_qa",
        "claim_verification",
        "multi_paper_synthesis",
    }:
        reference["evidence"] = [evidence_data()]
    if task_type in {"claim_verification", "multi_paper_synthesis"}:
        reference["claims"] = [claim_data()]
    if task_type in {"single_paper_qa", "multi_paper_synthesis"}:
        reference["answer"] = "The measured outcome improved."

    return {
        "schema_version": "1.0",
        "case_id": f"case-{task_type}",
        "task_type": task_type,
        "question": "Does the intervention improve the measured outcome?",
        "corpus": {"papers": papers},
        "reference": reference,
        "rubric": [{
            "rubric_id": "rubric-1",
            "description": "Uses the required evidence.",
            "required": True,
        }],
        "metadata": {
            "source": "SciFact",
            "split": "validation",
            "domain": "biomedicine",
            "difficulty": "medium",
        },
    }


def test_claim_verification_case_accepts_matching_gold_references() -> None:
    case = EvalCase.model_validate(valid_case_data())

    assert case.reference.relevant_paper_ids == ("paper-1",)
    assert case.reference.evidence[0].paper_id == "paper-1"
    assert case.reference.claims[0].importance == "critical"
    assert case.corpus.papers[0].content_sha256 == CONTENT_HASH
    assert isinstance(case.corpus.papers, tuple)
    assert isinstance(case.corpus.papers[0].authors, tuple)
    assert isinstance(case.reference.evidence, tuple)
    assert isinstance(case.reference.claims, tuple)
    assert isinstance(case.reference.claims[0].supporting_evidence_ids, tuple)
    assert isinstance(case.rubric, tuple)


@pytest.mark.parametrize(
    ("location", "value", "error_type"),
    [
        (("corpus", "papers", 0, "year"), "2024", "int_type"),
        (("corpus", "papers", 0, "year"), True, "int_type"),
        (("reference", "evidence", 0, "page"), "3", "int_type"),
        (("reference", "evidence", 0, "page"), False, "int_type"),
        (("reference", "evidence", 0, "relevance_grade"), "3", "int_type"),
        (("reference", "evidence", 0, "relevance_grade"), True, "int_type"),
        (("reference", "evidence", 0, "required"), "true", "bool_type"),
        (("reference", "evidence", 0, "required"), 1, "bool_type"),
        (("reference", "claims", 0, "required"), "true", "bool_type"),
        (("reference", "claims", 0, "required"), 1, "bool_type"),
        (("rubric", 0, "required"), "true", "bool_type"),
        (("rubric", 0, "required"), 1, "bool_type"),
        (("reference", "unanswerable"), "false", "bool_type"),
        (("reference", "unanswerable"), 0, "bool_type"),
    ],
)
def test_case_rejects_non_strict_scalar_values(
    location: tuple[str | int, ...], value: object, error_type: str
) -> None:
    data = valid_case_data()
    target: object = data
    for key in location[:-1]:
        target = target[key]  # type: ignore[index]
    target[location[-1]] = value  # type: ignore[index]
    with pytest.raises(ValidationError) as exc_info:
        EvalCase.model_validate(data)
    assert any(
        error["loc"] == location and error["type"] == error_type
        for error in exc_info.value.errors()
    )


@pytest.mark.parametrize(
    "location",
    [
        ("case_id",), ("question",),
        ("corpus", "papers", 0, "paper_id"),
        ("corpus", "papers", 0, "title"),
        ("corpus", "papers", 0, "authors", 0),
        ("corpus", "papers", 0, "url"),
        ("corpus", "papers", 0, "source"),
        ("reference", "relevant_paper_ids", 0),
        ("reference", "evidence", 0, "evidence_id"),
        ("reference", "evidence", 0, "source_type"),
        ("reference", "evidence", 0, "upstream_locator"),
        ("reference", "evidence", 0, "section"),
        ("reference", "evidence", 0, "quote"),
        ("reference", "claims", 0, "claim_id"),
        ("reference", "claims", 0, "text"),
        ("reference", "claims", 0, "supporting_evidence_ids", 0),
        ("rubric", 0, "rubric_id"), ("rubric", 0, "description"),
        ("metadata", "source"), ("metadata", "domain"),
        ("metadata", "difficulty"),
    ],
)
def test_case_rejects_blank_identity_text_and_provenance_fields(
    location: tuple[str | int, ...],
) -> None:
    data = valid_case_data()
    target: object = data
    for key in location[:-1]:
        target = target[key]  # type: ignore[index]
    target[location[-1]] = " "  # type: ignore[index]
    with pytest.raises(ValidationError):
        EvalCase.model_validate(data)


@pytest.mark.parametrize(
    ("location", "value"),
    [
        (("corpus", "papers", 0, "content_sha256"), "A" * 64),
        (("corpus", "papers", 0, "content_sha256"), "1" * 63),
        (("reference", "evidence", 0, "content_sha256"), "g" * 64),
        (("reference", "evidence", 0, "content_sha256"), ""),
    ],
)
def test_case_rejects_invalid_lowercase_sha256_fields(
    location: tuple[str | int, ...], value: str
) -> None:
    data = valid_case_data()
    target: object = data
    for key in location[:-1]:
        target = target[key]  # type: ignore[index]
    target[location[-1]] = value  # type: ignore[index]
    with pytest.raises(ValidationError):
        EvalCase.model_validate(data)


@pytest.mark.parametrize("duplicate_kind", ["paper", "evidence", "claim", "rubric"])
def test_case_rejects_duplicate_local_ids(duplicate_kind: str) -> None:
    data = valid_case_data()
    if duplicate_kind == "paper":
        data["corpus"]["papers"].append(deepcopy(data["corpus"]["papers"][0]))  # type: ignore[index]
    elif duplicate_kind == "evidence":
        data["reference"]["evidence"].append(deepcopy(data["reference"]["evidence"][0]))  # type: ignore[index]
    elif duplicate_kind == "claim":
        data["reference"]["claims"].append(deepcopy(data["reference"]["claims"][0]))  # type: ignore[index]
    else:
        data["rubric"].append(deepcopy(data["rubric"][0]))  # type: ignore[index]
    with pytest.raises(ValidationError, match="must be unique"):
        EvalCase.model_validate(data)


@pytest.mark.parametrize("reference_kind", ["relevant paper", "evidence paper"])
def test_case_rejects_paper_references_outside_corpus(reference_kind: str) -> None:
    data = valid_case_data()
    if reference_kind == "relevant paper":
        data["reference"]["relevant_paper_ids"] = ["outside-corpus"]  # type: ignore[index]
    else:
        data["reference"]["evidence"][0]["paper_id"] = "outside-corpus"  # type: ignore[index]
    with pytest.raises(ValidationError, match="corpus"):
        EvalCase.model_validate(data)


def test_case_rejects_evidence_hash_that_differs_from_corpus_paper() -> None:
    data = valid_case_data()
    data["reference"]["evidence"][0]["content_sha256"] = SECOND_CONTENT_HASH  # type: ignore[index]
    with pytest.raises(ValidationError, match="content hash"):
        EvalCase.model_validate(data)


def test_case_rejects_claim_supporting_evidence_outside_reference_evidence() -> None:
    data = valid_case_data()
    data["reference"]["claims"][0]["supporting_evidence_ids"] = ["missing"]  # type: ignore[index]
    with pytest.raises(ValidationError, match="supporting evidence"):
        EvalCase.model_validate(data)


def test_case_rejects_unanswerable_reference_with_nonblank_answer() -> None:
    data = valid_case_data("single_paper_qa")
    data["reference"]["unanswerable"] = True  # type: ignore[index]
    with pytest.raises(ValidationError, match="unanswerable"):
        EvalCase.model_validate(data)

@pytest.mark.parametrize(
    "task_type",
    [
        "paper_retrieval", "evidence_retrieval", "single_paper_qa",
        "claim_verification", "multi_paper_synthesis",
    ],
)
def test_case_accepts_exact_task_applicability_matrix(task_type: str) -> None:
    case = EvalCase.model_validate(valid_case_data(task_type))
    assert case.task_type == task_type


@pytest.mark.parametrize(
    ("task_type", "field"),
    [
        ("paper_retrieval", "evidence"),
        ("paper_retrieval", "claims"),
        ("paper_retrieval", "answer"),
        ("evidence_retrieval", "claims"),
        ("evidence_retrieval", "answer"),
        ("single_paper_qa", "claims"),
    ],
)
def test_case_rejects_forbidden_gold_sections(task_type: str, field: str) -> None:
    data = valid_case_data(task_type)
    values: dict[str, object] = {
        "evidence": [evidence_data()],
        "claims": [claim_data()],
        "answer": "Forbidden answer.",
    }
    data["reference"][field] = values[field]  # type: ignore[index]
    with pytest.raises(ValidationError, match="forbidden"):
        EvalCase.model_validate(data)


@pytest.mark.parametrize(
    ("task_type", "field"),
    [
        ("paper_retrieval", "relevant_paper_ids"),
        ("evidence_retrieval", "evidence"),
        ("single_paper_qa", "evidence"),
        ("claim_verification", "relevant_paper_ids"),
        ("claim_verification", "evidence"),
        ("claim_verification", "claims"),
        ("multi_paper_synthesis", "relevant_paper_ids"),
        ("multi_paper_synthesis", "evidence"),
        ("multi_paper_synthesis", "claims"),
        ("multi_paper_synthesis", "answer"),
    ],
)
def test_case_rejects_missing_required_gold_sections(
    task_type: str, field: str
) -> None:
    data = valid_case_data(task_type)
    del data["reference"][field]  # type: ignore[index]
    with pytest.raises(ValidationError, match="required"):
        EvalCase.model_validate(data)


@pytest.mark.parametrize(
    ("task_type", "field", "empty_value"),
    [
        ("paper_retrieval", "relevant_paper_ids", []),
        ("evidence_retrieval", "relevant_paper_ids", []),
        ("evidence_retrieval", "evidence", []),
        ("single_paper_qa", "relevant_paper_ids", []),
        ("single_paper_qa", "evidence", []),
        ("single_paper_qa", "answer", " "),
        ("claim_verification", "relevant_paper_ids", []),
        ("claim_verification", "evidence", []),
        ("claim_verification", "claims", []),
        ("claim_verification", "answer", ""),
        ("multi_paper_synthesis", "relevant_paper_ids", []),
        ("multi_paper_synthesis", "evidence", []),
        ("multi_paper_synthesis", "claims", []),
        ("multi_paper_synthesis", "answer", " "),
    ],
)
def test_case_rejects_empty_present_gold_sections(
    task_type: str, field: str, empty_value: object
) -> None:
    data = valid_case_data(task_type)
    data["reference"][field] = empty_value  # type: ignore[index]
    with pytest.raises(ValidationError):
        EvalCase.model_validate(data)


def test_single_paper_qa_accepts_unanswerable_without_answer() -> None:
    data = valid_case_data("single_paper_qa")
    del data["reference"]["answer"]  # type: ignore[index]
    data["reference"]["unanswerable"] = True  # type: ignore[index]
    case = EvalCase.model_validate(data)
    assert case.reference.unanswerable is True
    assert case.reference.answer is None


def test_single_paper_qa_rejects_missing_answer_when_answerable() -> None:
    data = valid_case_data("single_paper_qa")
    del data["reference"]["answer"]  # type: ignore[index]
    with pytest.raises(ValidationError, match="answer"):
        EvalCase.model_validate(data)


@pytest.mark.parametrize(
    ("task_type", "paper_count"),
    [
        ("paper_retrieval", 0), ("evidence_retrieval", 0),
        ("single_paper_qa", 0), ("single_paper_qa", 2),
        ("claim_verification", 0), ("multi_paper_synthesis", 1),
    ],
)
def test_case_rejects_task_incompatible_corpus_size(
    task_type: str, paper_count: int
) -> None:
    data = valid_case_data(task_type)
    papers = data["corpus"]["papers"]  # type: ignore[index]
    if paper_count == 0:
        papers.clear()
    elif paper_count == 1:
        del papers[1:]
        data["reference"]["relevant_paper_ids"] = ["paper-1"]  # type: ignore[index]
    else:
        papers.append(corpus_paper_data("paper-2", content_sha256=SECOND_CONTENT_HASH))
    with pytest.raises(ValidationError, match="corpus"):
        EvalCase.model_validate(data)


def test_paper_retrieval_accepts_missing_corpus_content_hash() -> None:
    data = valid_case_data("paper_retrieval")
    data["corpus"]["papers"][0]["content_sha256"] = None  # type: ignore[index]
    case = EvalCase.model_validate(data)
    assert case.corpus.papers[0].content_sha256 is None


@pytest.mark.parametrize(
    "task_type",
    [
        "evidence_retrieval", "single_paper_qa",
        "claim_verification", "multi_paper_synthesis",
    ],
)
def test_content_dependent_case_rejects_any_missing_corpus_hash(
    task_type: str,
) -> None:
    data = valid_case_data(task_type)
    data["corpus"]["papers"][-1]["content_sha256"] = None  # type: ignore[index]
    with pytest.raises(ValidationError, match="content hash"):
        EvalCase.model_validate(data)


def test_case_contracts_are_deeply_immutable() -> None:
    case = EvalCase.model_validate(valid_case_data())
    with pytest.raises(ValidationError):
        case.case_id = "replacement"
    with pytest.raises(AttributeError):
        case.corpus.papers.append(case.corpus.papers[0])
    with pytest.raises(AttributeError):
        case.corpus.papers[0].authors.append("Second Author")
    with pytest.raises(AttributeError):
        case.reference.evidence.append(case.reference.evidence[0])
    with pytest.raises(AttributeError):
        case.reference.claims[0].supporting_evidence_ids.append("evidence-2")
    with pytest.raises(AttributeError):
        case.rubric.append(case.rubric[0])
    with pytest.raises(ValidationError):
        case.metadata.source = "replacement"


@pytest.mark.parametrize(
    "location",
    [
        ("corpus",),
        ("corpus", "papers", 0),
        ("reference",),
        ("reference", "evidence", 0),
        ("reference", "claims", 0),
        ("rubric", 0),
        ("metadata",),
    ],
)
def test_case_rejects_unknown_nested_contract_fields(
    location: tuple[str | int, ...],
) -> None:
    data = valid_case_data()
    target: object = data
    for key in location:
        target = target[key]  # type: ignore[index]
    target["unexpected"] = "surplus"  # type: ignore[index]

    with pytest.raises(ValidationError) as exc_info:
        EvalCase.model_validate(data)

    assert any(error["type"] == "extra_forbidden" for error in exc_info.value.errors())

@pytest.mark.parametrize(
    ("task_type", "field", "value"),
    [
        ("evidence_retrieval", "relevant_paper_ids", ["paper-1"]),
        ("single_paper_qa", "relevant_paper_ids", ["paper-1"]),
        ("claim_verification", "answer", "Supported by the reference evidence."),
    ],
)
def test_case_accepts_present_nonempty_optional_gold_sections(
    task_type: str, field: str, value: object
) -> None:
    data = valid_case_data(task_type)
    data["reference"][field] = value  # type: ignore[index]

    case = EvalCase.model_validate(data)

    assert getattr(case.reference, field) is not None