import os
from pathlib import Path

import pytest

from paper_agent.techscout.models import Candidate, PocPlan
from paper_agent.techscout.sandbox.compiler import PocCompiler
from paper_agent.techscout.sandbox.runner import DockerCliRunner
from paper_agent.techscout.sandbox.types import ExecutionStatus, PocStage


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
def test_reviewed_recipe_runs_with_no_network(
    candidate: Candidate,
    recipe_id: str,
    tmp_path: Path,
) -> None:
    plan = PocPlan(
        poc_plan_id=f"poc-plan:{candidate.candidate_id}:smoke",
        candidate_id=candidate.candidate_id,
        recipe_id=recipe_id,
        trusted=True,
        checks=("import", "persistence", "upsert", "query", "filter"),
    )
    command = PocCompiler().compile(plan, candidate, PocStage.TEST)
    runner = DockerCliRunner(tmp_path)

    assert command.network_access.value == "none"
    result = runner.run(command, tmp_path)

    assert result.status is ExecutionStatus.SUCCEEDED, result.stderr
