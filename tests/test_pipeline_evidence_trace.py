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
    assert evidence[0]["evidence_id"].startswith(f"{run_dir.name}:ev_")
    assert evidence[0]["paper_id"] == "p1"
    assert evidence[0]["chunk_id"].startswith("p1:chunk:")
    assert evidence[0]["quote"] in report
    assert evidence[0]["evidence_id"] in report
    assert "## Evidence Trace" in report
    assert "unsupported" not in report
