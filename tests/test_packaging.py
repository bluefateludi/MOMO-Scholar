import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


def test_wheel_excludes_runtime_outputs_directory(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    project = tmp_path / "project"
    wheel_dir = tmp_path / "wheels"
    project.mkdir()
    wheel_dir.mkdir()

    shutil.copy2(repository_root / "pyproject.toml", project / "pyproject.toml")
    shutil.copytree(repository_root / "paper_agent", project / "paper_agent")
    outputs = project / "outputs"
    outputs.mkdir()
    (outputs / "example.txt").write_text("runtime output", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            str(project),
            "--no-deps",
            "--no-build-isolation",
            "--no-index",
            "--disable-pip-version-check",
            "--wheel-dir",
            str(wheel_dir),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    wheels = list(wheel_dir.glob("*.whl"))
    assert len(wheels) == 1
    with zipfile.ZipFile(wheels[0]) as wheel:
        members = wheel.namelist()
    assert any(member.startswith("paper_agent/") for member in members)
    assert not any(member.startswith("outputs/") for member in members)
