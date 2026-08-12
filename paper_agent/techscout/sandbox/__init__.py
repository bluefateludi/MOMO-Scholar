"""Allowlisted PoC compilation and bounded Docker execution."""

from importlib import import_module
from typing import TYPE_CHECKING, Any

from paper_agent.techscout.sandbox.compiler import PocCompiler
from paper_agent.techscout.sandbox.recipes import RecipeRegistry
from paper_agent.techscout.sandbox.runner import DockerCliRunner, FakeSandboxRunner
from paper_agent.techscout.sandbox.types import (
    CompilationDisposition,
    CompilationResult,
    CompiledCommand,
    ExecutionStatus,
    InstallNetworkPolicy,
    PocStage,
    SandboxLimits,
    SandboxResult,
)

if TYPE_CHECKING:
    from paper_agent.techscout.sandbox.service import (
        PocStageAttempt,
        RealPocAdapter,
        RealPocService,
    )


_LAZY_SERVICE_EXPORTS = frozenset(
    {"PocStageAttempt", "RealPocAdapter", "RealPocService"}
)


def __getattr__(name: str) -> Any:
    if name not in _LAZY_SERVICE_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module("paper_agent.techscout.sandbox.service"), name)
    globals()[name] = value
    return value

__all__ = [
    "CompiledCommand",
    "CompilationDisposition",
    "CompilationResult",
    "DockerCliRunner",
    "ExecutionStatus",
    "FakeSandboxRunner",
    "InstallNetworkPolicy",
    "PocCompiler",
    "PocStage",
    "PocStageAttempt",
    "RecipeRegistry",
    "RealPocAdapter",
    "RealPocService",
    "SandboxLimits",
    "SandboxResult",
]
