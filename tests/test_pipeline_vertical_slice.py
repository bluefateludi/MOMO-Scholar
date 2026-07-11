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
    assert (run_dir / "evidence.json").exists()
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "# Mini Survey" in report
    assert "Example Paper Agent Study" in report
