from __future__ import annotations

from pathlib import Path

import pytest

from paper_agent.eval.datasets.curation import curate_validation_cases
from paper_agent.eval.datasets.qasper import convert_qasper
from paper_agent.eval.datasets.scifact import convert_scifact


FIXTURE_ROOT = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "evaluation"
    / "upstream-format"
)


def _candidate_cases():
    scifact = convert_scifact(
        split="validation",
        claims_bytes=(FIXTURE_ROOT / "scifact" / "claims.jsonl").read_bytes(),
        corpus_bytes=(FIXTURE_ROOT / "scifact" / "corpus.jsonl").read_bytes(),
        corpus_source_url="https://example.test/scifact/corpus.jsonl",
    )
    qasper = convert_qasper(
        split="validation",
        dataset_bytes=(FIXTURE_ROOT / "qasper" / "qasper.json").read_bytes(),
        dataset_source_url="https://example.test/qasper/qasper.json",
    )
    return scifact + qasper


def test_curation_is_balanced_disjoint_and_deterministic() -> None:
    candidates = _candidate_cases()

    first = curate_validation_cases(
        candidates, retrieval_per_source=1, citation_per_source=1
    )
    second = curate_validation_cases(
        tuple(reversed(candidates)),
        retrieval_per_source=1,
        citation_per_source=1,
    )

    assert first == second
    assert len(first.retrieval) == 2
    assert len(first.citation) == 2
    assert len({case.case_id for case in first.combined}) == 4
    assert {case.metadata.source for case in first.retrieval} == {
        "SciFact",
        "QASPER",
    }
    assert {case.metadata.source for case in first.citation} == {
        "SciFact",
        "QASPER",
    }


def test_curation_rejects_insufficient_candidates() -> None:
    with pytest.raises(ValueError, match="fewer than"):
        curate_validation_cases(
            _candidate_cases(), retrieval_per_source=3, citation_per_source=2
        )


def test_curation_rejects_duplicate_case_ids() -> None:
    cases = _candidate_cases()

    with pytest.raises(ValueError, match="unique"):
        curate_validation_cases(cases + (cases[0],), retrieval_per_source=1)
