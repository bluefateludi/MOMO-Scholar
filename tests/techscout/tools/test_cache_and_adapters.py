import base64
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from paper_agent.techscout.models import CacheStatus
from paper_agent.techscout.tools.adapters import (
    AdapterTimeout,
    CachedFetchAdapter,
    CachedGitHubAdapter,
    CachedSearchAdapter,
    GitHubReadOnlyAdapter,
    HttpxFetchAdapter,
    ResponseTooLarge,
    TavilySearchAdapter,
    UnsafeUrl,
    UrlPolicy,
)
from paper_agent.techscout.tools.cache import ContentAddressedCache
from paper_agent.techscout.tools.contracts import (
    FetchInput,
    FetchOutput,
    GitHubInspectInput,
    GitHubInspectOutput,
    SearchHit,
    SearchInput,
    SearchOutput,
    SourceProvenance,
)


NOW = datetime(2026, 8, 9, tzinfo=timezone.utc)


def _request() -> SearchInput:
    return SearchInput(
        query="Qdrant filtering",
        candidate_id="candidate:qdrant",
        domains=("qdrant.tech",),
    )


def _output() -> SearchOutput:
    return SearchOutput(
        query="Qdrant filtering",
        candidate_id="candidate:qdrant",
        results=(
            SearchHit(
                title="Filtering",
                url="https://qdrant.tech/docs/filtering",
                snippet="Filtering docs",
                score=0.9,
            ),
        ),
        provenance=SourceProvenance(
            provider="fake",
            retrieved_at=NOW,
            snapshot_sha256="a" * 64,
            cache_status=CacheStatus.MISS,
        ),
    )


class _FailingSearch:
    def search(self, request: SearchInput) -> SearchOutput:
        raise AdapterTimeout("offline")


def test_content_addressed_cache_hit_and_explicit_stale_fallback(tmp_path) -> None:
    cache = ContentAddressedCache(tmp_path, ttl=timedelta(hours=1))
    key = cache.key("web.search", _request())
    digest = cache.put(key, _output(), now=NOW)
    assert (tmp_path / "blobs" / f"{digest}.json").is_file()

    warm = CachedSearchAdapter(delegate=_FailingSearch(), cache=cache, clock=lambda: NOW)
    assert warm.search(_request()).provenance.cache_status is CacheStatus.HIT

    fallback = CachedSearchAdapter(
        delegate=_FailingSearch(),
        cache=cache,
        max_stale=timedelta(hours=4),
        clock=lambda: NOW + timedelta(hours=2),
    ).search(_request())
    assert fallback.provenance.cache_status is CacheStatus.STALE
    assert fallback.provenance.cache_fallback is True


def test_fetch_and_github_cache_fallback_preserve_non_live_provenance(tmp_path) -> None:
    cache = ContentAddressedCache(tmp_path, ttl=timedelta(hours=1))
    fetch_request = FetchInput(
        url="https://docs.example.com/page",
        candidate_id="candidate:test",
    )
    fetch_output = FetchOutput(
        url=fetch_request.url,
        candidate_id=fetch_request.candidate_id,
        media_type="text/plain",
        content="cached docs",
        size_bytes=11,
        provenance=SourceProvenance(
            provider="httpx",
            retrieved_at=NOW,
            snapshot_sha256="b" * 64,
            cache_status=CacheStatus.MISS,
        ),
    )
    cache.put(cache.key("web.fetch", fetch_request), fetch_output, now=NOW)

    class FailingFetch:
        def fetch(self, request):
            raise AdapterTimeout("offline")

    cached_fetch = CachedFetchAdapter(
        delegate=FailingFetch(),
        cache=cache,
        clock=lambda: NOW + timedelta(hours=2),
    ).fetch(fetch_request)
    assert cached_fetch.provenance.cache_status is CacheStatus.STALE
    assert cached_fetch.provenance.cache_fallback is True

    github_request = GitHubInspectInput(
        repository_url="https://github.com/acme/vector",
        candidate_id="candidate:test",
        release_limit=0,
        issue_limit=0,
    )
    github_output = GitHubInspectOutput(
        candidate_id="candidate:test",
        repository_url="https://github.com/acme/vector",
        default_branch="main",
        description="cached repository",
        stars=1,
        archived=False,
        readme_excerpt="cached readme",
        releases=(),
        issues=(),
        provenance=SourceProvenance(
            provider="github-rest",
            retrieved_at=NOW,
            snapshot_sha256="c" * 64,
            cache_status=CacheStatus.MISS,
        ),
    )
    cache.put(cache.key("github.inspect_repository", github_request), github_output, now=NOW)

    class FailingGitHub:
        def inspect_repository(self, request):
            raise AdapterTimeout("offline")

    cached_github = CachedGitHubAdapter(
        delegate=FailingGitHub(),
        cache=cache,
        clock=lambda: NOW + timedelta(hours=2),
    ).inspect_repository(github_request)
    assert cached_github.provenance.cache_status is CacheStatus.STALE
    assert cached_github.provenance.cache_fallback is True


def test_tavily_is_bounded_and_normalizes_provenance() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.tavily.com/search"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Filtering",
                        "url": "https://qdrant.tech/docs/filtering",
                        "content": "Payload filtering.",
                        "score": 0.8,
                    },
                    {
                        "title": "Duplicate filtering",
                        "url": "https://qdrant.tech/docs/filtering/",
                        "content": "Duplicate URL.",
                        "score": 0.7,
                    },
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        output = TavilySearchAdapter(
            client=client, api_key="sentinel", clock=lambda: NOW
        ).search(_request())

    assert len(output.results) == 1
    assert output.provenance.provider == "tavily"
    assert len(output.provenance.snapshot_sha256) == 64


def test_https_fetch_rejects_private_urls_and_oversized_content() -> None:
    with pytest.raises(UnsafeUrl):
        UrlPolicy().validate("https://127.0.0.1/secrets")

    with pytest.raises(UnsafeUrl):
        UrlPolicy(resolver=lambda _: ("10.0.0.8",)).validate(
            "https://docs.example.com/page"
        )

    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"content-type": "text/plain"},
                content=b"too large",
            )
        )
    ) as client:
        adapter = HttpxFetchAdapter(
            client=client,
            url_policy=UrlPolicy(resolver=lambda _: ("8.8.8.8",)),
            max_response_bytes=3,
        )
        with pytest.raises(ResponseTooLarge):
            adapter.fetch(
                FetchInput(
                    url="https://docs.example.com/page",
                    candidate_id="candidate:test",
                )
            )


def test_https_fetch_pins_the_validated_address_and_preserves_origin() -> None:
    resolutions = 0

    def resolver(_: str) -> tuple[str, ...]:
        nonlocal resolutions
        resolutions += 1
        return ("8.8.8.8",) if resolutions == 1 else ("10.0.0.8",)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "8.8.8.8"
        assert request.headers["host"] == "docs.example.com"
        assert request.extensions["sni_hostname"] == "docs.example.com"
        return httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            content=b"safe",
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        output = HttpxFetchAdapter(
            client=client,
            url_policy=UrlPolicy(resolver=resolver),
        ).fetch(
            FetchInput(
                url="https://docs.example.com/page",
                candidate_id="candidate:test",
            )
        )

    assert resolutions == 1
    assert output.url == "https://docs.example.com/page"


def test_github_adapter_is_read_only_and_bounded() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/readme"):
            return httpx.Response(
                200, json={"content": base64.b64encode(b"README body").decode()}
            )
        if path.endswith("/releases"):
            return httpx.Response(
                200,
                json=[
                    {
                        "tag_name": "v1.0",
                        "html_url": "https://github.com/acme/vector/releases/tag/v1.0",
                        "published_at": "2026-08-01T00:00:00Z",
                    }
                ],
            )
        if path.endswith("/issues"):
            return httpx.Response(
                200,
                json=[
                    {
                        "number": 1,
                        "title": "Filtering issue",
                        "state": "open",
                        "html_url": "https://github.com/acme/vector/issues/1",
                    }
                ],
            )
        return httpx.Response(
            200,
            json={
                "html_url": "https://github.com/acme/vector",
                "default_branch": "main",
                "description": "A vector store",
                "stargazers_count": 42,
                "archived": False,
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = GitHubReadOnlyAdapter(client=client, clock=lambda: NOW).inspect_repository(
            GitHubInspectInput(
                repository_url="https://github.com/acme/vector",
                candidate_id="candidate:vector",
                release_limit=1,
                issue_limit=1,
            )
        )

    assert result.readme_excerpt == "README body"
    assert result.releases[0].tag == "v1.0"
    assert result.issues[0].number == 1
