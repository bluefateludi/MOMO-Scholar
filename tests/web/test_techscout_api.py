from pathlib import Path

from fastapi.testclient import TestClient

from paper_agent.config import Settings
from paper_agent.web.app import create_app
from paper_agent.web.techscout_fixtures import FIXTURE_NOTICE, SYNTHETIC_RUN_ID


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(
        state_root=tmp_path / "state", output_root=tmp_path / "outputs",
        demo_root=None, web_dist=tmp_path / "missing",
        runner=lambda *args, **kwargs: None,
        settings_loader=lambda: Settings(dashscope_api_key="unused"),
    ))


def test_v2_fixture_projects_run_report_candidates_evidence_and_trace(tmp_path):
    with _client(tmp_path) as client:
        listing = client.get("/api/v2/runs")
        assert listing.status_code == 200
        assert listing.json()["items"][0]["id"] == SYNTHETIC_RUN_ID

        detail = client.get(f"/api/v2/runs/{SYNTHETIC_RUN_ID}").json()
        assert detail["synthetic"] is True
        assert detail["progress"]["completed_stages"] == ["plan", "research", "verify", "decide"]
        assert detail["approval"]["status"] == "not_required"

        report = client.get(f"/api/v2/runs/{SYNTHETIC_RUN_ID}/report").json()
        assert report["recommendation"] == "chroma"
        assert FIXTURE_NOTICE in report["limitations"]
        assert report["poc_results"][2]["status"] == "research_only"

        candidates = client.get(f"/api/v2/runs/{SYNTHETIC_RUN_ID}/candidates").json()["items"]
        assert candidates[2]["support_level"] == "research_only"
        candidate = client.get(f"/api/v2/runs/{SYNTHETIC_RUN_ID}/candidates/chroma")
        assert candidate.status_code == 200

        evidence = client.get(f"/api/v2/runs/{SYNTHETIC_RUN_ID}/evidence").json()["items"]
        assert all(item["source_url"] is None for item in evidence)

        first = client.get(f"/api/v2/runs/{SYNTHETIC_RUN_ID}/trace?limit=2").json()
        assert len(first["items"]) == 2 and first["next_cursor"]
        second = client.get(
            f"/api/v2/runs/{SYNTHETIC_RUN_ID}/trace",
            params={"limit": 2, "cursor": first["next_cursor"]},
        ).json()
        assert len(second["items"]) == 2 and second["next_cursor"] is None


def test_v2_create_is_honest_until_harness_stream_is_connected(tmp_path):
    body = {
        "question": "Choose a local vector store",
        "project_context": "A Python local RAG application",
        "environment": {
            "python_version": "3.11", "operating_system": "Linux",
            "deployment": "single node",
        },
        "hard_constraints": ["local persistence"],
        "candidates": [{"name": "Chroma"}],
        "mode": "fast",
    }
    with _client(tmp_path) as client:
        response = client.post("/api/v2/runs", json=body)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "techscout_execution_unavailable"
