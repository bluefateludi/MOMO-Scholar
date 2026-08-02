from paper_agent.config import Settings
from paper_agent.web.api_models import CreateRunRequest
from paper_agent.web.artifacts import ArtifactReader
from paper_agent.web.execution import SingleRunExecutor
from paper_agent.web.registry import RunRegistry


def test_startup_marks_unfinished_rows_interrupted(tmp_path):
    registry = RunRegistry(tmp_path / "state" / "registry.sqlite3")
    request = CreateRunRequest.model_validate({
        "question": "unfinished research run", "paper_limit": 1,
        "content_mode": "abstract_only",
        "retrieval": {"mode": "lexical", "candidate_k": 2, "top_k": 1, "rrf_k": 60, "analysis_evidence_per_paper": 1},
    })
    run_id = "00000000-0000-4000-8000-000000000001"
    registry.admit(run_id, request, 4)
    executor = SingleRunExecutor(
        registry, ArtifactReader(tmp_path / "outputs"), tmp_path / "outputs",
        runner=lambda *args, **kwargs: None,
        settings_loader=lambda: Settings(dashscope_api_key="offline"),
    )
    executor.start()
    try:
        row = registry.get(run_id)
        assert row.status == "interrupted"
        assert row.phase == "terminal"
        assert row.error.model_dump() == {
            "stage": "initializing", "code": "web_process_interrupted",
            "paper_id": None,
        }
    finally:
        executor.close()


def test_second_executor_fails_closed_on_same_registry(tmp_path):
    registry = RunRegistry(tmp_path / "state" / "registry.sqlite3")
    artifacts = ArtifactReader(tmp_path / "outputs")
    kwargs = {
        "runner": lambda *args, **values: None,
        "settings_loader": lambda: Settings(dashscope_api_key="offline"),
    }
    first = SingleRunExecutor(registry, artifacts, tmp_path / "outputs", **kwargs)
    second = SingleRunExecutor(registry, artifacts, tmp_path / "outputs", **kwargs)
    first.start()
    try:
        try:
            second.start()
        except OSError:
            pass
        else:
            raise AssertionError("second executor unexpectedly acquired the lock")
    finally:
        first.close()
