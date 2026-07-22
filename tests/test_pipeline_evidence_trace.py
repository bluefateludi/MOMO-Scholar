import json
import httpx

from paper_agent.config import Settings
from paper_agent.pipeline import run_pipeline
from tests.test_pipeline_fulltext_integration import Provider, _dependencies


def test_pipeline_writes_consistent_evidence_trace(tmp_path):
    settings = Settings(dashscope_api_key="offline", retrieval_mode="hybrid")
    provider = Provider()
    client = httpx.Client(transport=httpx.MockTransport(lambda request: (_ for _ in ()).throw(AssertionError("no PDF request"))))
    result = run_pipeline("retrieval grounding for paper agents", output_base=tmp_path, no_pdf=True, settings=settings, dependencies=_dependencies(settings, provider, client))
    evidence = json.loads((result.run_dir / "evidence.json").read_text(encoding="utf-8"))
    report = (result.run_dir / "report.md").read_text(encoding="utf-8")
    assert evidence
    assert all(item["evidence_id"] in report and item["quote"] in report for item in evidence)
    assert "## Evidence Trace" in report
    assert "[unsupported]" not in report
