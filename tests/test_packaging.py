import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


def test_pyproject_uses_explicit_setuptools_package_discovery() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads(
        (repository_root / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert pyproject["tool"]["setuptools"]["packages"]["find"]["include"] == [
        "paper_agent",
        "paper_agent.*",
    ]
    assert pyproject["build-system"] == {
        "requires": ["setuptools>=61"],
        "build-backend": "setuptools.build_meta",
    }
    assert (
        "tomli>=2; python_version < '3.11'"
        in pyproject["project"]["optional-dependencies"]["dev"]
    )


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
        timeout=60,
    )

    diagnostics = (
        f"command: {' '.join(result.args)}\n"
        f"exit code: {result.returncode}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    assert result.returncode == 0, diagnostics
    wheels = sorted(wheel_dir.glob("*.whl"))
    assert len(wheels) == 1, (
        f"expected exactly one wheel, found {[wheel.name for wheel in wheels]}\n"
        f"{diagnostics}"
    )
    with zipfile.ZipFile(wheels[0]) as wheel:
        members = wheel.namelist()
    assert any(member.startswith("paper_agent/") for member in members)
    assert not any(member.startswith("outputs/") for member in members)
