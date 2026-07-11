# Evidence Trace Plan Review Corrections

本文件是 `2026-07-11-evidence-trace.md` 的规范性修订。执行时，本文件中同名 Chunk/Task 的要求优先于原计划；未被修订的文件边界、提交步骤和最终验收标准继续有效。

## Chunk 1 Corrections: Traceable Text and Chunks

### Task 1 revised contract

Evidence Trace 不实现 PDF 下载或解析，但必须证明“主加载器失败时回退 abstract”。`load_paper_text` 接受可选的 injectable primary loader；`no_pdf=True` 或未提供 primary loader 时直接使用 abstract，primary loader 抛出异常时也回退 abstract。真正的 PDF loader 在独立后续计划实现。

在任何实现之前写入并运行以下两个测试，确认因 `paper_agent.text` 不存在而 RED：

```python
from paper_agent.schemas import Paper
from paper_agent.text.loader import load_paper_text


def _paper() -> Paper:
    return Paper(
        paper_id="arxiv:2401.00001",
        title="Example",
        authors=[],
        year=2024,
        abstract="Evidence-grounded paper agents cite source text.",
        url="https://arxiv.org/abs/2401.00001",
        source="arxiv",
    )


def test_load_paper_text_uses_abstract_in_no_pdf_mode():
    assert load_paper_text(_paper(), no_pdf=True) == (
        "Abstract\nEvidence-grounded paper agents cite source text."
    )


def test_load_paper_text_falls_back_when_primary_loader_fails():
    def failing_loader(paper: Paper) -> str:
        raise OSError("PDF unavailable")

    assert load_paper_text(_paper(), primary_loader=failing_loader) == (
        "Abstract\nEvidence-grounded paper agents cite source text."
    )
```

Minimal implementation:

```python
from __future__ import annotations

from collections.abc import Callable

from paper_agent.schemas import Paper

PrimaryTextLoader = Callable[[Paper], str]


def _abstract_text(paper: Paper) -> str:
    return f"Abstract\n{paper.abstract}".strip()


def load_paper_text(
    paper: Paper,
    no_pdf: bool = False,
    primary_loader: PrimaryTextLoader | None = None,
) -> str:
    if no_pdf or primary_loader is None:
        return _abstract_text(paper)
    try:
        text = primary_loader(paper).strip()
    except (OSError, ValueError):
        return _abstract_text(paper)
    return text or _abstract_text(paper)
```

Focused expected result: `2 passed`. Full-suite projected result after Task 1: `17 passed`.

### Task 2 revised grammar and TDD order

Accepted sectioned-text grammar is explicit: each blank-line-delimited block is `section heading` on its first line followed immediately by one or more body lines. Example: `Abstract\nBody text.\n\nMethod\nBody text.`. A block without a body line has `section=None` and its complete text is treated as body. This milestone does not infer headings from arbitrary prose beyond that controlled loader/fixture format.

`tests/fixtures/sample_paper_text.txt` must be read by the first test. Before implementing `chunker.py`, write all four tests and run the whole file RED:

```python
from pathlib import Path

import pytest

from paper_agent.text.chunker import chunk_text


def test_chunk_text_reads_fixture_and_preserves_sections():
    text = Path("tests/fixtures/sample_paper_text.txt").read_text(encoding="utf-8")
    chunks = chunk_text("arxiv:2401.00001", text, max_words=50)
    assert [chunk.section for chunk in chunks] == [
        "Abstract",
        "Method",
        "Limitations",
    ]
    assert all(chunk.page is None for chunk in chunks)


def test_chunk_text_preserves_section_across_multiple_chunks_and_stable_ids():
    kwargs = {
        "paper_id": "p1",
        "text": "Method\none two three four five",
        "max_words": 2,
    }
    first = chunk_text(**kwargs)
    second = chunk_text(**kwargs)
    assert [chunk.section for chunk in first] == ["Method", "Method", "Method"]
    assert [chunk.chunk_id for chunk in first] == [
        "p1:chunk:001",
        "p1:chunk:002",
        "p1:chunk:003",
    ]
    assert [chunk.chunk_id for chunk in first] == [chunk.chunk_id for chunk in second]


def test_chunk_text_returns_empty_for_blank_text():
    assert chunk_text("p1", "   ") == []


def test_chunk_text_rejects_non_positive_max_words():
    with pytest.raises(ValueError, match="max_words must be at least 1"):
        chunk_text("p1", "Abstract\nText", max_words=0)
```

Then implement the original `_sections`/`chunk_text` code, with this grammar comment immediately above `_sections`:

```python
# Controlled format: each non-empty block is "heading\nbody"; a one-line block is body-only.
```

Focused expected result: `4 passed`. Full-suite projected result after Chunk 1: `21 passed`.

## Chunk 2 Corrections: Offline Evidence Retrieval

### Task 3 revised TDD order and run-scoped IDs

`retrieve_evidence` must accept a required `run_id: str`. Evidence IDs use `{run_id}:ev_001`, preventing ordinal collisions between runs.

Before creating `paper_agent/evidence/retriever.py`, write all six tests and run them together RED:

1. Matching chunk ranks first and produces `run-a:ev_001`.
2. Non-matching non-empty chunks return `[]`.
3. Empty chunks return `[]`.
4. Empty/punctuation-only question returns `[]`.
5. `top_k=0` raises `ValueError`.
6. Equal scores sort by `chunk_id`.

All calls use this signature:

```python
retrieve_evidence(question, chunks, run_id="run-a", top_k=8)
```

The complete minimal implementation replaces the original function with:

```python
def retrieve_evidence(
    question: str,
    chunks: list[Chunk],
    run_id: str,
    top_k: int = 8,
) -> list[Evidence]:
    if top_k < 1:
        raise ValueError("top_k must be at least 1")
    if not run_id.strip():
        raise ValueError("run_id must not be empty")

    query_terms = _terms(question)
    if not query_terms or not chunks:
        return []

    scored: list[tuple[float, str, Chunk]] = []
    for chunk in chunks:
        overlap = len(query_terms & _terms(chunk.text))
        score = overlap / len(query_terms)
        if score > 0:
            scored.append((score, chunk.chunk_id, chunk))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [
        Evidence(
            evidence_id=f"{run_id}:ev_{index:03d}",
            paper_id=chunk.paper_id,
            chunk_id=chunk.chunk_id,
            claim_type="retrieved",
            quote=chunk.text,
            relevance_score=round(min(score, 1.0), 4),
        )
        for index, (score, _chunk_id, chunk) in enumerate(scored[:top_k], start=1)
    ]
```

Add a seventh RED test before adding the `run_id` validation: blank `run_id` raises `ValueError("run_id must not be empty")`. All seven behaviors must be RED before the implementation that satisfies them.

Focused expected result: `7 passed`. Full-suite projected result after Chunk 2: `28 passed`.

## Chunk 3 Corrections: Citation-Grounded Offline Report

### Task 4 revised current-run and uniqueness validation

`check_claims` receives an explicit `run_id`. Evidence IDs must be unique, and only IDs prefixed with `{run_id}:` and present in the current evidence list are valid.

Before implementation, write four tests:

1. `run-b:ev_001` is supported for current `run_id="run-b"`.
2. A claim citing `run-a:ev_001` is unsupported even when current evidence contains `run-b:ev_001`.
3. Empty evidence IDs are unsupported.
4. Duplicate evidence IDs raise `ValueError("duplicate evidence_id")`.

Minimal implementation:

```python
def check_claims(
    claims: list[ReportClaim],
    evidence: list[Evidence],
    run_id: str,
) -> list[ReportClaim]:
    evidence_ids = [item.evidence_id for item in evidence]
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("duplicate evidence_id")

    valid_ids = set(evidence_ids)
    prefix = f"{run_id}:"
    checked: list[ReportClaim] = []
    for claim in claims:
        supported = bool(claim.evidence_ids) and all(
            evidence_id.startswith(prefix) and evidence_id in valid_ids
            for evidence_id in claim.evidence_ids
        )
        checked.append(
            claim.model_copy(
                update={"support_status": "supported" if supported else "unsupported"}
            )
        )
    return checked
```

Focused expected result: `4 passed`. Full-suite projected result after Task 4: `32 passed`.

### Task 5 revised deterministic/extractive synthesis

`synthesize_claims` must use `PaperAnalysis`; do not delete or ignore it. Write all three tests before implementation:

1. Calling analysis/synthesis twice with identical ordered inputs produces equal Pydantic models.
2. A paper with evidence produces one claim whose factual payload includes the extractive `analysis.contribution[0]` and whose IDs equal the analysis evidence IDs.
3. A paper without evidence produces no claim.

Minimal synthesis implementation:

```python
def synthesize_claims(
    question: str,
    papers: list[Paper],
    analyses: list[PaperAnalysis],
    evidence: list[Evidence],
) -> list[ReportClaim]:
    del question, evidence
    analysis_by_paper = {analysis.paper_id: analysis for analysis in analyses}
    claims: list[ReportClaim] = []
    for paper in papers:
        analysis = analysis_by_paper.get(paper.paper_id)
        if not analysis or not analysis.evidence_ids or not analysis.contribution:
            continue
        claims.append(
            ReportClaim(
                claim=f"{paper.title}: {analysis.contribution[0]}",
                evidence_ids=list(analysis.evidence_ids),
            )
        )
    return claims
```

`analyze_paper` keeps the original deterministic implementation, but contribution must be derived from the abstract and evidence IDs must preserve the input evidence order for that paper.

Focused expected result: `3 passed`. Full-suite projected result after Task 5: `35 passed`.

### Task 6 revised pipeline run identity

After `run_dir = create_run_dir(...)`, define:

```python
run_id = run_dir.name
```

Pass it explicitly to both boundaries:

```python
evidence = retrieve_evidence(question, chunks, run_id=run_id)
checked_claims = check_claims(claims, evidence, run_id=run_id)
```

The end-to-end test must additionally assert:

```python
assert evidence[0]["evidence_id"].startswith(f"{run_dir.name}:ev_")
```

Add one end-to-end test only; update the existing vertical-slice test without adding a new test function. Focused expected result for Task 6: `4 passed` across `test_pipeline_evidence_trace.py`, `test_pipeline_vertical_slice.py`, and `test_cli.py`. Projected full-suite result: `36 passed`.

## Corrected final verification

Run:

```bash
python -m pytest -q
git diff --check
git status --short
```

Expected pytest result for this plan, starting from the verified 15-test baseline: `36 passed`, zero failures, zero errors, zero unexpected skips. If the baseline changes before execution, record the fresh baseline and require exactly 21 newly added tests plus zero failures/errors/unexpected skips.
