from concurrent.futures import ThreadPoolExecutor

import pytest

from paper_agent.web.api_models import CreateRunRequest
from paper_agent.web.errors import WebError
from paper_agent.web.registry import RunRegistry


REQUEST = CreateRunRequest.model_validate({
    "question": "grounded literature review",
    "paper_limit": 1,
    "content_mode": "abstract_only",
    "retrieval": {
        "mode": "lexical", "candidate_k": 4, "top_k": 2, "rrf_k": 60,
        "analysis_evidence_per_paper": 1,
    },
})


def test_concurrent_admission_never_exceeds_capacity(tmp_path):
    registry = RunRegistry(tmp_path / "registry.sqlite3")

    def admit(index: int) -> bool:
        try:
            registry.admit(f"00000000-0000-4000-8000-{index:012d}", REQUEST, 2)
            return True
        except WebError as error:
            assert error.code == "queue_full"
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        accepted = list(pool.map(admit, range(8)))
    assert sum(accepted) == 2


def test_claim_is_atomic_and_oldest_only(tmp_path):
    registry = RunRegistry(tmp_path / "registry.sqlite3")
    registry.admit("00000000-0000-4000-8000-000000000001", REQUEST, 4)
    registry.admit("00000000-0000-4000-8000-000000000002", REQUEST, 4)

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: registry.claim_oldest(), range(2)))
    assert sum(item is not None for item in claims) == 1
    assert registry.get("00000000-0000-4000-8000-000000000001").status == "running"
    assert registry.get("00000000-0000-4000-8000-000000000002").status == "queued"


def test_artifact_id_rejects_paths(tmp_path):
    registry = RunRegistry(tmp_path / "registry.sqlite3")
    registry.admit("00000000-0000-4000-8000-000000000001", REQUEST, 4)
    with pytest.raises(ValueError):
        registry.set_artifact_id("00000000-0000-4000-8000-000000000001", "../secret")
