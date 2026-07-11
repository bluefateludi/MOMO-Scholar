# Paper Agent MVP Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a CLI-first Paper Agent MVP that retrieves papers, normalizes metadata, extracts evidence, generates citation-traceable mini surveys, and renders lightweight evaluation/showcase artifacts.

**Architecture:** Implement a small Python package with focused modules: schemas, retrieval, text loading, chunking, evidence retrieval, synthesis, citation checking, report rendering, evaluation, and CLI orchestration. The first milestone must produce a working vertical slice before adding PDF/evidence/eval depth.

**Tech Stack:** Python 3.10+, Typer, Pydantic, httpx, pytest, optional PyMuPDF for PDF parsing, static HTML rendering, OpenAI-compatible LLM adapter behind a local interface.

---

## Scope and Execution Notes

This plan implements the approved spec:

- `docs/superpowers/specs/2026-07-09-paper-agent-mvp-design.md`

The current workspace has a `.git` directory but `git status` reports `not a git repository`. Until Git is repaired or initialized, skip commit steps and record changed files manually. Once Git works, follow the commit steps included below.

Do not start with a full web app, LangGraph, MCP server, model training, or large benchmark. The MVP succeeds when this command works:

```bash
paper-agent run "LLM agents for scientific literature review"
```

and creates:

```text
outputs/<run-id>/
  papers.json
  evidence.json
  report.md
  report.html
  eval_report.md
  logs.jsonl
```

## Proposed File Structure

```text
paper_agent/
  __init__.py
  cli.py
  pipeline.py
  schemas.py
  config.py
  io.py
  retrieval/
    __init__.py
    arxiv.py
    normalize.py
  text/
    __init__.py
    loader.py
    chunker.py
  evidence/
    __init__.py
    retriever.py
    citation_checker.py
  llm/
    __init__.py
    base.py
    mock.py
    openai_compatible.py
  synthesis/
    __init__.py
    paper_reader.py
    survey.py
  rendering/
    __init__.py
    markdown.py
    html.py
  eval/
    __init__.py
    metrics.py
    runner.py
tests/
  fixtures/
    arxiv_feed.xml
    sample_paper_text.txt
    eval_cases.json
  test_schemas.py
  test_arxiv.py
  test_normalize.py
  test_chunker.py
  test_evidence_retriever.py
  test_citation_checker.py
  test_rendering.py
  test_eval_metrics.py
  test_pipeline_vertical_slice.py
pyproject.toml
README.md
.env.example
```

### Responsibility Map

| File | Responsibility |
|:---|:---|
| `paper_agent/schemas.py` | Pydantic models for Paper, Chunk, Evidence, Claim, Report, EvalResult |
| `paper_agent/config.py` | Environment/config parsing with safe defaults |
| `paper_agent/io.py` | Output directory creation and JSON/JSONL/Markdown writes |
| `paper_agent/retrieval/arxiv.py` | arXiv API query and XML parsing |
| `paper_agent/retrieval/normalize.py` | Normalize and deduplicate paper metadata |
| `paper_agent/text/loader.py` | Load PDF text or fallback abstract text |
| `paper_agent/text/chunker.py` | Convert text into traceable chunks |
| `paper_agent/evidence/retriever.py` | Rank chunks as evidence for a research question |
| `paper_agent/evidence/citation_checker.py` | Validate that report claims have evidence IDs |
| `paper_agent/llm/*` | LLM abstraction; mock provider for tests; OpenAI-compatible provider later |
| `paper_agent/synthesis/*` | Structure paper analyses and generate survey draft |
| `paper_agent/rendering/*` | Render Markdown and static HTML |
| `paper_agent/eval/*` | Compute lightweight MVP metrics |
| `paper_agent/pipeline.py` | Orchestrate modules into one run |
| `paper_agent/cli.py` | CLI entrypoint |

## Verification Commands

Run these after each meaningful task:

```bash
python -m pytest -q
```

Expected once tests exist and code is complete for the current task:

```text
... passed
```

Run the vertical slice command after Chunk 2 and later:

```bash
paper-agent run "LLM agents for scientific literature review" --limit 3 --no-pdf
```

Expected:

```text
Created outputs/<run-id>/report.md
Created outputs/<run-id>/papers.json
```

If editable install is not set up yet:

```bash
python -m paper_agent.cli run "LLM agents for scientific literature review" --limit 3 --no-pdf
```

---

## Chunk 1: Project Skeleton and Core Schemas

### Task 1: Create Python package skeleton

**Files:**

- Create: `pyproject.toml`
- Create: `paper_agent/__init__.py`
- Create: `paper_agent/cli.py`
- Create: `paper_agent/config.py`
- Create: `tests/test_schemas.py`

- [ ] **Step 1: Write minimal packaging config**

Create `pyproject.toml`:

```toml
[project]
name = "paper-agent"
version = "0.1.0"
description = "CLI-first paper research agent with citation-traceable reports"
requires-python = ">=3.10"
dependencies = [
  "typer>=0.12",
  "pydantic>=2",
  "httpx>=0.27",
  "rich>=13",
]

[project.optional-dependencies]
dev = [
  "pytest>=8",
  "pytest-cov>=5",
]
pdf = [
  "pymupdf>=1.24",
]
llm = [
  "openai>=1.0",
]

[project.scripts]
paper-agent = "paper_agent.cli:app"

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

- [ ] **Step 2: Create package init**

Create `paper_agent/__init__.py`:

```python
__version__ = "0.1.0"
```

- [ ] **Step 3: Create placeholder CLI**

Create `paper_agent/cli.py`:

```python
import typer

app = typer.Typer(help="Paper Agent: citation-traceable paper survey assistant")


@app.command()
def run(
    question: str,
    limit: int = typer.Option(5, help="Maximum number of papers to retrieve."),
    no_pdf: bool = typer.Option(False, help="Use abstract-only mode."),
) -> None:
    typer.echo(f"Paper Agent MVP placeholder: {question} limit={limit} no_pdf={no_pdf}")


if __name__ == "__main__":
    app()
```

- [ ] **Step 4: Run CLI smoke test**

Run:

```bash
python -m paper_agent.cli run "test query" --limit 2 --no-pdf
```

Expected:

```text
Paper Agent MVP placeholder: test query limit=2 no_pdf=True
```

- [ ] **Step 5: Run tests**

Run:

```bash
python -m pytest -q
```

Expected initially:

```text
no tests ran
```

If pytest returns non-zero only because no tests exist, continue after adding tests in Task 2.

- [ ] **Step 6: Commit if Git works**

```bash
git add pyproject.toml paper_agent/__init__.py paper_agent/cli.py
git commit -m "chore: scaffold paper agent package"
```

### Task 2: Define core Pydantic schemas with tests

**Files:**

- Create: `paper_agent/schemas.py`
- Modify: `tests/test_schemas.py`

- [ ] **Step 1: Write failing schema tests**

Create `tests/test_schemas.py`:

```python
from paper_agent.schemas import Chunk, Evidence, Paper, ReportClaim


def test_paper_requires_normalized_identity():
    paper = Paper(
        paper_id="arxiv:2401.00001",
        title="Example Paper",
        authors=["A. Researcher"],
        year=2024,
        abstract="Short abstract",
        url="https://arxiv.org/abs/2401.00001",
        pdf_url="https://arxiv.org/pdf/2401.00001",
        source="arxiv",
    )
    assert paper.paper_id == "arxiv:2401.00001"
    assert paper.citation_count is None


def test_evidence_links_to_chunk_and_paper():
    chunk = Chunk(
        chunk_id="arxiv:2401.00001:chunk:001",
        paper_id="arxiv:2401.00001",
        section="Abstract",
        page=None,
        text="Retrieval augmented systems use source grounding.",
        token_count=7,
    )
    evidence = Evidence(
        evidence_id="ev_001",
        paper_id=chunk.paper_id,
        chunk_id=chunk.chunk_id,
        claim_type="method",
        quote=chunk.text,
        relevance_score=0.9,
    )
    assert evidence.chunk_id == chunk.chunk_id


def test_report_claim_defaults_to_unsupported_without_evidence():
    claim = ReportClaim(claim="A claim without evidence.", evidence_ids=[])
    assert claim.support_status == "unsupported"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python -m pytest tests/test_schemas.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'paper_agent.schemas'
```

- [ ] **Step 3: Implement schemas**

Create `paper_agent/schemas.py`:

```python
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator


class Paper(BaseModel):
    paper_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    abstract: str = ""
    url: str
    pdf_url: str | None = None
    source: str
    citation_count: int | None = None


class Chunk(BaseModel):
    chunk_id: str
    paper_id: str
    section: str | None = None
    page: int | None = None
    text: str
    token_count: int

    @field_validator("text")
    @classmethod
    def text_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("chunk text must not be empty")
        return value


class Evidence(BaseModel):
    evidence_id: str
    paper_id: str
    chunk_id: str
    claim_type: str
    quote: str
    relevance_score: float = Field(ge=0.0, le=1.0)


class PaperAnalysis(BaseModel):
    paper_id: str
    contribution: list[str] = Field(default_factory=list)
    method: list[str] = Field(default_factory=list)
    experiment: list[str] = Field(default_factory=list)
    limitation: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


SupportStatus = Literal["supported", "weakly_supported", "unsupported"]


class ReportClaim(BaseModel):
    claim: str
    evidence_ids: list[str] = Field(default_factory=list)
    support_status: SupportStatus | None = None

    def model_post_init(self, __context: object) -> None:
        if self.support_status is None:
            self.support_status = "supported" if self.evidence_ids else "unsupported"


class SurveyReport(BaseModel):
    question: str
    papers: list[Paper]
    analyses: list[PaperAnalysis] = Field(default_factory=list)
    claims: list[ReportClaim] = Field(default_factory=list)
    markdown: str = ""


class EvalSummary(BaseModel):
    retrieval_hit_rate: float | None = None
    evidence_coverage: float | None = None
    unsupported_claim_rate: float | None = None
    citation_validity: float | None = None
    run_cost: float | None = None
```

- [ ] **Step 4: Run schema tests**

Run:

```bash
python -m pytest tests/test_schemas.py -q
```

Expected:

```text
3 passed
```

- [ ] **Step 5: Commit if Git works**

```bash
git add paper_agent/schemas.py tests/test_schemas.py
git commit -m "feat: add core paper agent schemas"
```

### Task 3: Add output IO helpers

**Files:**

- Create: `paper_agent/io.py`
- Create: `tests/test_io.py`

- [ ] **Step 1: Write failing IO tests**

Create `tests/test_io.py`:

```python
import json

from paper_agent.io import create_run_dir, write_json


def test_create_run_dir_uses_slug_and_timestamp(tmp_path):
    run_dir = create_run_dir(tmp_path, "LLM agents for scientific literature review")
    assert run_dir.exists()
    assert "llm-agents-for-scientific-literature-review" in run_dir.name


def test_write_json_round_trips_data(tmp_path):
    path = tmp_path / "data.json"
    write_json(path, {"hello": "world"})
    assert json.loads(path.read_text(encoding="utf-8")) == {"hello": "world"}
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python -m pytest tests/test_io.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'paper_agent.io'
```

- [ ] **Step 3: Implement IO helpers**

Create `paper_agent/io.py`:

```python
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


def slugify(value: str, max_length: int = 60) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return slug[:max_length].strip("-") or "paper-agent-run"


def create_run_dir(base_dir: Path, question: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = base_dir / f"{timestamp}-{slugify(question)}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
```

- [ ] **Step 4: Run IO tests**

Run:

```bash
python -m pytest tests/test_io.py -q
```

Expected:

```text
2 passed
```

- [ ] **Step 5: Run all tests**

Run:

```bash
python -m pytest -q
```

Expected:

```text
5 passed
```

---

## Chunk 2: Retrieval and Vertical Slice

### Task 4: Implement arXiv feed parsing

**Files:**

- Create: `paper_agent/retrieval/__init__.py`
- Create: `paper_agent/retrieval/arxiv.py`
- Create: `tests/fixtures/arxiv_feed.xml`
- Create: `tests/test_arxiv.py`

- [ ] **Step 1: Add arXiv XML fixture**

Create `tests/fixtures/arxiv_feed.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00001v1</id>
    <updated>2024-01-01T00:00:00Z</updated>
    <published>2024-01-01T00:00:00Z</published>
    <title>Example Paper Agent Study</title>
    <summary>This paper studies retrieval augmented paper agents.</summary>
    <author><name>Alice Researcher</name></author>
    <author><name>Bob Scientist</name></author>
    <link href="http://arxiv.org/abs/2401.00001v1" rel="alternate" type="text/html"/>
    <link title="pdf" href="http://arxiv.org/pdf/2401.00001v1" rel="related" type="application/pdf"/>
  </entry>
</feed>
```

- [ ] **Step 2: Write failing parser test**

Create `tests/test_arxiv.py`:

```python
from pathlib import Path

from paper_agent.retrieval.arxiv import parse_arxiv_feed


def test_parse_arxiv_feed_extracts_paper_fields():
    xml = Path("tests/fixtures/arxiv_feed.xml").read_text(encoding="utf-8")
    papers = parse_arxiv_feed(xml)
    assert len(papers) == 1
    paper = papers[0]
    assert paper.paper_id == "arxiv:2401.00001"
    assert paper.title == "Example Paper Agent Study"
    assert paper.authors == ["Alice Researcher", "Bob Scientist"]
    assert paper.year == 2024
    assert paper.pdf_url == "http://arxiv.org/pdf/2401.00001v1"
```

- [ ] **Step 3: Run test to verify failure**

Run:

```bash
python -m pytest tests/test_arxiv.py -q
```

Expected:

```text
ModuleNotFoundError
```

- [ ] **Step 4: Implement arXiv parser and client**

Create `paper_agent/retrieval/__init__.py`:

```python
"""Paper retrieval integrations."""
```

Create `paper_agent/retrieval/arxiv.py`:

```python
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from urllib.parse import urlencode

import httpx

from paper_agent.schemas import Paper

ARXIV_API_URL = "https://export.arxiv.org/api/query"
ATOM = {"atom": "http://www.w3.org/2005/Atom"}


def _clean_arxiv_id(raw_id: str) -> str:
    match = re.search(r"/abs/([^/]+)$", raw_id)
    value = match.group(1) if match else raw_id
    value = re.sub(r"v\d+$", "", value)
    return f"arxiv:{value}"


def parse_arxiv_feed(xml_text: str) -> list[Paper]:
    root = ET.fromstring(xml_text)
    papers: list[Paper] = []
    for entry in root.findall("atom:entry", ATOM):
        raw_id = entry.findtext("atom:id", default="", namespaces=ATOM)
        title = " ".join(entry.findtext("atom:title", default="", namespaces=ATOM).split())
        summary = " ".join(entry.findtext("atom:summary", default="", namespaces=ATOM).split())
        published = entry.findtext("atom:published", default="", namespaces=ATOM)
        authors = [
            name.text.strip()
            for name in entry.findall("atom:author/atom:name", ATOM)
            if name.text
        ]
        pdf_url = None
        url = raw_id
        for link in entry.findall("atom:link", ATOM):
            rel = link.attrib.get("rel")
            title_attr = link.attrib.get("title")
            href = link.attrib.get("href")
            if rel == "alternate" and href:
                url = href
            if title_attr == "pdf" and href:
                pdf_url = href
        papers.append(
            Paper(
                paper_id=_clean_arxiv_id(raw_id),
                title=title,
                authors=authors,
                year=int(published[:4]) if published[:4].isdigit() else None,
                abstract=summary,
                url=url,
                pdf_url=pdf_url,
                source="arxiv",
            )
        )
    return papers


def search_arxiv(query: str, limit: int = 5, timeout: float = 20.0) -> list[Paper]:
    params = urlencode(
        {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": limit,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
    )
    response = httpx.get(f"{ARXIV_API_URL}?{params}", timeout=timeout)
    response.raise_for_status()
    return parse_arxiv_feed(response.text)
```

- [ ] **Step 5: Run arXiv tests**

Run:

```bash
python -m pytest tests/test_arxiv.py -q
```

Expected:

```text
1 passed
```

### Task 5: Normalize and deduplicate papers

**Files:**

- Create: `paper_agent/retrieval/normalize.py`
- Create: `tests/test_normalize.py`

- [ ] **Step 1: Write failing normalization tests**

Create `tests/test_normalize.py`:

```python
from paper_agent.retrieval.normalize import dedupe_papers
from paper_agent.schemas import Paper


def test_dedupe_papers_prefers_first_seen_id():
    first = Paper(
        paper_id="arxiv:2401.00001",
        title="Same Title",
        authors=["A"],
        year=2024,
        abstract="abstract",
        url="https://arxiv.org/abs/2401.00001",
        source="arxiv",
    )
    duplicate = first.model_copy(update={"paper_id": "s2:abc"})
    assert dedupe_papers([first, duplicate]) == [first]
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
python -m pytest tests/test_normalize.py -q
```

Expected:

```text
ModuleNotFoundError
```

- [ ] **Step 3: Implement dedupe**

Create `paper_agent/retrieval/normalize.py`:

```python
from __future__ import annotations

import re

from paper_agent.schemas import Paper


def title_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def dedupe_papers(papers: list[Paper]) -> list[Paper]:
    seen: set[str] = set()
    result: list[Paper] = []
    for paper in papers:
        key = title_key(paper.title)
        if key in seen:
            continue
        seen.add(key)
        result.append(paper)
    return result
```

- [ ] **Step 4: Run normalization tests**

Run:

```bash
python -m pytest tests/test_normalize.py -q
```

Expected:

```text
1 passed
```

### Task 6: Build vertical slice pipeline with abstract-only report

**Files:**

- Create: `paper_agent/pipeline.py`
- Create: `paper_agent/rendering/__init__.py`
- Create: `paper_agent/rendering/markdown.py`
- Modify: `paper_agent/cli.py`
- Create: `tests/test_pipeline_vertical_slice.py`

- [ ] **Step 1: Write failing pipeline test with fake retriever**

Create `tests/test_pipeline_vertical_slice.py`:

```python
from pathlib import Path

from paper_agent.pipeline import run_pipeline
from paper_agent.schemas import Paper


def test_pipeline_writes_papers_and_report(tmp_path):
    def fake_search(query: str, limit: int):
        return [
            Paper(
                paper_id="arxiv:2401.00001",
                title="Example Paper Agent Study",
                authors=["Alice Researcher"],
                year=2024,
                abstract="This paper studies retrieval augmented paper agents.",
                url="https://arxiv.org/abs/2401.00001",
                pdf_url=None,
                source="arxiv",
            )
        ]

    run_dir = run_pipeline(
        question="LLM agents for scientific literature review",
        output_base=tmp_path,
        limit=1,
        no_pdf=True,
        search_fn=fake_search,
    )
    assert (run_dir / "papers.json").exists()
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "# Mini Survey" in report
    assert "Example Paper Agent Study" in report
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
python -m pytest tests/test_pipeline_vertical_slice.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'paper_agent.pipeline'
```

- [ ] **Step 3: Implement Markdown renderer**

Create `paper_agent/rendering/__init__.py`:

```python
"""Report renderers."""
```

Create `paper_agent/rendering/markdown.py`:

```python
from __future__ import annotations

from paper_agent.schemas import Paper


def render_initial_review(question: str, papers: list[Paper]) -> str:
    lines = [
        f"# Mini Survey: {question}",
        "",
        "## TL;DR",
        "",
        f"This initial review retrieved {len(papers)} candidate papers. Evidence tracing will be added in the next milestone.",
        "",
        "## Selected Papers",
        "",
    ]
    for index, paper in enumerate(papers, start=1):
        authors = ", ".join(paper.authors[:3]) or "Unknown authors"
        year = paper.year or "n.d."
        lines.extend(
            [
                f"### {index}. {paper.title}",
                "",
                f"- Year: {year}",
                f"- Authors: {authors}",
                f"- URL: {paper.url}",
                f"- Abstract: {paper.abstract}",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"
```

- [ ] **Step 4: Implement pipeline**

Create `paper_agent/pipeline.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from paper_agent.io import create_run_dir, write_json, write_text
from paper_agent.rendering.markdown import render_initial_review
from paper_agent.retrieval.arxiv import search_arxiv
from paper_agent.retrieval.normalize import dedupe_papers
from paper_agent.schemas import Paper

SearchFn = Callable[[str, int], list[Paper]]


def run_pipeline(
    question: str,
    output_base: Path = Path("outputs"),
    limit: int = 5,
    no_pdf: bool = False,
    search_fn: SearchFn = search_arxiv,
) -> Path:
    papers = dedupe_papers(search_fn(question, limit))[:limit]
    run_dir = create_run_dir(output_base, question)
    write_json(run_dir / "papers.json", [paper.model_dump() for paper in papers])
    write_json(run_dir / "evidence.json", [])
    report_md = render_initial_review(question, papers)
    write_text(run_dir / "report.md", report_md)
    write_text(run_dir / "logs.jsonl", "")
    return run_dir
```

- [ ] **Step 5: Wire CLI to pipeline**

Modify `paper_agent/cli.py`:

```python
from pathlib import Path

import typer

from paper_agent.pipeline import run_pipeline

app = typer.Typer(help="Paper Agent: citation-traceable paper survey assistant")


@app.command()
def run(
    question: str,
    limit: int = typer.Option(5, help="Maximum number of papers to retrieve."),
    no_pdf: bool = typer.Option(False, help="Use abstract-only mode."),
    output_dir: Path = typer.Option(Path("outputs"), help="Base output directory."),
) -> None:
    run_dir = run_pipeline(
        question=question,
        output_base=output_dir,
        limit=limit,
        no_pdf=no_pdf,
    )
    typer.echo(f"Created {run_dir / 'report.md'}")
    typer.echo(f"Created {run_dir / 'papers.json'}")


if __name__ == "__main__":
    app()
```

- [ ] **Step 6: Run vertical slice tests**

Run:

```bash
python -m pytest tests/test_pipeline_vertical_slice.py -q
```

Expected:

```text
1 passed
```

- [ ] **Step 7: Run CLI against live arXiv only if network is available**

Run:

```bash
python -m paper_agent.cli run "LLM agents for scientific literature review" --limit 3 --no-pdf
```

Expected:

```text
Created outputs/<run-id>/report.md
Created outputs/<run-id>/papers.json
```

If network fails, do not block implementation. The tested fake retriever already validates pipeline mechanics; live API verification can happen when network access is available.

---

## Chunk 3: Evidence Trace and Citation-Grounded Survey

### Task 7: Add text loader and chunker

**Files:**

- Create: `paper_agent/text/__init__.py`
- Create: `paper_agent/text/loader.py`
- Create: `paper_agent/text/chunker.py`
- Create: `tests/fixtures/sample_paper_text.txt`
- Create: `tests/test_chunker.py`

- [ ] **Step 1: Add sample paper text fixture**

Create `tests/fixtures/sample_paper_text.txt`:

```text
Abstract
Paper agents retrieve scientific documents and generate grounded summaries.

Method
The system chunks papers into evidence spans and links claims to sources.

Limitations
The system can fail when PDF parsing loses section structure.
```

- [ ] **Step 2: Write failing chunker test**

Create `tests/test_chunker.py`:

```python
from paper_agent.text.chunker import chunk_text


def test_chunk_text_preserves_paper_id_and_section():
    chunks = chunk_text(
        paper_id="arxiv:2401.00001",
        text="Abstract\nA short abstract.\n\nMethod\nA method section.",
        max_words=5,
    )
    assert chunks
    assert chunks[0].paper_id == "arxiv:2401.00001"
    assert chunks[0].chunk_id.startswith("arxiv:2401.00001:chunk:")
    assert chunks[0].token_count > 0
```

- [ ] **Step 3: Run test to verify failure**

Run:

```bash
python -m pytest tests/test_chunker.py -q
```

Expected:

```text
ModuleNotFoundError
```

- [ ] **Step 4: Implement loader and chunker**

Create `paper_agent/text/__init__.py`:

```python
"""Text loading and chunking."""
```

Create `paper_agent/text/loader.py`:

```python
from __future__ import annotations

from paper_agent.schemas import Paper


def load_abstract_text(paper: Paper) -> str:
    return f"Abstract\n{paper.abstract}".strip()
```

Create `paper_agent/text/chunker.py`:

```python
from __future__ import annotations

from paper_agent.schemas import Chunk


def chunk_text(paper_id: str, text: str, max_words: int = 180) -> list[Chunk]:
    words = text.split()
    chunks: list[Chunk] = []
    for index in range(0, len(words), max_words):
        chunk_words = words[index : index + max_words]
        if not chunk_words:
            continue
        chunk_number = len(chunks) + 1
        chunks.append(
            Chunk(
                chunk_id=f"{paper_id}:chunk:{chunk_number:03d}",
                paper_id=paper_id,
                section=None,
                page=None,
                text=" ".join(chunk_words),
                token_count=len(chunk_words),
            )
        )
    return chunks
```

- [ ] **Step 5: Run chunker tests**

Run:

```bash
python -m pytest tests/test_chunker.py -q
```

Expected:

```text
1 passed
```

### Task 8: Add evidence retrieval

**Files:**

- Create: `paper_agent/evidence/__init__.py`
- Create: `paper_agent/evidence/retriever.py`
- Create: `tests/test_evidence_retriever.py`

- [ ] **Step 1: Write failing evidence retrieval test**

Create `tests/test_evidence_retriever.py`:

```python
from paper_agent.evidence.retriever import retrieve_evidence
from paper_agent.schemas import Chunk


def test_retrieve_evidence_ranks_matching_chunks():
    chunks = [
        Chunk(
            chunk_id="p1:chunk:001",
            paper_id="p1",
            text="Paper agents use retrieval and source grounding.",
            token_count=7,
        ),
        Chunk(
            chunk_id="p2:chunk:001",
            paper_id="p2",
            text="This chunk discusses unrelated biology.",
            token_count=5,
        ),
    ]
    evidence = retrieve_evidence("retrieval grounding for paper agents", chunks, top_k=1)
    assert len(evidence) == 1
    assert evidence[0].chunk_id == "p1:chunk:001"
    assert evidence[0].relevance_score > 0
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
python -m pytest tests/test_evidence_retriever.py -q
```

Expected:

```text
ModuleNotFoundError
```

- [ ] **Step 3: Implement simple lexical evidence retriever**

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
    return {term for term in re.findall(r"[a-zA-Z][a-zA-Z0-9-]+", text.lower()) if len(term) > 2}


def retrieve_evidence(question: str, chunks: list[Chunk], top_k: int = 8) -> list[Evidence]:
    query_terms = _terms(question)
    scored: list[tuple[float, Chunk]] = []
    for chunk in chunks:
        chunk_terms = _terms(chunk.text)
        if not chunk_terms:
            continue
        overlap = len(query_terms & chunk_terms)
        score = overlap / max(len(query_terms), 1)
        if score > 0:
            scored.append((score, chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    evidence: list[Evidence] = []
    for index, (score, chunk) in enumerate(scored[:top_k], start=1):
        evidence.append(
            Evidence(
                evidence_id=f"ev_{index:03d}",
                paper_id=chunk.paper_id,
                chunk_id=chunk.chunk_id,
                claim_type="retrieved",
                quote=chunk.text,
                relevance_score=round(min(score, 1.0), 4),
            )
        )
    return evidence
```

- [ ] **Step 4: Run evidence tests**

Run:

```bash
python -m pytest tests/test_evidence_retriever.py -q
```

Expected:

```text
1 passed
```

### Task 9: Add paper analysis, survey synthesis, and citation checker

**Files:**

- Create: `paper_agent/synthesis/__init__.py`
- Create: `paper_agent/synthesis/paper_reader.py`
- Create: `paper_agent/synthesis/survey.py`
- Create: `paper_agent/evidence/citation_checker.py`
- Create: `tests/test_citation_checker.py`
- Modify: `paper_agent/pipeline.py`
- Modify: `paper_agent/rendering/markdown.py`

- [ ] **Step 1: Write failing citation checker test**

Create `tests/test_citation_checker.py`:

```python
from paper_agent.evidence.citation_checker import check_claims
from paper_agent.schemas import Evidence, ReportClaim


def test_check_claims_marks_missing_evidence_unsupported():
    evidence = [
        Evidence(
            evidence_id="ev_001",
            paper_id="p1",
            chunk_id="p1:chunk:001",
            claim_type="method",
            quote="Some source text",
            relevance_score=0.9,
        )
    ]
    claims = [
        ReportClaim(claim="Supported claim", evidence_ids=["ev_001"]),
        ReportClaim(claim="Unsupported claim", evidence_ids=["missing"]),
    ]
    checked = check_claims(claims, evidence)
    assert checked[0].support_status == "supported"
    assert checked[1].support_status == "unsupported"
```

- [ ] **Step 2: Implement citation checker**

Create `paper_agent/evidence/citation_checker.py`:

```python
from __future__ import annotations

from paper_agent.schemas import Evidence, ReportClaim


def check_claims(claims: list[ReportClaim], evidence: list[Evidence]) -> list[ReportClaim]:
    valid_ids = {item.evidence_id for item in evidence}
    checked: list[ReportClaim] = []
    for claim in claims:
        status = "supported" if claim.evidence_ids and all(eid in valid_ids for eid in claim.evidence_ids) else "unsupported"
        checked.append(claim.model_copy(update={"support_status": status}))
    return checked
```

- [ ] **Step 3: Create deterministic paper reader**

Create `paper_agent/synthesis/__init__.py`:

```python
"""Survey synthesis components."""
```

Create `paper_agent/synthesis/paper_reader.py`:

```python
from __future__ import annotations

from paper_agent.schemas import Evidence, Paper, PaperAnalysis


def analyze_paper(paper: Paper, evidence: list[Evidence]) -> PaperAnalysis:
    paper_evidence = [item for item in evidence if item.paper_id == paper.paper_id]
    summary = paper.abstract or "No abstract available."
    return PaperAnalysis(
        paper_id=paper.paper_id,
        contribution=[summary[:280]],
        method=[item.quote[:280] for item in paper_evidence[:2]],
        experiment=[],
        limitation=[],
        evidence_ids=[item.evidence_id for item in paper_evidence],
    )
```

- [ ] **Step 4: Create deterministic survey synthesizer**

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
    claims: list[ReportClaim] = []
    if papers:
        claims.append(
            ReportClaim(
                claim=f"The retrieved literature for '{question}' includes {len(papers)} candidate papers.",
                evidence_ids=[item.evidence_id for item in evidence[:2]],
            )
        )
    for paper in papers:
        related = [item.evidence_id for item in evidence if item.paper_id == paper.paper_id][:2]
        claims.append(
            ReportClaim(
                claim=f"{paper.title} is relevant because its abstract or text discusses {question}.",
                evidence_ids=related,
            )
        )
    return claims
```

- [ ] **Step 5: Upgrade Markdown renderer to include evidence and claims**

Modify `paper_agent/rendering/markdown.py` to add:

```python
from paper_agent.schemas import Evidence, Paper, ReportClaim


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
        f"This report retrieved {len(papers)} candidate papers and attached {len(evidence)} evidence spans.",
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
        evidence_label = ", ".join(claim.evidence_ids) if claim.evidence_ids else "no evidence"
        lines.append(f"- {claim.claim} [{evidence_label}] ({claim.support_status})")
    lines.extend(["", "## Evidence Trace", ""])
    for item in evidence:
        lines.append(f"- **{item.evidence_id}** `{item.paper_id}`: {item.quote}")
    return "\n".join(lines).strip() + "\n"
```

- [ ] **Step 6: Update pipeline to generate evidence and checked claims**

Modify `paper_agent/pipeline.py` to:

```python
from paper_agent.evidence.citation_checker import check_claims
from paper_agent.evidence.retriever import retrieve_evidence
from paper_agent.rendering.markdown import render_evidence_review
from paper_agent.synthesis.paper_reader import analyze_paper
from paper_agent.synthesis.survey import synthesize_claims
from paper_agent.text.chunker import chunk_text
from paper_agent.text.loader import load_abstract_text
```

and after papers are retrieved:

```python
chunks = []
for paper in papers:
    chunks.extend(chunk_text(paper.paper_id, load_abstract_text(paper)))
evidence = retrieve_evidence(question, chunks)
analyses = [analyze_paper(paper, evidence) for paper in papers]
claims = check_claims(synthesize_claims(question, papers, analyses, evidence), evidence)
write_json(run_dir / "evidence.json", [item.model_dump() for item in evidence])
report_md = render_evidence_review(question, papers, evidence, claims)
```

- [ ] **Step 7: Run targeted tests**

Run:

```bash
python -m pytest tests/test_citation_checker.py tests/test_pipeline_vertical_slice.py -q
```

Expected:

```text
2 passed
```

---

## Chunk 4: Evaluation, HTML Showcase, and Documentation

### Task 10: Add lightweight eval metrics

**Files:**

- Create: `paper_agent/eval/__init__.py`
- Create: `paper_agent/eval/metrics.py`
- Create: `paper_agent/eval/runner.py`
- Create: `tests/fixtures/eval_cases.json`
- Create: `tests/test_eval_metrics.py`
- Modify: `paper_agent/pipeline.py`

- [ ] **Step 1: Write failing eval metrics test**

Create `tests/test_eval_metrics.py`:

```python
from paper_agent.eval.metrics import evidence_coverage, unsupported_claim_rate
from paper_agent.schemas import ReportClaim


def test_eval_metrics_compute_claim_rates():
    claims = [
        ReportClaim(claim="A", evidence_ids=["ev_001"], support_status="supported"),
        ReportClaim(claim="B", evidence_ids=[], support_status="unsupported"),
    ]
    assert evidence_coverage(claims) == 0.5
    assert unsupported_claim_rate(claims) == 0.5
```

- [ ] **Step 2: Implement eval metrics**

Create `paper_agent/eval/__init__.py`:

```python
"""Lightweight evaluation."""
```

Create `paper_agent/eval/metrics.py`:

```python
from __future__ import annotations

from paper_agent.schemas import ReportClaim


def evidence_coverage(claims: list[ReportClaim]) -> float:
    if not claims:
        return 0.0
    return sum(1 for claim in claims if claim.evidence_ids) / len(claims)


def unsupported_claim_rate(claims: list[ReportClaim]) -> float:
    if not claims:
        return 0.0
    return sum(1 for claim in claims if claim.support_status == "unsupported") / len(claims)
```

Create `paper_agent/eval/runner.py`:

```python
from __future__ import annotations

from paper_agent.eval.metrics import evidence_coverage, unsupported_claim_rate
from paper_agent.schemas import EvalSummary, ReportClaim


def summarize_eval(claims: list[ReportClaim]) -> EvalSummary:
    return EvalSummary(
        evidence_coverage=round(evidence_coverage(claims), 4),
        unsupported_claim_rate=round(unsupported_claim_rate(claims), 4),
    )


def render_eval_markdown(summary: EvalSummary) -> str:
    return "\n".join(
        [
            "# Eval Report",
            "",
            f"- Evidence coverage: {summary.evidence_coverage}",
            f"- Unsupported claim rate: {summary.unsupported_claim_rate}",
            "",
        ]
    )
```

- [ ] **Step 3: Update pipeline to write eval report**

Modify `paper_agent/pipeline.py`:

```python
from paper_agent.eval.runner import render_eval_markdown, summarize_eval
```

After claims are checked:

```python
eval_summary = summarize_eval(claims)
write_text(run_dir / "eval_report.md", render_eval_markdown(eval_summary))
```

- [ ] **Step 4: Run eval tests**

Run:

```bash
python -m pytest tests/test_eval_metrics.py -q
```

Expected:

```text
1 passed
```

### Task 11: Add static HTML renderer

**Files:**

- Create: `paper_agent/rendering/html.py`
- Create: `tests/test_rendering.py`
- Modify: `paper_agent/pipeline.py`

- [ ] **Step 1: Write failing HTML renderer test**

Create `tests/test_rendering.py`:

```python
from paper_agent.rendering.html import render_html


def test_render_html_wraps_markdown_content():
    html = render_html("# Title\n\nBody")
    assert "<html" in html
    assert "Title" in html
    assert "Body" in html
```

- [ ] **Step 2: Implement simple HTML renderer**

Create `paper_agent/rendering/html.py`:

```python
from __future__ import annotations

import html


def render_html(markdown_text: str) -> str:
    escaped = html.escape(markdown_text)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Paper Agent Report</title>
  <style>
    body {{ font-family: Inter, system-ui, sans-serif; margin: 2rem; line-height: 1.6; }}
    pre {{ white-space: pre-wrap; background: #f7f7f8; padding: 1rem; border-radius: 12px; }}
  </style>
</head>
<body>
  <h1>Paper Agent Report</h1>
  <pre>{escaped}</pre>
</body>
</html>
"""
```

- [ ] **Step 3: Update pipeline to write HTML**

Modify `paper_agent/pipeline.py`:

```python
from paper_agent.rendering.html import render_html
```

After `report.md` is written:

```python
write_text(run_dir / "report.html", render_html(report_md))
```

- [ ] **Step 4: Run rendering tests**

Run:

```bash
python -m pytest tests/test_rendering.py -q
```

Expected:

```text
1 passed
```

### Task 12: Add README, env example, and final verification

**Files:**

- Create: `.env.example`
- Modify: `README.md`
- Optional modify: `PaperAgent.md`

- [ ] **Step 1: Create env example**

Create `.env.example`:

```env
# Optional for OpenAI-compatible generation in later milestones
OPENAI_API_KEY=
OPENAI_BASE_URL=
PAPER_AGENT_MODEL=

# Optional academic APIs
SEMANTIC_SCHOLAR_API_KEY=
OPENALEX_MAIL_ADDRESS=
```

- [ ] **Step 2: Write README quickstart**

Create or update `README.md`:

````md
# Paper Agent

CLI-first paper research agent that retrieves scientific papers, extracts evidence, and generates citation-traceable mini surveys.

## Quickstart

```bash
python -m pip install -e ".[dev]"
paper-agent run "LLM agents for scientific literature review" --limit 3 --no-pdf
```

Outputs:

```text
outputs/<run-id>/
  papers.json
  evidence.json
  report.md
  report.html
  eval_report.md
  logs.jsonl
```

## MVP Focus

- Paper retrieval from arXiv.
- Metadata normalization and deduplication.
- Abstract/PDF text loading with fallback.
- Evidence-grounded claims.
- Lightweight eval report.
- Static HTML showcase.
````

- [ ] **Step 3: Run all tests**

Run:

```bash
python -m pytest -q
```

Expected:

```text
all tests passed
```

- [ ] **Step 4: Run end-to-end command**

Run:

```bash
python -m paper_agent.cli run "LLM agents for scientific literature review" --limit 3 --no-pdf
```

Expected:

```text
Created outputs/<run-id>/report.md
Created outputs/<run-id>/papers.json
```

Then verify output files:

```bash
Get-ChildItem outputs -Recurse -Filter report.md | Select-Object -First 1
Get-ChildItem outputs -Recurse -Filter report.html | Select-Object -First 1
Get-ChildItem outputs -Recurse -Filter eval_report.md | Select-Object -First 1
```

Expected: each command returns at least one file.

- [ ] **Step 5: Commit if Git works**

```bash
git add .
git commit -m "feat: build paper agent mvp vertical slice"
```

---

## Completion Criteria

The MVP implementation is ready for first demo when:

- [ ] `python -m pytest -q` passes.
- [ ] CLI creates a new `outputs/<run-id>/` directory.
- [ ] `papers.json` contains normalized paper metadata.
- [ ] `evidence.json` contains evidence spans or an explicit empty list for no matches.
- [ ] `report.md` includes selected papers, key claims, and evidence trace.
- [ ] `report.html` can be opened as a static showcase.
- [ ] `eval_report.md` includes evidence coverage and unsupported claim rate.
- [ ] README explains quickstart and MVP focus.

## Suggested Implementation Order

1. Chunk 1: package, schemas, IO.
2. Chunk 2: arXiv retrieval and vertical slice.
3. Chunk 3: evidence trace and citation-grounded survey.
4. Chunk 4: eval, HTML, README.

Do not proceed to advanced features until the vertical slice works end-to-end.
