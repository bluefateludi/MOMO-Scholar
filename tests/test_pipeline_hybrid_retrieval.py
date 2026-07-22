import json
import httpx

from paper_agent.config import Settings
from paper_agent.pipeline import run_pipeline
from tests.test_pipeline_fulltext_integration import Provider, _dependencies


def test_pipeline_records_one_isolated_hybrid_retrieval_per_paper(tmp_path):
    settings = Settings(dashscope_api_key="offline", retrieval_mode="hybrid")
    provider = Provider()
    client = httpx.Client(transport=httpx.MockTransport(lambda request: (_ for _ in ()).throw(AssertionError("no PDF request"))))
    dependencies = _dependencies(settings, provider, client)
    result = run_pipeline("retrieval grounding", output_base=tmp_path, no_pdf=True, settings=settings, dependencies=dependencies)
    manifest = json.loads((result.run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert [item["paper_id"] for item in manifest["retrieval_outcomes"]] == ["arxiv:2401.00001", "arxiv:2401.00002"]
    assert all(item["actual_mode"] == "hybrid" for item in manifest["retrieval_outcomes"])
