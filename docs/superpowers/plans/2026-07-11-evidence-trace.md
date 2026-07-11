# MOMO Scholar Evidence Trace Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the current abstract-only vertical slice into an offline, deterministic evidence-trace pipeline where every generated claim references valid evidence derived from traceable chunks.

**Architecture:** Keep external I/O separate from deterministic transformations. Load each paper through an injectable text loader, split text into stable `Chunk` records, rank chunks with an offline lexical retriever, synthesize deterministic claims, validate claim-to-evidence references, and render/write the trace. Bailian Generation, Embedding, vector databases, hybrid fusion, and Rerank are explicitly deferred to separate plans.

**Tech Stack:** Python 3.10+, Pydantic 2, Typer, pytest; no new runtime dependency and no required network/database service.

**Source Specs:**

- `docs/superpowers/specs/2026-07-11-evidence-retrieval-stack-design.md`
- `docs/superpowers/specs/2026-07-11-evidence-retrieval-stack-review-addendum.md`

---

## File Structure

| Path | Responsibility |
|:---|:---|
| `paper_agent/text/loader.py` | Convert a `Paper` into traceable text; abstract fallback is deterministic and offline. |
| `paper_agent/text/chunker.py` | Split sectioned text into stable `Chunk` records while preserving paper, section, and nullable page provenance. |
| `paper_agent/evidence/retriever.py` | Offline lexical evidence ranking and Top-K selection. |
| `paper_agent/evidence/citation_checker.py` | Validate that report claims reference evidence present in the current run. |
| `paper_agent/synthesis/paper_reader.py` | Build deterministic per-paper analysis from paper metadata and retrieved evidence. |
| `paper_agent/synthesis/survey.py` | Produce deterministic, evidence-bound report claims without an LLM. |
| `paper_agent/rendering/markdown.py` | Render papers, checked claims, and evidence trace as Markdown. |
| `paper_agent/pipeline.py` | Orchestrate retrieval, text loading, chunking, evidence ranking, checked claims, and output writes. |
| `tests/fixtures/sample_paper_text.txt` | Stable sectioned text fixture. |
| `tests/test_chunker.py` | Loader/chunker contracts and abstract fallback provenance. |
| `tests/test_evidence_retriever.py` | Lexical ranking, Top-K, empty/no-match behavior, and stable IDs. |
| `tests/test_citation_checker.py` | Valid/missing/cross-run evidence reference behavior. |
| `tests/test_pipeline_evidence_trace.py` | Offline end-to-end output and claim/evidence consistency. |

---

## Chunk 1: Traceable Text and Chunks

### Task 1: Add abstract fallback loader

**Files:**

- Create: `paper_agent/text/__init__.py`
- Create: `paper_agent/text/loader.py`
- Test: `tests/test_chunker.py`

- [ ] **Step 1: Write the failing abstract fallback test**

```python
from paper_agent.schemas import Paper
from paper_agent.text.loader import load_paper_text


def test_load_paper_text_uses_abstract_with_traceable_section():
    paper = Paper(
        paper_id="arxiv:2401.00001",
        title="Example",
        authors=[],
        year=2024,
        abstract="Evidence-grounded paper agents cite source text.",
        url="https://arxiv.org/abs/2401.00001",
        source="arxiv",
    )

    loaded = load_paper_text(paper, no_pdf=True)

    assert loaded == "Abstract\nEvidence-grounded paper agents cite source text."
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
python -m pytest tests/test_chunker.py::test_load_paper_text_uses_abstract_with_traceable_section -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'paper_agent.text'`.

- [ ] **Step 3: Implement the minimal loader**

Create `paper_agent/text/__init__.py`:

```python
"""Text loading and chunking."""
```

Create `paper_agent/text/loader.py`:

```python
from __future__ import annotations

from paper_agent.schemas import Paper


def load_paper_text(paper: Paper, no_pdf: bool = False) -> str:
    """Return traceable text, using abstract fallback for the offline milestone."""
    return f"Abstract\n{paper.abstract}".strip()
```

`no_pdf` is accepted now because the pipeline already exposes it. PDF downloading/parsing is not implemented in this task; both modes use the explicit abstract fallback.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run:

```bash
python -m pytest tests/test_chunker.py::test_load_paper_text_uses_abstract_with_traceable_section -q
```

Expected: `1 passed`.

- [ ] **Step 5: Commit Task 1**

```bash
git add paper_agent/text/__init__.py paper_agent/text/loader.py tests/test_chunker.py
git commit -m "feat: add abstract fallback text loader"
```

### Task 2: Add section-aware stable chunking

**Files:**

- Create: `paper_agent/text/chunker.py`
- Create: `tests/fixtures/sample_paper_text.txt`
- Modify: `tests/test_chunker.py`

- [ ] **Step 1: Add the sectioned fixture**

```text
Abstract
Paper agents retrieve scientific documents and generate grounded summaries.

Method
The system chunks papers into evidence spans and links claims to sources.

Limitations
The system can fail when PDF parsing loses section structure.
```

- [ ] **Step 2: Write failing section and stability tests**

```python
from paper_agent.text.chunker import chunk_text


def test_chunk_text_preserves_paper_and_section():
    chunks = chunk_text(
        paper_id="arxiv:2401.00001",
        text="Abstract\nA short abstract.\n\nMethod\nA retrieval method.",
        max_words=5,
    )

    assert [chunk.section for chunk in chunks] == ["Abstract", "Method"]
    assert all(chunk.paper_id == "arxiv:2401.00001" for chunk in chunks)
    assert chunks[0].page is None


def test_chunk_text_produces_stable_ids_for_same_input():
    kwargs = {
        "paper_id": "arxiv:2401.00001",
        "text": "Abstract\nStable source text.",
        "max_words": 20,
    }

    first = chunk_text(**kwargs)
    second = chunk_text(**kwargs)

    assert [chunk.chunk_id for chunk in first] == [chunk.chunk_id for chunk in second]
    assert first[0].chunk_id == "arxiv:2401.00001:chunk:001"
```

- [ ] **Step 3: Run the focused tests and verify RED**

Run:

```bash
python -m pytest tests/test_chunker.py -q
```

Expected: collection fails because `paper_agent.text.chunker` does not exist.

- [ ] **Step 4: Implement section-aware chunking**

Create `paper_agent/text/chunker.py`:

```python
from __future__ import annotations

from paper_agent.schemas import Chunk


def _sections(text: str) -> list[tuple[str | None, str]]:
    blocks = [block.strip() for block in text.split("\n\n") if block.strip()]
    sections: list[tuple[str | None, str]] = []
    for block in blocks:
        lines = block.splitlines()
        if len(lines) > 1:
            sections.append((lines[0].strip() or None, " ".join(lines[1:]).strip()))
        else:
            sections.append((None, block))
    return sections


def chunk_text(paper_id: str, text: str, max_words: int = 180) -> list[Chunk]:
    if max_words < 1:
        raise ValueError("max_words must be at least 1")

    chunks: list[Chunk] = []
    for section, body in _sections(text):
        words = body.split()
        for offset in range(0, len(words), max_words):
            chunk_words = words[offset : offset + max_words]
            if not chunk_words:
                continue
            number = len(chunks) + 1
            chunks.append(
                Chunk(
                    chunk_id=f"{paper_id}:chunk:{number:03d}",
                    paper_id=paper_id,
                    section=section,
                    page=None,
                    text=" ".join(chunk_words),
                    token_count=len(chunk_words),
                )
            )
    return chunks
```

- [ ] **Step 5: Add boundary tests**

```python
import pytest


def test_chunk_text_returns_empty_for_blank_text():
    assert chunk_text("p1", "   ") == []


def test_chunk_text_rejects_non_positive_max_words():
    with pytest.raises(ValueError, match="max_words must be at least 1"):
        chunk_text("p1", "Abstract\nText", max_words=0)
```

- [ ] **Step 6: Run Chunk 1 tests and full regression**

Run:

```bash
python -m pytest tests/test_chunker.py -q
python -m pytest -q
```

Expected: all chunker tests pass; the previous 15 tests remain green.

- [ ] **Step 7: Commit Task 2**

```bash
git add paper_agent/text/chunker.py tests/fixtures/sample_paper_text.txt tests/test_chunker.py
git commit -m "feat: add traceable section chunking"
```

---

## Chunk 2: Offline Evidence Retrieval

### Task 3: Add deterministic lexical retriever

**Files:**

- Create: `paper_agent/evidence/__init__.py`
- Create: `paper_agent/evidence/retriever.py`
- Test: `tests/test_evidence_retriever.py`

- [ ] **Step 1: Write the failing ranking test**

```python
from paper_agent.evidence.retriever import retrieve_evidence
from paper_agent.schemas import Chunk


def test_retrieve_evidence_ranks_matching_chunks():
    chunks = [
        Chunk(
            chunk_id="p1:chunk:001",
            paper_id="p1",
            section="Method",
            text="Paper agents use retrieval and source grounding.",
            token_count=7,
        ),
        Chunk(
            chunk_id="p2:chunk:001",
            paper_id="p2",
            section="Results",
            text="This chunk discusses unrelated biology.",
            token_count=5,
        ),
    ]

    evidence = retrieve_evidence("retrieval grounding for paper agents", chunks, top_k=1)

    assert len(evidence) == 1
    assert evidence[0].chunk_id == "p1:chunk:001"
    assert evidence[0].quote == chunks[0].text
    assert evidence[0].relevance_score > 0
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
python -m pytest tests/test_evidence_retriever.py::test_retrieve_evidence_ranks_matching_chunks -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'paper_agent.evidence'`.

- [ ] **Step 3: Implement lexical ranking and stable evidence IDs**

Create `paper_agent/evidence/__init__.py`:

```python
"""Evidence retrieval and citation checking."""
```

Create `paper_agent/evidence/retriever.py`:

```python
from __future__ import annotations

import re

from paper_agent.schemas import Chunk, Evidence


def _terms(text: str) -> set[str]:
    return {
        term
        for term in re.findall(r"[a-zA-Z][a-zA-Z0-9-]+", text.lower())
        if len(term) > 2
    }


def retrieve_evidence(question: str, chunks: list[Chunk], top_k: int = 8) -> list[Evidence]:
    if top_k < 1:
        raise ValueError("top_k must be at least 1")

    query_terms = _terms(question)
    scored: list[tuple[float, str, Chunk]] = []
    for chunk in chunks:
        chunk_terms = _terms(chunk.text)
        overlap = len(query_terms & chunk_terms)
        score = overlap / max(len(query_terms), 1)
        if score > 0:
            scored.append((score, chunk.chunk_id, chunk))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [
        Evidence(
            evidence_id=f"ev_{index:03d}",
            paper_id=chunk.paper_id,
            chunk_id=chunk.chunk_id,
            claim_type="retrieved",
            quote=chunk.text,
            relevance_score=round(min(score, 1.0), 4),
        )
        for index, (score, _chunk_id, chunk) in enumerate(scored[:top_k], start=1)
    ]
```

- [ ] **Step 4: Add boundary tests**

```python
import pytest


def test_retrieve_evidence_returns_empty_when_nothing_matches():
    chunk = Chunk(
        chunk_id="p1:chunk:001",
        paper_id="p1",
        text="Unrelated biology content.",
        token_count=3,
    )
    assert retrieve_evidence("retrieval agents", [chunk]) == []


def test_retrieve_evidence_rejects_non_positive_top_k():
    with pytest.raises(ValueError, match="top_k must be at least 1"):
        retrieve_evidence("query", [], top_k=0)


def test_retrieve_evidence_breaks_ties_by_chunk_id():
    chunks = [
        Chunk(chunk_id="p2:chunk:001", paper_id="p2", text="retrieval", token_count=1),
        Chunk(chunk_id="p1:chunk:001", paper_id="p1", text="retrieval", token_count=1),
    ]
    evidence = retrieve_evidence("retrieval", chunks, top_k=2)
    assert [item.chunk_id for item in evidence] == ["p1:chunk:001", "p2:chunk:001"]
```

- [ ] **Step 5: Run Chunk 2 tests and full regression**

Run:

```bash
python -m pytest tests/test_evidence_retriever.py -q
python -m pytest -q
```

Expected: all evidence retriever tests pass; prior tests remain green.

- [ ] **Step 6: Commit Task 3**

```bash
git add paper_agent/evidence/__init__.py paper_agent/evidence/retriever.py tests/test_evidence_retriever.py
git commit -m "feat: add offline evidence retrieval"
```

---

## Chunk 3: Citation-Grounded Offline Report

### Task 4: Add claim citation validation

**Files:**

- Create: `paper_agent/evidence/citation_checker.py`
- Test: `tests/test_citation_checker.py`

- [ ] **Step 1: Write failing validation tests**

```python
from paper_agent.evidence.citation_checker import check_claims
from paper_agent.schemas import Evidence, ReportClaim


def _evidence() -> list[Evidence]:
    return [
        Evidence(
            evidence_id="ev_001",
            paper_id="p1",
            chunk_id="p1:chunk:001",
            claim_type="retrieved",
            quote="Source text",
            relevance_score=0.9,
        )
    ]


def test_check_claims_marks_valid_reference_supported():
    checked = check_claims(
        [ReportClaim(claim="Supported", evidence_ids=["ev_001"])],
        _evidence(),
    )
    assert checked[0].support_status == "supported"


def test_check_claims_marks_missing_or_empty_reference_unsupported():
    claims = [
        ReportClaim(claim="Missing", evidence_ids=["other_run_ev_001"]),
        ReportClaim(claim="Empty", evidence_ids=[]),
    ]
    checked = check_claims(claims, _evidence())
    assert [claim.support_status for claim in checked] == ["unsupported", "unsupported"]
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
python -m pytest tests/test_citation_checker.py -q
```

Expected: collection fails because `paper_agent.evidence.citation_checker` does not exist.

- [ ] **Step 3: Implement citation validation**

Create `paper_agent/evidence/citation_checker.py`:

```python
from __future__ import annotations

from paper_agent.schemas import Evidence, ReportClaim


def check_claims(
    claims: list[ReportClaim],
    evidence: list[Evidence],
) -> list[ReportClaim]:
    valid_ids = {item.evidence_id for item in evidence}
    checked: list[ReportClaim] = []
    for claim in claims:
        supported = bool(claim.evidence_ids) and all(
            evidence_id in valid_ids for evidence_id in claim.evidence_ids
        )
        checked.append(
            claim.model_copy(
                update={"support_status": "supported" if supported else "unsupported"}
            )
        )
    return checked
```

- [ ] **Step 4: Run focused tests and full regression**

Run:

```bash
python -m pytest tests/test_citation_checker.py -q
python -m pytest -q
```

Expected: citation checker tests pass; prior tests remain green.

- [ ] **Step 5: Commit Task 4**

```bash
git add paper_agent/evidence/citation_checker.py tests/test_citation_checker.py
git commit -m "feat: validate claim evidence references"
```

### Task 5: Add deterministic analysis and synthesis

**Files:**

- Create: `paper_agent/synthesis/__init__.py`
- Create: `paper_agent/synthesis/paper_reader.py`
- Create: `paper_agent/synthesis/survey.py`
- Test: `tests/test_synthesis.py`

- [ ] **Step 1: Write failing deterministic synthesis tests**

```python
from paper_agent.schemas import Evidence, Paper
from paper_agent.synthesis.paper_reader import analyze_paper
from paper_agent.synthesis.survey import synthesize_claims


def test_analysis_and_claims_only_reference_same_run_evidence():
    paper = Paper(
        paper_id="p1",
        title="Grounded Agents",
        authors=[],
        year=2024,
        abstract="Agents link claims to source evidence.",
        url="https://example.test/p1",
        source="test",
    )
    evidence = [
        Evidence(
            evidence_id="ev_001",
            paper_id="p1",
            chunk_id="p1:chunk:001",
            claim_type="retrieved",
            quote=paper.abstract,
            relevance_score=1.0,
        )
    ]

    analysis = analyze_paper(paper, evidence)
    claims = synthesize_claims("grounded agents", [paper], [analysis], evidence)

    assert analysis.evidence_ids == ["ev_001"]
    assert claims
    assert all(set(claim.evidence_ids) <= {"ev_001"} for claim in claims)
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
python -m pytest tests/test_synthesis.py -q
```

Expected: collection fails because `paper_agent.synthesis` does not exist.

- [ ] **Step 3: Implement deterministic per-paper analysis**

Create `paper_agent/synthesis/__init__.py`:

```python
"""Deterministic offline survey synthesis."""
```

Create `paper_agent/synthesis/paper_reader.py`:

```python
from __future__ import annotations

from paper_agent.schemas import Evidence, Paper, PaperAnalysis


def analyze_paper(paper: Paper, evidence: list[Evidence]) -> PaperAnalysis:
    related = [item for item in evidence if item.paper_id == paper.paper_id]
    return PaperAnalysis(
        paper_id=paper.paper_id,
        contribution=[paper.abstract[:280]] if paper.abstract else [],
        method=[item.quote[:280] for item in related[:2]],
        experiment=[],
        limitation=[],
        evidence_ids=[item.evidence_id for item in related],
    )
```

- [ ] **Step 4: Implement deterministic evidence-bound claims**

Create `paper_agent/synthesis/survey.py`:

```python
from __future__ import annotations

from paper_agent.schemas import Evidence, Paper, PaperAnalysis, ReportClaim


def synthesize_claims(
    question: str,
    papers: list[Paper],
    analyses: list[PaperAnalysis],
    evidence: list[Evidence],
) -> list[ReportClaim]:
    del analyses
    claims: list[ReportClaim] = []
    for paper in papers:
        related = [
            item.evidence_id for item in evidence if item.paper_id == paper.paper_id
        ][:2]
        if not related:
            continue
        claims.append(
            ReportClaim(
                claim=f"{paper.title} provides evidence relevant to '{question}'.",
                evidence_ids=related,
            )
        )
    return claims
```

- [ ] **Step 5: Run synthesis tests and full regression**

Run:

```bash
python -m pytest tests/test_synthesis.py -q
python -m pytest -q
```

Expected: deterministic synthesis tests pass; prior tests remain green.

- [ ] **Step 6: Commit Task 5**

```bash
git add paper_agent/synthesis/__init__.py paper_agent/synthesis/paper_reader.py paper_agent/synthesis/survey.py tests/test_synthesis.py
git commit -m "feat: add deterministic grounded synthesis"
```

### Task 6: Integrate Evidence Trace into pipeline and renderer

**Files:**

- Modify: `paper_agent/pipeline.py`
- Modify: `paper_agent/rendering/markdown.py`
- Create: `tests/test_pipeline_evidence_trace.py`
- Modify: `tests/test_pipeline_vertical_slice.py`

- [ ] **Step 1: Write the failing end-to-end test**

```python
import json

from paper_agent.pipeline import run_pipeline
from paper_agent.schemas import Paper


def test_pipeline_writes_consistent_evidence_trace(tmp_path):
    def fake_search(query: str, limit: int) -> list[Paper]:
        return [
            Paper(
                paper_id="p1",
                title="Grounded Paper Agents",
                authors=["A. Researcher"],
                year=2024,
                abstract="Paper agents use retrieval and source grounding.",
                url="https://example.test/p1",
                source="test",
            )
        ]

    run_dir = run_pipeline(
        question="retrieval grounding for paper agents",
        output_base=tmp_path,
        limit=1,
        no_pdf=True,
        search_fn=fake_search,
    )

    evidence = json.loads((run_dir / "evidence.json").read_text(encoding="utf-8"))
    report = (run_dir / "report.md").read_text(encoding="utf-8")

    assert evidence
    assert evidence[0]["paper_id"] == "p1"
    assert evidence[0]["chunk_id"].startswith("p1:chunk:")
    assert evidence[0]["quote"] in report
    assert evidence[0]["evidence_id"] in report
    assert "## Evidence Trace" in report
    assert "unsupported" not in report
```

- [ ] **Step 2: Run the end-to-end test and verify RED**

Run:

```bash
python -m pytest tests/test_pipeline_evidence_trace.py -q
```

Expected: test fails because the current pipeline writes `evidence.json` as an empty list.

- [ ] **Step 3: Add evidence Markdown renderer**

In `paper_agent/rendering/markdown.py`, import `Evidence` and `ReportClaim`, retain `render_initial_review` for compatibility, and add:

```python
def render_evidence_review(
    question: str,
    papers: list[Paper],
    evidence: list[Evidence],
    claims: list[ReportClaim],
) -> str:
    lines = [
        f"# Mini Survey: {question}",
        "",
        "## TL;DR",
        "",
        f"Retrieved {len(papers)} papers and attached {len(evidence)} evidence spans.",
        "",
        "## Selected Papers",
        "",
    ]
    for index, paper in enumerate(papers, start=1):
        lines.extend(
            [
                f"### {index}. {paper.title}",
                "",
                f"- Year: {paper.year or 'n.d.'}",
                f"- URL: {paper.url}",
                f"- Abstract: {paper.abstract}",
                "",
            ]
        )
    lines.extend(["## Key Claims with Evidence", ""])
    for claim in claims:
        references = ", ".join(claim.evidence_ids) or "no evidence"
        lines.append(f"- {claim.claim} [{references}] ({claim.support_status})")
    lines.extend(["", "## Evidence Trace", ""])
    for item in evidence:
        lines.append(f"- **{item.evidence_id}** `{item.paper_id}`: {item.quote}")
    return "\n".join(lines).strip() + "\n"
```

- [ ] **Step 4: Integrate the deterministic Evidence Trace pipeline**

Update `paper_agent/pipeline.py` imports:

```python
from paper_agent.evidence.citation_checker import check_claims
from paper_agent.evidence.retriever import retrieve_evidence
from paper_agent.rendering.markdown import render_evidence_review
from paper_agent.synthesis.paper_reader import analyze_paper
from paper_agent.synthesis.survey import synthesize_claims
from paper_agent.text.chunker import chunk_text
from paper_agent.text.loader import load_paper_text
```

Replace the empty evidence/report writes with:

```python
    chunks = []
    for paper in papers:
        text = load_paper_text(paper, no_pdf=no_pdf)
        chunks.extend(chunk_text(paper.paper_id, text))

    evidence = retrieve_evidence(question, chunks)
    analyses = [analyze_paper(paper, evidence) for paper in papers]
    claims = synthesize_claims(question, papers, analyses, evidence)
    checked_claims = check_claims(claims, evidence)

    write_json(run_dir / "evidence.json", [item.model_dump() for item in evidence])
    report_md = render_evidence_review(question, papers, evidence, checked_claims)
```

Keep `papers.json`, `logs.jsonl`, the return value, and the injectable `search_fn` unchanged.

- [ ] **Step 5: Update the existing vertical-slice assertion**

Keep `tests/test_pipeline_vertical_slice.py` as a compatibility test. Add assertions that `evidence.json` exists and `report.md` still includes the paper title; do not duplicate the detailed trace assertions from the new test.

- [ ] **Step 6: Run focused and full verification**

Run:

```bash
python -m pytest tests/test_pipeline_evidence_trace.py tests/test_pipeline_vertical_slice.py tests/test_cli.py -q
python -m pytest -q
```

Expected: focused integration tests pass; the full suite passes with zero failures and no live network/database requirement.

- [ ] **Step 7: Run an offline CLI smoke test with the tested fake boundary**

The automated pipeline test is the required offline end-to-end verification. Do not make live arXiv a merge gate. A live CLI run may be performed separately when network is available:

```bash
python -m paper_agent.cli run "LLM agents for scientific literature review" --limit 3 --no-pdf
```

Expected when live network is available: output directory contains non-empty `papers.json`, `evidence.json` (when lexical terms match), `report.md`, and `logs.jsonl`.

- [ ] **Step 8: Review diff and commit Task 6**

Run:

```bash
git diff --check
git status --short
```

Confirm there are no unrelated files, generated outputs, secrets, database dependencies, Bailian calls, or vector-store code in the diff.

```bash
git add paper_agent/pipeline.py paper_agent/rendering/markdown.py tests/test_pipeline_evidence_trace.py tests/test_pipeline_vertical_slice.py
git commit -m "feat: integrate offline evidence trace"
```

---

## Completion Criteria

- [ ] `python -m pytest -q` passes with zero failures.
- [ ] The pipeline works without API keys, PostgreSQL, pgvector, or any vector database.
- [ ] `evidence.json` contains evidence with stable `paper_id`, `chunk_id`, quote, and score when query terms match.
- [ ] Abstract fallback chunks use section `Abstract` and page `null`.
- [ ] Report claims reference only evidence IDs from the current run.
- [ ] Missing evidence IDs are marked unsupported.
- [ ] `report.md` includes Selected Papers, Key Claims with Evidence, and Evidence Trace sections.
- [ ] Existing CLI and vertical-slice behavior remains compatible.
- [ ] No Bailian, Embedding, vector-store, hybrid-fusion, or Rerank implementation is introduced early.

## Follow-on Plan Boundaries

After this plan is complete and verified, create separate implementation plans in this order:

1. **Vector Retrieval:** `Embedder` and typed `VectorStore` contracts, `BailianEmbedder`, fake store contract tests, then one replaceable database adapter (pgvector is the current default candidate).
2. **Hybrid Retrieval:** independent vector retrieval verification first, then lexical/vector candidate fusion with normalized scores.
3. **Bailian Rerank:** reranker interface, Bailian adapter, candidate Top-N to evidence Top-K, fallback to fused order.
4. **Bailian Generation:** structured paper analysis and survey generation consuming checked evidence only.

No follow-on plan may make the offline Evidence Trace path dependent on its external service.
