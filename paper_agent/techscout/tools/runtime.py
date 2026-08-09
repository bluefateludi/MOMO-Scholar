from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from contextlib import AsyncExitStack
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from paper_agent.techscout.errors import FailureCode
from paper_agent.techscout.models import (
    CacheStatus,
    SkillSpec,
    ToolCall,
    ToolResult,
    ToolStatus,
)
from paper_agent.techscout.runtime_skills import SkillRegistry

from .contracts import TOOL_INPUT_MODELS, TOOL_OUTPUT_MODELS


class ToolRuntime(Protocol):
    async def discover_tools(self) -> tuple[str, ...]: ...

    async def invoke(self, call: ToolCall) -> ToolResult: ...


class FakeToolRuntime:
    """Deterministic typed runtime for graph and service tests.

    Script values may be output models, JSON-compatible dictionaries, or exceptions.
    Both the request and scripted response cross the same schemas as the real runtime.
    """

    def __init__(
        self,
        scripts: Mapping[str, Iterable[BaseModel | dict[str, Any] | Exception]],
    ) -> None:
        self._scripts = {
            name: deque(values) for name, values in scripts.items()
        }
        unknown = set(self._scripts) - set(TOOL_INPUT_MODELS)
        if unknown:
            raise ValueError(f"unknown fake tools: {sorted(unknown)}")
        self.calls: list[ToolCall] = []

    async def discover_tools(self) -> tuple[str, ...]:
        return tuple(sorted(self._scripts))

    async def invoke(self, call: ToolCall) -> ToolResult:
        self.calls.append(call)
        try:
            input_model = TOOL_INPUT_MODELS[call.tool_name]
            input_model.model_validate_json(_json_bytes(call.arguments))
        except (KeyError, ValidationError):
            return _failure(call, 0.0, FailureCode.MALFORMED_MCP_RESPONSE, latency_ms=0)
        queue = self._scripts.get(call.tool_name)
        if not queue:
            return _failure(call, 0.0, FailureCode.TOOL_UNAVAILABLE, latency_ms=0)
        scripted = queue.popleft()
        if isinstance(scripted, Exception):
            code = (
                FailureCode.TOOL_TIMEOUT
                if isinstance(scripted, TimeoutError)
                else FailureCode.TOOL_UNAVAILABLE
            )
            return _failure(call, 0.0, code, latency_ms=0)
        try:
            output_model = TOOL_OUTPUT_MODELS[call.tool_name]
            if isinstance(scripted, BaseModel):
                payload = scripted.model_dump(mode="json")
            else:
                payload = scripted
            output = output_model.model_validate_json(_json_bytes(payload))
        except (KeyError, ValidationError, TypeError, ValueError):
            return _failure(call, 0.0, FailureCode.MALFORMED_MCP_RESPONSE, latency_ms=0)
        return ToolResult(
            tool_call_id=call.tool_call_id,
            status=ToolStatus.SUCCEEDED,
            output=output.model_dump(mode="json"),
            latency_ms=0,
            cache_status=_cache_status(output),
        )


class PolicyToolRuntime:
    """Fail-closed intersection of a Skill allowlist and local tool policy."""

    def __init__(
        self,
        *,
        delegate: ToolRuntime,
        skills: SkillRegistry,
        local_allowlist: Iterable[str],
    ) -> None:
        self._delegate = delegate
        self._skills = skills
        self._local_allowlist = frozenset(local_allowlist)
        unknown = self._local_allowlist - set(TOOL_INPUT_MODELS)
        if unknown:
            raise ValueError(f"local policy contains unknown tools: {sorted(unknown)}")

    async def discover_tools(self) -> tuple[str, ...]:
        discovered = await self._delegate.discover_tools()
        return tuple(name for name in discovered if name in self._local_allowlist)

    async def invoke(self, call: ToolCall) -> ToolResult:
        try:
            skill: SkillSpec = self._skills.get(call.skill_id)
        except KeyError:
            return _denied(call)
        if (
            call.tool_name not in skill.allowed_tools
            or call.tool_name not in self._local_allowlist
        ):
            return _denied(call)
        discovered = await self._delegate.discover_tools()
        if call.tool_name not in discovered:
            return _failure(call, time.monotonic(), FailureCode.TOOL_UNAVAILABLE)
        return await self._delegate.invoke(call)


class StdioMcpRuntime:
    """Official MCP SDK v2 stdio client with run-scoped discovery caching."""

    def __init__(
        self,
        *,
        command: str,
        args: Iterable[str],
        env: Mapping[str, str] | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("MCP timeout must be positive")
        self._command = command
        self._args = tuple(args)
        self._env = dict(env) if env is not None else None
        self._timeout = timeout_seconds
        self._stack: AsyncExitStack | None = None
        self._client: Any = None
        self._discovered: tuple[str, ...] | None = None

    async def __aenter__(self) -> "StdioMcpRuntime":
        try:
            from mcp import Client, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as exc:
            raise RuntimeError("MCP Python SDK v2 is required") from exc
        stack = AsyncExitStack()
        try:
            params = StdioServerParameters(
                command=self._command,
                args=list(self._args),
                env=self._env,
            )
            client = await asyncio.wait_for(
                stack.enter_async_context(
                    Client(
                        stdio_client(params),
                        read_timeout_seconds=self._timeout,
                    )
                ),
                timeout=self._timeout,
            )
        except BaseException:
            await stack.aclose()
            raise
        self._stack = stack
        self._client = client
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = None
        self._client = None
        self._discovered = None

    async def discover_tools(self) -> tuple[str, ...]:
        self._require_client()
        if self._discovered is None:
            response = await asyncio.wait_for(
                self._client.list_tools(), timeout=self._timeout
            )
            self._discovered = tuple(sorted(tool.name for tool in response.tools))
        return self._discovered

    async def invoke(self, call: ToolCall) -> ToolResult:
        self._require_client()
        started = time.monotonic()
        try:
            request = TOOL_INPUT_MODELS[call.tool_name].model_validate_json(
                _json_bytes(call.arguments)
            )
            result = await asyncio.wait_for(
                self._client.call_tool(
                    call.tool_name, arguments=request.model_dump(mode="json")
                ),
                timeout=self._timeout,
            )
            if result.is_error or not isinstance(result.structured_content, dict):
                return _failure(call, started, FailureCode.MALFORMED_MCP_RESPONSE)
            output = TOOL_OUTPUT_MODELS[call.tool_name].model_validate_json(
                _json_bytes(result.structured_content)
            )
        except asyncio.TimeoutError:
            return _failure(call, started, FailureCode.TOOL_TIMEOUT)
        except (KeyError, ValidationError, TypeError, ValueError):
            return _failure(call, started, FailureCode.MALFORMED_MCP_RESPONSE)
        except Exception:
            return _failure(call, started, FailureCode.TOOL_UNAVAILABLE)
        return ToolResult(
            tool_call_id=call.tool_call_id,
            status=ToolStatus.SUCCEEDED,
            output=output.model_dump(mode="json"),
            latency_ms=_latency(started),
            cache_status=_cache_status(output),
        )

    def _require_client(self) -> None:
        if self._client is None:
            raise RuntimeError("StdioMcpRuntime must be used as an async context manager")


def _json_bytes(value: object) -> bytes:
    import json

    return json.dumps(value, separators=(",", ":")).encode("utf-8")


def _cache_status(output: BaseModel) -> CacheStatus:
    provenance = getattr(output, "provenance", None)
    return (
        provenance.cache_status
        if provenance is not None
        else CacheStatus.NOT_APPLICABLE
    )


def _latency(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1_000))


def _failure(
    call: ToolCall,
    started: float,
    code: FailureCode,
    *,
    latency_ms: int | None = None,
) -> ToolResult:
    status = ToolStatus.TIMED_OUT if code is FailureCode.TOOL_TIMEOUT else ToolStatus.FAILED
    return ToolResult(
        tool_call_id=call.tool_call_id,
        status=status,
        error_code=code,
        latency_ms=_latency(started) if latency_ms is None else latency_ms,
    )


def _denied(call: ToolCall) -> ToolResult:
    return ToolResult(
        tool_call_id=call.tool_call_id,
        status=ToolStatus.DENIED,
        error_code=FailureCode.UNSAFE_REQUEST,
        latency_ms=0,
    )
