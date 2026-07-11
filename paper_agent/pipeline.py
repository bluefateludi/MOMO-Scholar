from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from paper_agent.evidence.citation_checker import check_claims
from paper_agent.evidence.retriever import retrieve_evidence
from paper_agent.io import create_run_dir, write_json, write_text
from paper_agent.rendering.markdown import render_evidence_review
from paper_agent.retrieval.arxiv import search_arxiv
from paper_agent.retrieval.normalize import dedupe_papers
from paper_agent.schemas import Paper
from paper_agent.synthesis.paper_reader import analyze_paper
from paper_agent.synthesis.survey import synthesize_claims
from paper_agent.text.chunker import chunk_text
from paper_agent.text.loader import load_paper_text

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
    run_id = run_dir.name
    write_json(run_dir / "papers.json", [paper.model_dump() for paper in papers])

    chunks = []
    for paper in papers:
        text = load_paper_text(paper, no_pdf=no_pdf)
        chunks.extend(chunk_text(paper.paper_id, text))

    evidence = retrieve_evidence(question, chunks, run_id=run_id)
    analyses = [analyze_paper(paper, evidence) for paper in papers]
    claims = synthesize_claims(question, papers, analyses, evidence)
    checked_claims = check_claims(claims, evidence, run_id=run_id)

    write_json(run_dir / "evidence.json", [item.model_dump() for item in evidence])
    report_md = render_evidence_review(question, papers, evidence, checked_claims)
    write_text(run_dir / "report.md", report_md)
    write_text(run_dir / "logs.jsonl", "")
    return run_dir
