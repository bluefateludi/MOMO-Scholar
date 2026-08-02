from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from urllib.parse import quote

from fastapi.testclient import TestClient

from paper_agent.config import Settings
from paper_agent.fulltext.models import DocumentRecord
from paper_agent.observability.models import RunCounts, RunIssue, SafeRunSettings, UsageTotals
from paper_agent.observability.recorder import RunRecorder
from paper_agent.schemas import Evidence, Paper
from paper_agent.synthesis.models import (
    CheckedClaim, CheckedFinding, CheckedPaperAnalysis, CheckedSurveyReport,
)
from paper_agent.web.app import create_app
from paper_agent.web.demo import DEMO_API_ID


REQUEST = {
    "question": "  grounded literature review  ",
    "paper_limit": 1,
    "content_mode": "abstract_only",
    "retrieval": {
        "mode": "lexical", "candidate_k": 4, "top_k": 2, "rrf_k": 60,
        "analysis_evidence_per_paper": 1,
    },
}


def _settings() -> Settings:
    return Settings(dashscope_api_key="secret-canary", trace_enabled=False)


class SuccessfulRunner:
    def __init__(self, status: str = "completed") -> None:
        self.calls: list[dict[str, object]] = []
        self.error: str | None = None
        self.status = status

    def __call__(self, question: str, **kwargs: object) -> object:
        try:
            return self._run(question, **kwargs)
        except Exception as error:
            self.error = repr(error)
            raise

    def _run(self, question: str, **kwargs: object) -> object:
        self.calls.append({"question": question, **kwargs})
        settings = kwargs["settings"]
        recorder = RunRecorder.start(
            output_base=kwargs["output_base"], question=question,
            requested_limit=kwargs["limit"], no_pdf=kwargs["no_pdf"],
            safe_settings=SafeRunSettings.from_settings(settings, chunk_max_words=180, chunk_overlap_words=30),
            component_versions={"paper-agent": "test"}, trace_enabled=False,
            artifact_created_sink=kwargs["artifact_created_sink"],
        )
        paper = Paper(
            paper_id="arxiv:1234.5678", title="Grounded Paper", authors=["A"],
            year=2026, abstract="Evidence.", url="https://example.test/paper",
            pdf_url=None, source="test",
        )
        document = DocumentRecord(
            paper_id=paper.paper_id, content_source="abstract",
            content_sha256="a" * 64, page_count=1, fallback_code=None,
        )
        evidence = Evidence(
            evidence_id=f"{recorder.run_id}:paper:{paper.paper_id}:ev_001",
            paper_id=paper.paper_id, chunk_id=f"{paper.paper_id}:chunk:0001",
            section=None, page=None, claim_type="finding", quote="Persisted quote",
            relevance_score=0.9,
        )
        report = CheckedSurveyReport(
            question=question,
            tldr_claims=[CheckedClaim(text="Supported", evidence_ids=[evidence.evidence_id], support_status="supported")],
            key_findings=[CheckedClaim(text="Supported", evidence_ids=[evidence.evidence_id], support_status="supported")],
        )
        recorder.write_papers([paper])
        recorder.write_documents([document])
        recorder.write_evidence([evidence])
        recorder.write_analyses([CheckedPaperAnalysis(
            paper_id=paper.paper_id,
            contributions=[CheckedFinding(
                text="Supported", evidence_ids=[evidence.evidence_id],
                support_status="supported",
            )],
        )])
        recorder.publish_report(report, "# Exact persisted Markdown\n")
        recorder.complete(
            status=self.status, counts=RunCounts(
                selected_papers=1, pdf_documents=0, abstract_documents=1,
                explicit_abstract_documents=1, pdf_fallback_documents=0,
                excluded_papers=0, successful_analyses=1, evidence_items=1,
            ), retrieval_outcomes=[], stage_elapsed_seconds={},
            usage=UsageTotals(operations=0, http_attempts=0),
            degradations=(
                [RunIssue(stage="retrieval", code="vector_network_unavailable")]
                if self.status == "completed_with_degradation" else []
            ),
        )
        return object()


class BlockingRunner:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def __call__(self, question: str, **kwargs: object) -> object:
        self.started.set()
        self.release.wait(timeout=10)
        raise RuntimeError("secret-canary provider body")


def _client(tmp_path: Path, runner: object, capacity: int = 4) -> TestClient:
    return TestClient(create_app(
        state_root=tmp_path / "state", output_root=tmp_path / "outputs",
        runner=runner, settings_loader=_settings, queue_capacity=capacity,
    ))


def _wait_terminal(client: TestClient, run_id: str) -> dict[str, object]:
    for _ in range(100):
        response = client.get(f"/api/v1/runs/{run_id}")
        if response.json()["status"] not in {"queued", "running"}:
            return response.json()
        time.sleep(0.01)
    raise AssertionError("run did not finish")


def test_create_maps_request_and_exposes_validated_views(tmp_path):
    runner = SuccessfulRunner()
    with _client(tmp_path, runner) as client:
        response = client.post("/api/v1/runs", json=REQUEST)
        assert response.status_code == 202
        created = response.json()
        assert created["status"] == "queued"
        assert created["question"] == "grounded literature review"
        assert response.headers["location"] == f"/api/v1/runs/{created['id']}"
        detail = _wait_terminal(client, created["id"])
        assert detail["status"] == "completed", runner.error
        assert detail["has_report"] is True
        assert detail["manifest"]["counts"]["evidence_items"] == 1

        call = runner.calls[0]
        assert call["limit"] == 1 and call["no_pdf"] is True
        settings = call["settings"]
        assert settings.retrieval_mode == "lexical"
        assert settings.retrieval_candidate_k == 4
        assert settings.retrieval_top_k == 2
        assert settings.analysis_evidence_per_paper == 1

        report = client.get(f"/api/v1/runs/{created['id']}/report")
        persisted_markdown = report.json()["markdown"]
        assert persisted_markdown.replace("\r\n", "\n") == "# Exact persisted Markdown\n"
        evidence = client.get(f"/api/v1/runs/{created['id']}/evidence").json()["items"]
        assert evidence[0]["source"]["content_source"] == "abstract"
        exact = client.get(f"/api/v1/runs/{created['id']}/evidence/{evidence[0]['evidence_id']}")
        assert exact.status_code == 200
        encoded = quote(evidence[0]["evidence_id"], safe="")
        assert client.get(f"/api/v1/runs/{created['id']}/evidence/{encoded}").json() == exact.json()

        papers = client.get(f"/api/v1/runs/{created['id']}/papers")
        assert papers.status_code == 200
        assert papers.json()["items"][0]["analysis_available"] is True
        paper_id = quote(papers.json()["items"][0]["paper_id"], safe="")
        analysis = client.get(f"/api/v1/runs/{created['id']}/papers/{paper_id}/analysis")
        assert analysis.status_code == 200
        assert analysis.json()["analysis"]["paper_id"] == "arxiv:1234.5678"

        download = client.get(f"/api/v1/runs/{created['id']}/artifacts/report.md")
        assert download.content.decode("utf-8") == persisted_markdown
        assert download.headers["content-type"].startswith("text/markdown")
        assert "attachment" in download.headers["content-disposition"]
        assert download.headers["x-content-type-options"] == "nosniff"
        assert "secret-canary" not in json.dumps(detail)


def test_strict_validation_and_safe_error_envelope(tmp_path):
    with _client(tmp_path, SuccessfulRunner()) as client:
        invalid = {**REQUEST, "unknown": True}
        response = client.post("/api/v1/runs", json=invalid)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"
        invalid = {**REQUEST, "retrieval": {**REQUEST["retrieval"], "top_k": 5}}
        assert client.post("/api/v1/runs", json=invalid).status_code == 422
        invalid = {**REQUEST, "paper_limit": True}
        assert client.post("/api/v1/runs", json=invalid).status_code == 422
        assert client.post("/api/v1/runs", content="{}", headers={"Content-Type": "text/plain"}).status_code == 422
        assert client.post("/api/v1/runs", content=b" " * (16 * 1024 + 1), headers={"Content-Type": "application/json"}).status_code == 422
        missing = client.get("/api/v1/runs/00000000-0000-4000-8000-000000000000")
        assert missing.json() == {
            "error": {"code": "run_not_found", "message": "The requested run was not found.", "details": {}}
        }


def test_queue_capacity_and_api_responsiveness(tmp_path):
    runner = BlockingRunner()
    with _client(tmp_path, runner, capacity=1) as client:
        first = client.post("/api/v1/runs", json=REQUEST)
        assert runner.started.wait(timeout=2)
        started = time.monotonic()
        detail = client.get(first.headers["location"])
        assert time.monotonic() - started < 1
        assert detail.json()["status"] == "running"
        assert detail.headers["retry-after"] == "2"
        second = client.post("/api/v1/runs", json=REQUEST)
        assert second.status_code == 503
        assert second.json()["error"]["code"] == "queue_full"
        runner.release.set()
        terminal = _wait_terminal(client, first.json()["id"])
        assert terminal["status"] == "failed"
        assert "secret-canary" not in json.dumps(terminal)


def test_download_allowlist_rejects_private_and_traversal_names(tmp_path):
    runner = SuccessfulRunner()
    with _client(tmp_path, runner) as client:
        run_id = client.post("/api/v1/runs", json=REQUEST).json()["id"]
        _wait_terminal(client, run_id)
        for name in ("traces.jsonl", ".env", "paper.pdf", "..%2F.env", "%2e%2e%5c.env"):
            response = client.get(f"/api/v1/runs/{run_id}/artifacts/{name}")
            assert response.status_code == 404, name
            assert response.json()["error"]["code"] == "artifact_not_found"


def test_all_allowlisted_artifacts_download_with_canonical_headers(tmp_path):
    runner = SuccessfulRunner()
    with _client(tmp_path, runner) as client:
        run_id = client.post("/api/v1/runs", json=REQUEST).json()["id"]
        detail = _wait_terminal(client, run_id)
        assert set(detail["available_artifacts"]) == {
            "papers.json", "documents.json", "evidence.json", "analyses.json",
            "report.json", "report.md", "run_manifest.json", "logs.jsonl",
        }
        for name in detail["available_artifacts"]:
            response = client.get(f"/api/v1/runs/{run_id}/artifacts/{name}")
            assert response.status_code == 200, name
            assert f'filename="{name}"' in response.headers["content-disposition"]
            assert response.headers["x-content-type-options"] == "nosniff"


def test_list_degraded_run_and_bundled_demo_vertical_read(tmp_path):
    calls = 0

    def should_not_run(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("bundled demo must not execute a pipeline")

    with _client(tmp_path, should_not_run) as client:
        listing = client.get("/api/v1/runs?limit=1")
        assert listing.status_code == 200
        assert listing.json()["items"][0]["id"] == DEMO_API_ID
        detail = client.get(f"/api/v1/runs/{DEMO_API_ID}").json()
        assert detail["status"] == "completed_with_degradation"
        assert detail["demo"] is True and detail["origin"] == "bundled_demo"
        assert "retry-after" not in client.get(f"/api/v1/runs/{DEMO_API_ID}").headers
        report = client.get(f"/api/v1/runs/{DEMO_API_ID}/report")
        assert report.status_code == 200
        papers = client.get(f"/api/v1/runs/{DEMO_API_ID}/papers").json()["items"]
        assert len(papers) == 2
        evidence = client.get(f"/api/v1/runs/{DEMO_API_ID}/evidence").json()["items"]
        encoded = quote(evidence[0]["evidence_id"], safe="")
        assert client.get(f"/api/v1/runs/{DEMO_API_ID}/evidence/{encoded}").status_code == 200
        assert calls == 0


def test_origin_boundary_and_security_headers(tmp_path):
    with _client(tmp_path, SuccessfulRunner()) as client:
        blocked = client.get("/api/v1/runs", headers={"Origin": "https://evil.example"})
        assert blocked.status_code == 403
        assert blocked.json()["error"]["code"] == "origin_not_allowed"
        allowed = client.get("/api/v1/runs", headers={"Origin": "http://testserver"})
        assert allowed.status_code == 200
        assert "frame-ancestors 'none'" in allowed.headers["content-security-policy"]
        assert allowed.headers["x-frame-options"] == "DENY"
    web_dist = tmp_path / "web-dist"
    web_dist.mkdir()
    (web_dist / "index.html").write_text("<title>MOMO Scholar</title>", encoding="utf-8")
    app = create_app(
        state_root=tmp_path / "static-state", output_root=tmp_path / "static-outputs",
        web_dist=web_dist, runner=SuccessfulRunner(), settings_loader=_settings,
    )
    with TestClient(app) as client:
        home = client.get("/")
        assert home.status_code == 200
        assert "MOMO Scholar" in home.text
        deep_link = client.get(f"/runs/{DEMO_API_ID}/report")
        assert deep_link.status_code == 200
        missing_api = client.get("/api/v1/not-a-route")
        assert missing_api.status_code == 404
        assert missing_api.json()["error"]["code"] == "run_not_found"


def test_terminal_manifest_repairs_stale_registry_projection(tmp_path):
    runner = SuccessfulRunner()
    app = create_app(
        state_root=tmp_path / "state", output_root=tmp_path / "outputs",
        runner=runner, settings_loader=_settings,
    )
    with TestClient(app) as client:
        run_id = client.post("/api/v1/runs", json=REQUEST).json()["id"]
        _wait_terminal(client, run_id)
        app.state.run_service.registry._update(run_id, status="running", phase="analysis", finished_at=None)
        detail = client.get(f"/api/v1/runs/{run_id}").json()
        assert detail["status"] == "completed"
        assert detail["phase"] == "terminal"


def test_corrupt_evidence_returns_sanitized_conflict(tmp_path):
    runner = SuccessfulRunner()
    with _client(tmp_path, runner) as client:
        run_id = client.post("/api/v1/runs", json=REQUEST).json()["id"]
        detail = _wait_terminal(client, run_id)
        path = tmp_path / "outputs" / detail["artifact_run_id"] / "evidence.json"
        path.write_text("{secret-canary", encoding="utf-8")
        response = client.get(f"/api/v1/runs/{run_id}/evidence")
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "artifact_corrupt"
        assert "secret-canary" not in response.text
