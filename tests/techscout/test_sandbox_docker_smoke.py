import os
from pathlib import Path

import pytest

from paper_agent.techscout.models import Candidate, PocPlan, PocStatus
from paper_agent.techscout.sandbox.runner import DockerCliRunner
from paper_agent.techscout.sandbox.service import RealPocService
from paper_agent.techscout.sandbox.types import InstallNetworkPolicy


pytestmark = pytest.mark.skipif(
    os.environ.get("TECHSCOUT_DOCKER_SMOKE") != "1",
    reason="set TECHSCOUT_DOCKER_SMOKE=1 after building the sandbox image",
)


@pytest.mark.parametrize(
    ("candidate", "recipe_id"),
    (
        (
            Candidate(
                candidate_id="candidate:chromadb",
                name="Chroma",
                package_name="chromadb",
            ),
            "recipe:chroma-local@1",
        ),
        (
            Candidate(
                candidate_id="candidate:qdrant-client",
                name="Qdrant Local",
                package_name="qdrant-client",
            ),
            "recipe:qdrant-local@1",
        ),
    ),
)
def test_real_poc_service_runs_reviewed_recipe_and_publishes_artifact(
    candidate: Candidate,
    recipe_id: str,
    tmp_path: Path,
) -> None:
    plan = PocPlan(
        poc_plan_id=f"poc-plan:{candidate.candidate_id}:smoke",
        candidate_id=candidate.candidate_id,
        recipe_id=recipe_id,
        trusted=True,
        checks=("import", "create", "persistence", "upsert", "query", "filter"),
    )
    runner = DockerCliRunner(
        tmp_path,
        install_network=InstallNetworkPolicy(
            docker_network=os.environ.get(
                "TECHSCOUT_INSTALL_NETWORK", "techscout-pypi-egress"
            ),
            allowed_destinations=("pypi.org", "files.pythonhosted.org"),
            egress_allowlist_enforced=True,
        ),
    )

    result = RealPocService(runner).execute(
        plan,
        candidate,
        run_workspace=tmp_path,
    )

    assert result.status is PocStatus.PASSED
    assert result.artifacts
