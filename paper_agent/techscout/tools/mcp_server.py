from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx

from .adapters import (
    CachedSearchAdapter,
    GitHubAdapter,
    GitHubReadOnlyAdapter,
    HttpxFetchAdapter,
    SearchAdapter,
    UrlPolicy,
    resolve_addresses,
)
from .cache import ContentAddressedCache
from .contracts import (
    FetchInput,
    GitHubInspectInput,
    SearchInput,
    SmokeTestInput,
    SmokeTestOutput,
)


class SmokeTestAdapter(Protocol):
    def run_smoke_test(self, request: SmokeTestInput) -> SmokeTestOutput: ...


@dataclass(frozen=True, slots=True)
class ToolGatewayHandlers:
    search: SearchAdapter
    fetch: HttpxFetchAdapter
    github: GitHubAdapter
    smoke_test: SmokeTestAdapter


def create_mcp_server(handlers: ToolGatewayHandlers) -> Any:
    """Create the real local stdio gateway using the official MCP SDK v2.

    The import is lazy so the repository's offline unit suite remains runnable until
    the integration branch adds the declared MCP dependency.
    """

    try:
        from mcp.server import MCPServer
    except ImportError as exc:
        raise RuntimeError("MCP Python SDK v2 is required") from exc

    server = MCPServer("momo-techscout-tool-gateway", version="1")

    @server.tool(name="web.search", structured_output=True)
    def web_search(
        query: str,
        candidate_id: str,
        domains: list[str] | None = None,
        max_results: int = 5,
    ) -> dict[str, Any]:
        result = handlers.search.search(
            SearchInput(
                query=query,
                candidate_id=candidate_id,
                domains=tuple(domains or ()),
                max_results=max_results,
            )
        )
        return result.model_dump(mode="json")

    @server.tool(name="web.fetch", structured_output=True)
    def web_fetch(url: str, candidate_id: str) -> dict[str, Any]:
        result = handlers.fetch.fetch(FetchInput(url=url, candidate_id=candidate_id))
        return result.model_dump(mode="json")

    @server.tool(name="github.inspect_repository", structured_output=True)
    def github_inspect_repository(
        repository_url: str,
        candidate_id: str,
        release_limit: int = 3,
        issue_limit: int = 3,
    ) -> dict[str, Any]:
        result = handlers.github.inspect_repository(
            GitHubInspectInput(
                repository_url=repository_url,
                candidate_id=candidate_id,
                release_limit=release_limit,
                issue_limit=issue_limit,
            )
        )
        return result.model_dump(mode="json")

    @server.tool(name="sandbox.run_smoke_test", structured_output=True)
    def sandbox_run_smoke_test(
        candidate_id: str,
        recipe_id: str,
        checks: list[str],
        requested_version: str | None = None,
    ) -> dict[str, Any]:
        result = handlers.smoke_test.run_smoke_test(
            SmokeTestInput(
                candidate_id=candidate_id,
                recipe_id=recipe_id,
                checks=tuple(checks),
                requested_version=requested_version,
            )
        )
        return result.model_dump(mode="json")

    return server


class ResearchOnlySmokeAdapter:
    """Safe integration seam until Stream C supplies the allowlisted sandbox."""

    def run_smoke_test(self, request: SmokeTestInput) -> SmokeTestOutput:
        return SmokeTestOutput(
            candidate_id=request.candidate_id,
            recipe_id=request.recipe_id,
            status="research_only",
            duration_ms=0,
        )


def run_stdio_server(handlers: ToolGatewayHandlers) -> None:
    create_mcp_server(handlers).run(transport="stdio")


def main() -> None:
    from .adapters import TavilySearchAdapter

    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY is required for the live stdio gateway")
    cache_root = Path(os.environ.get("TECHSCOUT_CACHE_DIR", ".cache/techscout"))
    with httpx.Client(follow_redirects=False) as client:
        search = CachedSearchAdapter(
            delegate=TavilySearchAdapter(client=client, api_key=api_key),
            cache=ContentAddressedCache(cache_root),
        )
        run_stdio_server(
            ToolGatewayHandlers(
                search=search,
                fetch=HttpxFetchAdapter(
                    client=client, url_policy=UrlPolicy(resolver=resolve_addresses)
                ),
                github=GitHubReadOnlyAdapter(
                    client=client, token=os.environ.get("GITHUB_TOKEN")
                ),
                smoke_test=ResearchOnlySmokeAdapter(),
            )
        )


if __name__ == "__main__":
    main()
