from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from paper_agent.evidence.hybrid import HybridEvidenceRetriever
from paper_agent.evidence.retriever import LexicalCandidateSource
from paper_agent.techscout.context import ContextEngine, HybridContextRetriever
from paper_agent.techscout.errors import FailureCode
from paper_agent.techscout.models import CacheStatus, PocArtifact, PocResult, PocStatus
from paper_agent.techscout.research import LiveEvidenceResearchService
from paper_agent.techscout.sandbox.service import PocStageAttempt
from paper_agent.techscout.sandbox.types import PocStage
from paper_agent.techscout.tools.contracts import (
    FetchOutput,
    GitHubInspectOutput,
    SearchHit,
    SearchOutput,
    SourceProvenance,
)
from paper_agent.web.app import create_app
from paper_agent.web.techscout_execution import VerifiedStageServices
from paper_agent.web.techscout_api_models import TechScoutCreateRunRequest
from paper_agent.web.techscout_execution import TechScoutRunEngine


NOW = datetime(2026, 8, 12, tzinfo=timezone.utc)


def _provenance(cache: bool = False) -> SourceProvenance:
    return SourceProvenance(
        provider="offline-live-fake",
        retrieved_at=NOW,
        snapshot_sha256=hashlib.sha256(b"bounded source").hexdigest(),
        cache_status=CacheStatus.STALE if cache else CacheStatus.MISS,
        cache_fallback=cache,
    )


class _Search:
    def __init__(self, cache: bool = False) -> None:
        self.cache = cache

    def search(self, request):
        domain = request.domains[0]
        return SearchOutput(
            query=request.query,
            candidate_id=request.candidate_id,
            results=(SearchHit(title="Official docs", url=f"https://{domain}/local", snippet="persistence metadata filtering"),),
            provenance=_provenance(self.cache),
        )


class _Fetch:
    def __init__(self, cache: bool = False) -> None:
        self.cache = cache

    def fetch(self, request):
        content = "Python 3.11 collection create upsert query metadata filter persistence reopen"
        return FetchOutput(
            url=request.url, candidate_id=request.candidate_id,
            media_type="text/plain", content=content, size_bytes=len(content),
            provenance=_provenance(self.cache),
        )


class _GitHub:
    def __init__(self, cache: bool = False) -> None:
        self.cache = cache

    def inspect_repository(self, request):
        return GitHubInspectOutput(
            candidate_id=request.candidate_id,
            repository_url=request.repository_url,
            default_branch="main", description="bounded repository snapshot",
            stars=1, archived=False,
            readme_excerpt="Python 3.11 persistence metadata filtering",
            releases=(), issues=(), provenance=_provenance(self.cache),
        )


class _Poc:
    def __init__(self, outcome: str = "passed") -> None:
        self.outcome = outcome
        self.execute_calls: list[str] = []
        self.rerun_calls: list[PocStage] = []

    def execute(self, plan, candidate, *, run_workspace, attempt=1):
        self.execute_calls.append(candidate.candidate_id)
        if not plan.trusted:
            return PocResult(
                poc_result_id=f"poc-result:{candidate.candidate_id.split(':')[-1]}:research",
                poc_plan_id=plan.poc_plan_id, candidate_id=candidate.candidate_id,
                status=PocStatus.RESEARCH_ONLY, timed_out=False, duration_ms=0,
                failure_code=FailureCode.POC_RECIPE_UNSUPPORTED,
            )
        if self.outcome == "unavailable":
            return PocResult(
                poc_result_id=f"poc-result:{candidate.candidate_id.split(':')[-1]}:unavailable",
                poc_plan_id=plan.poc_plan_id, candidate_id=candidate.candidate_id,
                status=PocStatus.FAILED, timed_out=False, duration_ms=2,
                failure_code=FailureCode.TOOL_UNAVAILABLE,
            )
        status = PocStatus.FAILED if self.outcome == "recover" and not self.rerun_calls else PocStatus.PASSED
        resolved = "1.0.15" if "chroma" in candidate.candidate_id else "1.15.1"
        return PocResult(
            poc_result_id=f"poc-result:{candidate.candidate_id.split(':')[-1]}:1",
            poc_plan_id=plan.poc_plan_id, candidate_id=candidate.candidate_id,
            status=status, resolved_version=resolved if status is PocStatus.PASSED else None,
            exit_code=0 if status is PocStatus.PASSED else 1,
            timed_out=False, duration_ms=4,
            artifacts=(PocArtifact(artifact_id=f"artifact:{candidate.candidate_id.split(':')[-1]}:poc", kind="fake-real-docker", sha256="a" * 64, size_bytes=64),),
            failure_code=None if status is PocStatus.PASSED else FailureCode.DEPENDENCY_CONFLICT,
        )

    def rerun_stage(self, plan, candidate, *, run_workspace, stage):
        self.rerun_calls.append(stage)
        return PocStageAttempt(
            poc_plan_id=plan.poc_plan_id, candidate_id=candidate.candidate_id,
            recipe_id=plan.recipe_id, stage=stage, attempt=2,
            status=PocStatus.PASSED, exit_code=0, timed_out=False, duration_ms=3,
            artifact=PocArtifact(artifact_id=f"artifact:{candidate.candidate_id.split(':')[-1]}:recovery", kind="fake-real-docker-stage", sha256="b" * 64, size_bytes=64),
        )


def _factory(*, cache: bool = False, github_cache: bool | None = None, poc: _Poc | None = None):
    poc = poc or _Poc()
    retrieval = HybridEvidenceRetriever(
        lexical_source=LexicalCandidateSource(), vector_source=None,
        requested_mode="lexical", candidate_k=8, top_k=8, rrf_k=60,
    )
    context_engine = ContextEngine(HybridContextRetriever(retrieval))
    research = LiveEvidenceResearchService(
        search=_Search(cache), fetch=_Fetch(cache),
        github=_GitHub(cache if github_cache is None else github_cache),
        context_engine=context_engine,
    )
    return lambda **kwargs: VerifiedStageServices(
        research_service=research, context_engine=context_engine, poc_service=poc, **kwargs
    )


def _body(candidates=None):
    return {
        "question": "Choose a Python 3.11 local RAG vector store.",
        "project_context": "Single-node local RAG",
        "environment": {"python_version": "3.11", "operating_system": "linux", "deployment": "local"},
        "hard_constraints": ["collection", "upsert query", "metadata filter", "persistence reopen"],
        "candidates": candidates or [{"name": "Chroma"}, {"name": "Qdrant Local"}],
        "mode": "verified",
    }


def _run(tmp_path: Path, factory, body=None):
    app = create_app(
        state_root=tmp_path / "state", output_root=tmp_path / "outputs",
        demo_root=None, web_dist=tmp_path / "missing", verified_services_factory=factory,
    )
    with TestClient(app) as client:
        created = client.post("/api/v2/runs", json=body or _body())
        run_id = created.json()["id"]
        for _ in range(400):
            detail = client.get(f"/api/v2/runs/{run_id}").json()
            if detail["status"] not in {"queued", "running"}:
                report = client.get(f"/api/v2/runs/{run_id}/report").json()
                evidence = client.get(f"/api/v2/runs/{run_id}/evidence").json()["items"]
                trace = client.get(f"/api/v2/runs/{run_id}/trace?limit=100").json()["items"]
                return detail, report, evidence, trace
            time.sleep(0.01)
    raise AssertionError("verified fake did not terminalize")


def test_verified_happy_path_is_live_and_poc_verified(tmp_path: Path) -> None:
    detail, report, evidence, _ = _run(tmp_path, _factory())
    assert detail["status"] == "completed"
    assert detail["synthetic"] is False
    assert {item["acquisition_state"] for item in evidence} == {"live"}
    assert all(item["verified"] for item in report["poc_results"])
    serialized = " ".join(item["label"] for item in _)
    assert str(tmp_path) not in serialized
    assert "raw provider body" not in serialized


def test_verified_budget_is_300_seconds_and_fast_budget_stays_120(tmp_path: Path) -> None:
    verified = TechScoutRunEngine._initial_state(
        "run:00000000-0000-4000-8000-000000000701",
        TechScoutCreateRunRequest.model_validate(_body()),
    )
    fast_body = _body()
    fast_body["mode"] = "fast"
    fast = TechScoutRunEngine._initial_state(
        "run:00000000-0000-4000-8000-000000000702",
        TechScoutCreateRunRequest.model_validate(fast_body),
    )
    assert 295 <= (verified.budget.deadline_at - datetime.now(timezone.utc)).total_seconds() <= 300
    assert 115 <= (fast.budget.deadline_at - datetime.now(timezone.utc)).total_seconds() <= 120


def test_cache_degradation_and_docker_unavailable_are_honest_terminal_results(tmp_path: Path) -> None:
    detail, report, evidence, _ = _run(tmp_path, _factory(cache=True))
    assert detail["status"] == "completed_with_limitations"
    assert report["verdict"] == "no_safe_winner"
    assert {item["acquisition_state"] for item in evidence} == {"cache"}

    detail, report, _, _ = _run(tmp_path / "docker", _factory(poc=_Poc("unavailable")))
    assert detail["status"] == "completed_with_limitations"
    assert "docker_unavailable" in report["limitations"]


def test_mixed_source_authority_does_not_promote_cached_evidence_to_live(tmp_path: Path) -> None:
    _, _, evidence, trace = _run(tmp_path, _factory(cache=True, github_cache=False))
    assert {item["acquisition_state"] for item in evidence} == {"cache"}
    research_labels = " ".join(
        item["label"] for item in trace if item["event_type"] == "tool"
    )
    assert "cache_state=cache" in research_labels
    assert "cache_state=live" in research_labels


def test_unsupported_candidate_is_research_only_and_recovery_repeats_one_poc_stage(tmp_path: Path) -> None:
    poc = _Poc()
    detail, report, _, _ = _run(tmp_path / "unsupported", _factory(poc=poc), _body([{"name": "pgvector"}]))
    assert detail["status"] == "completed_with_limitations"
    assert report["poc_results"][0]["status"] == "research_only"

    recovering = _Poc("recover")
    detail, _, _, trace = _run(tmp_path / "recovery", _factory(poc=recovering), _body([{"name": "Chroma"}]))
    assert detail["recovery"]["attempts_used"] == 1
    assert len(recovering.execute_calls) == 1
    assert len(recovering.rerun_calls) == 1
    assert any(item["event_type"] == "recovery" and "checkpoint=" in item["label"] for item in trace)


def test_non_hero_environment_never_runs_reviewed_recipe(tmp_path: Path) -> None:
    poc = _Poc()
    body = _body([{"name": "Chroma"}])
    body["environment"]["python_version"] = "3.12"
    detail, report, _, _ = _run(tmp_path, _factory(poc=poc), body)
    assert detail["status"] == "completed_with_limitations"
    assert report["poc_results"][0]["status"] == "research_only"
    assert poc.execute_calls == ["candidate:chroma"]


def test_one_recovery_transition_reruns_only_one_failed_candidate(tmp_path: Path) -> None:
    poc = _Poc("recover")
    detail, report, _, _ = _run(tmp_path, _factory(poc=poc))
    assert detail["recovery"]["attempts_used"] == 1
    assert len(poc.rerun_calls) == 1
    assert detail["status"] == "failed"
    assert "docker_unavailable" not in str(detail)
    assert "limitations" not in report


def test_cache_degradation_does_not_mask_exhausted_poc_failure(tmp_path: Path) -> None:
    detail, report, evidence, _ = _run(
        tmp_path,
        _factory(cache=True, poc=_Poc("recover")),
        _body([{"name": "Chroma"}]),
    )
    assert {item["acquisition_state"] for item in evidence} == {"cache"}
    assert detail["status"] == "failed"
    assert "limitations" not in report
