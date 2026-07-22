from paper_agent.config import Settings
from paper_agent.pipeline import run_pipeline
from tests.test_pipeline_fulltext_integration import Provider, _dependencies


def test_pipeline_writes_all_success_artifacts_in_abstract_mode(tmp_path):
    import httpx
    settings = Settings(dashscope_api_key="offline", retrieval_mode="hybrid")
    provider = Provider()
    client = httpx.Client(transport=httpx.MockTransport(lambda request: (_ for _ in ()).throw(AssertionError("no PDF request"))))
    result = run_pipeline("LLM agents for scientific literature review", output_base=tmp_path, no_pdf=True, settings=settings, dependencies=_dependencies(settings, provider, client))
    assert result.status == "completed"
    assert (result.run_dir / "papers.json").exists()
    assert "# Formal Survey:" in (result.run_dir / "report.md").read_text(encoding="utf-8")
