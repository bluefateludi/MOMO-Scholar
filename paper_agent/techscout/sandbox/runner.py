"""Docker CLI runner with explicit argv and deterministic fake."""

import subprocess
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Protocol

from paper_agent.techscout.errors import FailureCode
from paper_agent.techscout.sandbox.types import (
    CompiledCommand,
    ExecutionStatus,
    NetworkAccess,
    PocStage,
    SandboxLimits,
    SandboxResult,
)


class SandboxRunner(Protocol):
    def run(self, command: CompiledCommand, run_workspace: Path) -> SandboxResult: ...


class DockerCliRunner:
    def __init__(
        self,
        workspace_root: Path,
        limits: SandboxLimits | None = None,
        *,
        docker_executable: str = "docker",
        install_network: str = "bridge",
    ) -> None:
        self._workspace_root = workspace_root.resolve(strict=True)
        self._limits = limits or SandboxLimits()
        self._docker_executable = docker_executable
        if install_network not in {"bridge", "none"}:
            raise ValueError("install network must be bridge or none")
        self._install_network = install_network

    def docker_argv(self, command: CompiledCommand, run_workspace: Path) -> list[str]:
        workspace = run_workspace.resolve(strict=True)
        if workspace != self._workspace_root and self._workspace_root not in workspace.parents:
            raise ValueError("run workspace must stay inside the configured workspace root")

        network = "none"
        if (
            command.stage is PocStage.INSTALL
            and command.network_access is NetworkAccess.INSTALL_ONLY
        ):
            network = self._install_network

        return [
            self._docker_executable,
            "run",
            "--rm",
            "--init",
            "--cpus",
            str(self._limits.cpus),
            "--memory",
            self._limits.memory,
            "--pids-limit",
            str(self._limits.pids),
            "--storage-opt",
            f"size={self._limits.disk}",
            "--network",
            network,
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--tmpfs",
            f"/tmp:rw,noexec,nosuid,size={self._limits.tmpfs}",
            "--workdir",
            "/workspace",
            "--mount",
            f"type=bind,source={workspace},target=/workspace",
            "--env",
            "HOME=/tmp",
            command.image,
            *command.argv,
        ]

    def run(self, command: CompiledCommand, run_workspace: Path) -> SandboxResult:
        argv = self.docker_argv(command, run_workspace)
        started = time.monotonic()
        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=self._limits.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return SandboxResult(
                command=command,
                status=ExecutionStatus.TIMED_OUT,
                exit_code=None,
                timed_out=True,
                duration_ms=_duration_ms(started),
                stdout=_bounded_text(exc.stdout, self._limits.output_bytes),
                stderr=_bounded_text(exc.stderr, self._limits.output_bytes),
                failure_code=FailureCode.POC_TIMEOUT,
            )
        except OSError as exc:
            return SandboxResult(
                command=command,
                status=ExecutionStatus.UNAVAILABLE,
                exit_code=None,
                timed_out=False,
                duration_ms=_duration_ms(started),
                stderr=_bounded_text(str(exc), self._limits.output_bytes),
                failure_code=FailureCode.TOOL_UNAVAILABLE,
            )

        succeeded = completed.returncode == 0
        return SandboxResult(
            command=command,
            status=(ExecutionStatus.SUCCEEDED if succeeded else ExecutionStatus.FAILED),
            exit_code=completed.returncode,
            timed_out=False,
            duration_ms=_duration_ms(started),
            stdout=_bounded_text(completed.stdout, self._limits.output_bytes),
            stderr=_bounded_text(completed.stderr, self._limits.output_bytes),
            failure_code=None if succeeded else FailureCode.POC_NONZERO_EXIT,
        )


class FakeSandboxRunner:
    """FIFO deterministic runner used by ordinary tests and the Agent fake runtime."""

    def __init__(self) -> None:
        self._results: dict[tuple[str, PocStage], deque[SandboxResult]] = defaultdict(deque)
        self.calls: list[tuple[CompiledCommand, Path]] = []

    def queue(self, result: SandboxResult) -> None:
        key = (result.command.recipe_id, result.command.stage)
        self._results[key].append(result)

    def run(self, command: CompiledCommand, run_workspace: Path) -> SandboxResult:
        self.calls.append((command, run_workspace))
        key = (command.recipe_id, command.stage)
        if not self._results[key]:
            raise LookupError(f"no fake result queued for {key}")
        result = self._results[key].popleft()
        if result.command != command:
            raise ValueError("queued fake result does not match compiled command")
        return result


def _duration_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def _bounded_text(value: str | bytes | None, maximum: int) -> str:
    if value is None:
        return ""
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
    encoded = text.encode("utf-8")
    if len(encoded) <= maximum:
        return text
    suffix = "\n[output truncated]"
    budget = max(0, maximum - len(suffix.encode("utf-8")))
    return encoded[:budget].decode("utf-8", errors="ignore") + suffix
