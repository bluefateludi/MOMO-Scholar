import subprocess
import sys
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "module_order",
    (
        (
            "paper_agent.techscout.sandbox.types",
            "paper_agent.techscout.recovery.classifier",
        ),
        (
            "paper_agent.techscout.recovery.classifier",
            "paper_agent.techscout.sandbox.types",
        ),
    ),
)
def test_sandbox_boundary_imports_do_not_load_service_or_optional_dependencies(
    module_order: tuple[str, str],
) -> None:
    imports = "\n".join(f"import {module}" for module in module_order)
    script = f"""
import importlib.abc
import sys

class BoundaryBlocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "paper_agent.techscout.sandbox.service":
            raise ModuleNotFoundError("sandbox service crossed the import boundary")
        if fullname == "dotenv" or fullname.startswith("dotenv."):
            raise ModuleNotFoundError("optional dotenv dependency crossed the import boundary")
        return None

sys.meta_path.insert(0, BoundaryBlocker())
{imports}
assert "paper_agent.techscout.sandbox.service" not in sys.modules
assert not any(name == "dotenv" or name.startswith("dotenv.") for name in sys.modules)
"""

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_sandbox_service_package_exports_remain_lazy_and_compatible() -> None:
    script = """
import sys
import paper_agent.techscout.sandbox as sandbox

assert "paper_agent.techscout.sandbox.service" not in sys.modules
from paper_agent.techscout.sandbox import PocStageAttempt, RealPocAdapter, RealPocService
from paper_agent.techscout.sandbox.service import (
    PocStageAttempt as DirectPocStageAttempt,
    RealPocAdapter as DirectRealPocAdapter,
    RealPocService as DirectRealPocService,
)
assert PocStageAttempt is DirectPocStageAttempt
assert RealPocAdapter is DirectRealPocAdapter
assert RealPocService is DirectRealPocService
assert set(("PocStageAttempt", "RealPocAdapter", "RealPocService")) <= set(sandbox.__all__)
"""

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
