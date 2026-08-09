import subprocess
from pathlib import Path

import pytest

from paper_agent.techscout.errors import FailureCode
from paper_agent.techscout.models import Candidate, PocPlan
from paper_agent.techscout.sandbox.compiler import PocCompiler
from paper_agent.techscout.sandbox.recipes import UnsupportedRecipeError
from paper_agent.techscout.sandbox.runner import DockerCliRunner, FakeSandboxRunner
from paper_agent.techscout.sandbox.types import (
    CompilationDisposition,
    ExecutionStatus,
    PocStage,
    SandboxLimits,
    SandboxResult,
)


def _candidate(name: str = "Qdrant Local", package: str = "qdrant-client") -> Candidate:
    return Candidate(
        candidate_id="candidate:qdrant-client",
        name=name,
        package_name=package,
        resolved_version="1.15.1",
    )


def _plan(recipe_id: str | None = "recipe:qdrant-local@1", trusted: bool = True) -> PocPlan:
    return PocPlan(
        poc_plan_id="poc-plan:qdrant:1",
        candidate_id="candidate:qdrant-client",
        recipe_id=recipe_id,
        trusted=trusted,
        checks=("import", "persistence", "upsert", "query", "filter"),
    )


def test_compiler_emits_only_reviewed_explicit_argv() -> None:
    compiler = PocCompiler()

    install = compiler.compile(_plan(), _candidate(), PocStage.INSTALL)
    test = compiler.compile(_plan(), _candidate(), PocStage.TEST)

    assert install.argv == (
        "python",
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
        "--target",
        "/tmp/techscout-site",
        "qdrant-client==1.15.1",
    )
    assert install.network_access.value == "install_only"
    assert test.argv == ("python", "/opt/techscout/recipes/qdrant_local.py")
    assert test.network_access.value == "none"


@pytest.mark.parametrize(
    ("plan", "candidate"),
    (
        (_plan("recipe:pgvector@1"), _candidate("pgvector", "pgvector")),
        (_plan(None, trusted=False), _candidate()),
        (_plan(), _candidate("Qdrant Local", "chromadb")),
        (
            PocPlan(
                poc_plan_id="poc-plan:qdrant:1",
                candidate_id="candidate:qdrant-client",
                recipe_id="recipe:qdrant-local@1",
                trusted=True,
                checks=("query; destructive-command",),
            ),
            _candidate(),
        ),
    ),
)
def test_unknown_or_mismatched_recipe_never_compiles(
    plan: PocPlan,
    candidate: Candidate,
) -> None:
    with pytest.raises(UnsupportedRecipeError):
        PocCompiler().compile(plan, candidate, PocStage.TEST)

    decision = PocCompiler().compile_or_research_only(plan, candidate, PocStage.TEST)
    assert decision.disposition is CompilationDisposition.RESEARCH_ONLY
    assert decision.command is None
    assert decision.failure_code is FailureCode.POC_RECIPE_UNSUPPORTED


def test_docker_argv_applies_resource_mount_and_network_boundaries(tmp_path: Path) -> None:
    run_workspace = tmp_path / "run-001"
    run_workspace.mkdir()
    runner = DockerCliRunner(
        tmp_path,
        limits=SandboxLimits(
            cpus=0.5,
            memory="256m",
            pids=32,
            disk="128m",
            tmpfs="32m",
            timeout_seconds=5,
            output_bytes=2048,
        ),
    )
    command = PocCompiler().compile(_plan(), _candidate(), PocStage.TEST)

    argv = runner.docker_argv(command, run_workspace)

    assert argv[:3] == ["docker", "run", "--rm"]
    assert argv[argv.index("--cpus") + 1] == "0.5"
    assert argv[argv.index("--memory") + 1] == "256m"
    assert argv[argv.index("--pids-limit") + 1] == "32"
    assert argv[argv.index("--storage-opt") + 1] == "size=128m"
    assert argv[argv.index("--network") + 1] == "none"
    assert argv[argv.index("--workdir") + 1] == "/workspace"
    mount = argv[argv.index("--mount") + 1]
    assert str(run_workspace.resolve()) in mount
    assert "target=/workspace" in mount
    assert argv[-len(command.argv) :] == list(command.argv)
    assert [argv[index + 1] for index, value in enumerate(argv) if value == "--env"] == [
        "HOME=/tmp"
    ]

    install = PocCompiler().compile(_plan(), _candidate(), PocStage.INSTALL)
    install_argv = runner.docker_argv(install, run_workspace)
    assert install_argv[install_argv.index("--network") + 1] == "bridge"

    outside = tmp_path.parent / "outside-techscout-run"
    outside.mkdir(exist_ok=True)
    with pytest.raises(ValueError, match="inside the configured workspace root"):
        runner.docker_argv(command, outside)


def test_runner_invokes_subprocess_with_timeout_and_no_shell(monkeypatch, tmp_path: Path) -> None:
    run_workspace = tmp_path / "run-001"
    run_workspace.mkdir()
    command = PocCompiler().compile(_plan(), _candidate(), PocStage.TEST)
    captured: dict[str, object] = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = DockerCliRunner(tmp_path).run(command, run_workspace)

    assert result.status is ExecutionStatus.SUCCEEDED
    assert captured["kwargs"] == {
        "capture_output": True,
        "text": True,
        "timeout": 60.0,
        "check": False,
    }
    assert isinstance(captured["argv"], list)


def test_timeout_and_nonzero_exit_are_bounded_structured_results(
    monkeypatch,
    tmp_path: Path,
) -> None:
    run_workspace = tmp_path / "run-001"
    run_workspace.mkdir()
    command = PocCompiler().compile(_plan(), _candidate(), PocStage.TEST)
    runner = DockerCliRunner(tmp_path, limits=SandboxLimits(output_bytes=1024))

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 60, output="x" * 3000, stderr="late")

    monkeypatch.setattr(subprocess, "run", timeout)
    timed_out = runner.run(command, run_workspace)
    assert timed_out.status is ExecutionStatus.TIMED_OUT
    assert timed_out.failure_code is FailureCode.POC_TIMEOUT
    assert len(timed_out.stdout.encode()) <= 1024

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 7, "", "failed"),
    )
    failed = runner.run(command, run_workspace)
    assert failed.status is ExecutionStatus.FAILED
    assert failed.exit_code == 7
    assert failed.failure_code is FailureCode.POC_NONZERO_EXIT


def test_fake_runner_is_deterministic_fifo(tmp_path: Path) -> None:
    command = PocCompiler().compile(_plan(), _candidate(), PocStage.TEST)
    fake = FakeSandboxRunner()
    for exit_code in (1, 0):
        fake.queue(
            SandboxResult(
                command=command,
                status=ExecutionStatus.FAILED if exit_code else ExecutionStatus.SUCCEEDED,
                exit_code=exit_code,
                timed_out=False,
                duration_ms=10,
                failure_code=FailureCode.POC_NONZERO_EXIT if exit_code else None,
            )
        )

    assert fake.run(command, tmp_path).exit_code == 1
    assert fake.run(command, tmp_path).exit_code == 0
    assert len(fake.calls) == 2
