import asyncio
import os
import sys

import mcp
from mcp import Client

from paper_agent.techscout.models import ToolCall, ToolStatus
from paper_agent.techscout.tools.mcp_server import (
    ResearchOnlySmokeAdapter,
    ToolGatewayHandlers,
    create_mcp_server,
)
from paper_agent.techscout.tools.runtime import StdioMcpRuntime


class _UnusedAdapters:
    def search(self, request):
        raise AssertionError("search must not run")

    def fetch(self, request):
        raise AssertionError("fetch must not run")

    def inspect_repository(self, request):
        raise AssertionError("GitHub must not run")


def _gateway_handlers() -> ToolGatewayHandlers:
    unused = _UnusedAdapters()
    return ToolGatewayHandlers(
        search=unused,
        fetch=unused,
        github=unused,
        smoke_test=ResearchOnlySmokeAdapter(),
    )


def _smoke_call() -> ToolCall:
    return ToolCall(
        tool_call_id="tool-call:mcp-v2:smoke",
        tool_name="sandbox.run_smoke_test",
        skill_id="skill:python-package-smoke-test@1",
        arguments={
            "candidate_id": "candidate:qdrant",
            "recipe_id": "recipe:qdrant-local@1",
            "checks": ["import"],
        },
    )


def test_real_mcp_v2_in_memory_gateway() -> None:
    async def exercise() -> None:
        async with Client(create_mcp_server(_gateway_handlers())) as client:
            discovered = await client.list_tools()
            assert {tool.name for tool in discovered.tools} == {
                "web.search",
                "web.fetch",
                "github.inspect_repository",
                "sandbox.run_smoke_test",
            }
            result = await client.call_tool(
                "sandbox.run_smoke_test", _smoke_call().arguments
            )
            assert result.is_error is False
            assert result.structured_content["status"] == "research_only"

    asyncio.run(exercise())


def test_real_mcp_v2_local_stdio_runtime(tmp_path, monkeypatch) -> None:
    def reject_low_level_session(*args, **kwargs):
        raise AssertionError("StdioMcpRuntime must use the MCP v2 Client API")

    monkeypatch.setattr(mcp, "ClientSession", reject_low_level_session)

    async def exercise() -> None:
        environment = dict(os.environ)
        environment.update(
            {
                "TAVILY_API_KEY": "offline-test-key",
                "TECHSCOUT_CACHE_DIR": str(tmp_path / "cache"),
            }
        )
        async with StdioMcpRuntime(
            command=sys.executable,
            args=("-m", "paper_agent.techscout.tools.mcp_server"),
            env=environment,
            timeout_seconds=10,
        ) as runtime:
            assert "sandbox.run_smoke_test" in await runtime.discover_tools()
            result = await runtime.invoke(_smoke_call())
        assert result.status is ToolStatus.SUCCEEDED
        assert result.output["status"] == "research_only"

    asyncio.run(exercise())
