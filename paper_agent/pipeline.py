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
