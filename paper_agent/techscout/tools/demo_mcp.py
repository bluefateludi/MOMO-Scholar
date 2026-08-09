"""Offline deterministic MCP gateway used by the Web Fast Demo path.

This is synthetic evidence served through the real local stdio MCP transport. It
never claims to be live provider data and is deliberately separate from the live
gateway in :mod:`mcp_server`.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone

from paper_agent.techscout.models import CacheStatus

from .contracts import (
    FetchInput,
    FetchOutput,
    GitHubInspectInput,
    GitHubInspectOutput,
    SearchHit,
    SearchInput,
    SearchOutput,
    SmokeTestInput,
    SmokeTestOutput,
    SourceProvenance,
)
from .mcp_server import ToolGatewayHandlers, run_stdio_server


_AS_OF = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _provenance(value: str) -> SourceProvenance:
    cached = os.environ.get("TECHSCOUT_DEMO_SCENARIO") == "cached_degradation"
    return SourceProvenance(
        provider="momo-frozen-demo",
        retrieved_at=_AS_OF,
        snapshot_sha256=_sha(value),
        cache_status=CacheStatus.HIT if cached else CacheStatus.NOT_APPLICABLE,
        cache_fallback=cached,
    )


class FrozenSearchAdapter:
    def search(self, request: SearchInput) -> SearchOutput:
        slug = request.candidate_id.split(":", 1)[-1]
        url = f"https://docs.example.test/{slug}/frozen-local-mode"
        snippet = (
            "Frozen synthetic documentation states that the local mode supports "
            "persistence and metadata equality filtering without a managed service."
        )
        return SearchOutput(
            query=request.query,
            candidate_id=request.candidate_id,
            results=(SearchHit(title=f"{slug} frozen official guide", url=url, snippet=snippet, score=1.0),),
            provenance=_provenance(snippet),
        )


class FrozenFetchAdapter:
    def fetch(self, request: FetchInput) -> FetchOutput:
        content = "Frozen synthetic documentation for offline Fast Demo verification."
        return FetchOutput(
            url=request.url,
            candidate_id=request.candidate_id,
            media_type="text/plain",
            content=content,
            size_bytes=len(content.encode("utf-8")),
            provenance=_provenance(content),
        )


class FrozenGitHubAdapter:
    def inspect_repository(self, request: GitHubInspectInput) -> GitHubInspectOutput:
        return GitHubInspectOutput(
            candidate_id=request.candidate_id,
            repository_url=request.repository_url,
            default_branch="main",
            description="Frozen synthetic repository metadata.",
            stars=0,
            archived=False,
            readme_excerpt="Offline Fast Demo fixture.",
            releases=(),
            issues=(),
            provenance=_provenance(request.repository_url),
        )


class DeterministicSmokeAdapter:
    def run_smoke_test(self, request: SmokeTestInput) -> SmokeTestOutput:
        if request.requested_version == "demo-conflict":
            return SmokeTestOutput(
                candidate_id=request.candidate_id,
                recipe_id=request.recipe_id,
                status="failed",
                exit_code=1,
                duration_ms=4,
            )
        resolved = "1.0.15" if "chroma" in request.recipe_id else "1.15.1"
        payload = f"{request.candidate_id}:{request.recipe_id}:{resolved}"
        return SmokeTestOutput(
            candidate_id=request.candidate_id,
            recipe_id=request.recipe_id,
            status="passed",
            resolved_version=resolved,
            exit_code=0,
            duration_ms=6,
            artifact_sha256=_sha(payload),
        )


def main() -> None:
    run_stdio_server(
        ToolGatewayHandlers(
            search=FrozenSearchAdapter(),
            fetch=FrozenFetchAdapter(),
            github=FrozenGitHubAdapter(),
            smoke_test=DeterministicSmokeAdapter(),
        )
    )


if __name__ == "__main__":
    main()
