from __future__ import annotations

import hashlib
import ipaddress
import socket
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

from paper_agent.techscout.models import CacheStatus

from .cache import ContentAddressedCache, canonical_sha256
from .contracts import (
    FetchInput,
    FetchOutput,
    GitHubInspectInput,
    GitHubInspectOutput,
    GitHubIssue,
    GitHubRelease,
    SearchHit,
    SearchInput,
    SearchOutput,
    SourceProvenance,
)


Clock = Callable[[], datetime]
AddressResolver = Callable[[str], Iterable[str]]


class AdapterError(RuntimeError):
    """A safe external-adapter failure that never includes provider response bodies."""


class AdapterTimeout(AdapterError):
    pass


class AdapterRateLimited(AdapterError):
    pass


class ResponseTooLarge(AdapterError):
    pass


class UnsafeUrl(AdapterError):
    pass


class SearchAdapter(Protocol):
    def search(self, request: SearchInput) -> SearchOutput: ...


class FetchAdapter(Protocol):
    def fetch(self, request: FetchInput) -> FetchOutput: ...


class GitHubAdapter(Protocol):
    def inspect_repository(self, request: GitHubInspectInput) -> GitHubInspectOutput: ...


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def resolve_addresses(hostname: str) -> tuple[str, ...]:
    """Production resolver seam; tests can inject a deterministic resolver."""

    return tuple(
        sorted(
            {
                item[4][0]
                for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
            }
        )
    )


class UrlPolicy:
    def __init__(
        self,
        *,
        allowed_domains: Iterable[str] = (),
        resolver: AddressResolver | None = None,
    ) -> None:
        self._allowed = tuple(domain.lower().strip(".") for domain in allowed_domains)
        self._resolver = resolver

    def validate(self, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname:
            raise UnsafeUrl("only absolute HTTPS URLs are allowed")
        if parsed.username or parsed.password or parsed.fragment:
            raise UnsafeUrl("URL credentials and fragments are not allowed")
        hostname = parsed.hostname.lower().strip(".")
        if hostname == "localhost" or hostname.endswith(".localhost"):
            raise UnsafeUrl("local hosts are not allowed")
        if self._allowed and not any(
            hostname == domain or hostname.endswith(f".{domain}")
            for domain in self._allowed
        ):
            raise UnsafeUrl("URL host is outside the configured allowlist")
        self._validate_address(hostname)
        if self._resolver is not None:
            addresses = tuple(self._resolver(hostname))
            if not addresses:
                raise UnsafeUrl("URL host did not resolve")
            for address in addresses:
                self._validate_address(address)
        return value

    @staticmethod
    def _validate_address(value: str) -> None:
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            return
        if not address.is_global:
            raise UnsafeUrl("non-public network addresses are not allowed")


def _read_bounded(response: httpx.Response, max_bytes: int) -> bytes:
    content_length = response.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > max_bytes:
                raise ResponseTooLarge("response exceeded configured size limit")
        except ValueError as exc:
            raise AdapterError("invalid content-length response header") from exc
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes():
        total += len(chunk)
        if total > max_bytes:
            raise ResponseTooLarge("response exceeded configured size limit")
        chunks.append(chunk)
    return b"".join(chunks)


def _raise_status(response: httpx.Response) -> None:
    if response.status_code == 429:
        raise AdapterRateLimited("provider rate limited the request")
    if response.is_redirect:
        raise UnsafeUrl("redirect responses are not followed")
    if response.status_code >= 400:
        raise AdapterError(f"provider returned HTTP {response.status_code}")


def _safe_request(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    timeout: float,
    max_bytes: int,
    **kwargs: Any,
) -> tuple[httpx.Response, bytes]:
    kwargs.setdefault("follow_redirects", False)
    try:
        with client.stream(method, url, timeout=timeout, **kwargs) as response:
            _raise_status(response)
            content = _read_bounded(response, max_bytes)
            return response, content
    except httpx.TimeoutException as exc:
        raise AdapterTimeout("provider request timed out") from exc
    except httpx.RequestError as exc:
        raise AdapterError("provider request failed") from exc


def _json_object(content: bytes) -> dict[str, Any]:
    try:
        value = httpx.Response(200, content=content).json()
    except ValueError as exc:
        raise AdapterError("provider returned malformed JSON") from exc
    if not isinstance(value, dict):
        raise AdapterError("provider JSON response must be an object")
    return value


class TavilySearchAdapter:
    ENDPOINT = "https://api.tavily.com/search"

    def __init__(
        self,
        *,
        client: httpx.Client,
        api_key: str,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 512_000,
        max_snippet_chars: int = 4_000,
        clock: Clock = _utc_now,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Tavily API key is required")
        if timeout_seconds <= 0 or max_response_bytes < 1 or max_snippet_chars < 1:
            raise ValueError("timeout and response-size limit must be positive")
        self._client = client
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._max_bytes = max_response_bytes
        self._max_snippet_chars = max_snippet_chars
        self._clock = clock

    def search(self, request: SearchInput) -> SearchOutput:
        _, body = _safe_request(
            self._client,
            "POST",
            self.ENDPOINT,
            timeout=self._timeout,
            max_bytes=self._max_bytes,
            json={
                "api_key": self._api_key,
                "query": request.query,
                "max_results": request.max_results,
                "include_domains": list(request.domains),
                "search_depth": "basic",
            },
        )
        payload = _json_object(body)
        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            raise AdapterError("Tavily response omitted results")
        hits: list[SearchHit] = []
        seen_urls: set[str] = set()
        for raw in raw_results:
            if len(hits) >= request.max_results:
                break
            if not isinstance(raw, dict):
                raise AdapterError("Tavily result must be an object")
            try:
                url = str(httpx.URL(str(raw.get("url")))).rstrip("/")
                hit = SearchHit(
                    title=_bounded_text(raw.get("title"), 500),
                    url=url,
                    snippet=_bounded_text(
                        raw.get("content"), self._max_snippet_chars
                    ),
                    score=raw.get("score"),
                )
            except ValidationError as exc:
                raise AdapterError("Tavily result failed schema validation") from exc
            UrlPolicy(allowed_domains=request.domains).validate(hit.url)
            if hit.url in seen_urls:
                continue
            seen_urls.add(hit.url)
            hits.append(hit)
        snapshot = canonical_sha256([hit.model_dump(mode="json") for hit in hits])
        return SearchOutput(
            query=request.query,
            candidate_id=request.candidate_id,
            results=tuple(hits),
            provenance=SourceProvenance(
                provider="tavily",
                retrieved_at=self._clock(),
                snapshot_sha256=snapshot,
                cache_status=CacheStatus.MISS,
            ),
        )


class CachedSearchAdapter:
    def __init__(
        self,
        *,
        delegate: SearchAdapter,
        cache: ContentAddressedCache,
        max_stale: timedelta = timedelta(days=7),
        clock: Clock = _utc_now,
    ) -> None:
        if max_stale.total_seconds() <= 0:
            raise ValueError("maximum stale age must be positive")
        self._delegate = delegate
        self._cache = cache
        self._max_stale = max_stale
        self._clock = clock

    def search(self, request: SearchInput) -> SearchOutput:
        now = self._clock()
        key = self._cache.key("web.search", request)
        cached = self._cache.get(
            key, SearchOutput, now=now, allow_stale=True
        )
        if cached is not None and not cached.stale:
            return _with_cache(cached.value, CacheStatus.HIT, fallback=False)
        try:
            result = self._delegate.search(request)
        except AdapterError:
            if cached is None or now - cached.stored_at > self._max_stale:
                raise
            return _with_cache(cached.value, CacheStatus.STALE, fallback=True)
        self._cache.put(key, result, now=now)
        return result


def _with_cache(
    output: SearchOutput, status: CacheStatus, *, fallback: bool
) -> SearchOutput:
    provenance = output.provenance.model_copy(
        update={"cache_status": status, "cache_fallback": fallback}
    )
    return output.model_copy(update={"provenance": provenance})


class HttpxFetchAdapter:
    def __init__(
        self,
        *,
        client: httpx.Client,
        url_policy: UrlPolicy | None = None,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 1_000_000,
        clock: Clock = _utc_now,
    ) -> None:
        if timeout_seconds <= 0 or max_response_bytes < 1:
            raise ValueError("timeout and response-size limit must be positive")
        self._client = client
        self._policy = url_policy or UrlPolicy()
        self._timeout = timeout_seconds
        self._max_bytes = max_response_bytes
        self._clock = clock

    def fetch(self, request: FetchInput) -> FetchOutput:
        url = self._policy.validate(request.url)
        response, content = _safe_request(
            self._client,
            "GET",
            url,
            timeout=self._timeout,
            max_bytes=self._max_bytes,
            headers={"Accept": "text/html,text/plain,application/json"},
        )
        media_type = response.headers.get("content-type", "text/plain").split(";", 1)[0]
        if media_type not in {"text/html", "text/plain", "application/json"}:
            raise AdapterError("unsupported response media type")
        try:
            text = content.decode(response.encoding or "utf-8")
        except UnicodeDecodeError as exc:
            raise AdapterError("response is not valid text") from exc
        if not text.strip():
            raise AdapterError("response body is empty")
        digest = hashlib.sha256(content).hexdigest()
        return FetchOutput(
            url=url,
            candidate_id=request.candidate_id,
            media_type=media_type,
            content=text,
            size_bytes=len(content),
            provenance=SourceProvenance(
                provider="httpx",
                retrieved_at=self._clock(),
                snapshot_sha256=digest,
                cache_status=CacheStatus.MISS,
            ),
        )


class GitHubReadOnlyAdapter:
    API_ROOT = "https://api.github.com"

    def __init__(
        self,
        *,
        client: httpx.Client,
        token: str | None = None,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 512_000,
        readme_max_chars: int = 12_000,
        clock: Clock = _utc_now,
    ) -> None:
        if (
            timeout_seconds <= 0
            or max_response_bytes < 1
            or readme_max_chars < 1
        ):
            raise ValueError("GitHub adapter bounds must be positive")
        self._client = client
        self._token = token
        self._timeout = timeout_seconds
        self._max_bytes = max_response_bytes
        self._readme_max_chars = readme_max_chars
        self._clock = clock

    def inspect_repository(self, request: GitHubInspectInput) -> GitHubInspectOutput:
        owner, repository = self._parse_repository(request.repository_url)
        base = f"{self.API_ROOT}/repos/{owner}/{repository}"
        repo = self._get_json(base)
        readme = self._get_json(f"{base}/readme")
        releases_raw = self._get_list(
            f"{base}/releases?per_page={request.release_limit}"
        ) if request.release_limit else []
        issues_raw = self._get_list(
            f"{base}/issues?state=all&per_page={request.issue_limit}"
        ) if request.issue_limit else []
        try:
            import base64

            encoded = readme.get("content", "")
            if not isinstance(encoded, str):
                raise ValueError("GitHub README content must be base64 text")
            readme_text = base64.b64decode(
                "".join(encoded.split()), validate=True
            ).decode("utf-8")
            releases = tuple(
                GitHubRelease(
                    tag=item.get("tag_name"),
                    url=item.get("html_url"),
                    published_at=_optional_datetime(item.get("published_at")),
                )
                for item in releases_raw[: request.release_limit]
            )
            issues = tuple(
                GitHubIssue(
                    number=item.get("number"),
                    title=item.get("title"),
                    state=item.get("state"),
                    url=item.get("html_url"),
                )
                for item in issues_raw
                if "pull_request" not in item
            )[: request.issue_limit]
            normalized = {
                "repository_url": repo.get("html_url"),
                "default_branch": repo.get("default_branch"),
                "description": repo.get("description") or "",
                "stars": repo.get("stargazers_count"),
                "archived": repo.get("archived"),
                "readme_excerpt": readme_text[: self._readme_max_chars],
            }
            expected_url = f"https://github.com/{owner}/{repository}"
            if str(normalized["repository_url"]).rstrip("/") != expected_url:
                raise ValueError("GitHub response repository identity mismatch")
            github_policy = UrlPolicy(allowed_domains=("github.com",))
            for item in (*releases, *issues):
                github_policy.validate(item.url)
            snapshot = {
                **normalized,
                "releases": [item.model_dump(mode="json") for item in releases],
                "issues": [item.model_dump(mode="json") for item in issues],
            }
            return GitHubInspectOutput(
                candidate_id=request.candidate_id,
                **normalized,
                releases=releases,
                issues=issues,
                provenance=SourceProvenance(
                    provider="github-rest",
                    retrieved_at=self._clock(),
                    snapshot_sha256=canonical_sha256(snapshot),
                    cache_status=CacheStatus.MISS,
                ),
            )
        except (ValidationError, ValueError, UnicodeDecodeError) as exc:
            raise AdapterError("GitHub response failed schema validation") from exc

    @staticmethod
    def _parse_repository(url: str) -> tuple[str, str]:
        UrlPolicy(allowed_domains=("github.com",)).validate(url)
        parts = [part for part in urlsplit(url).path.split("/") if part]
        if len(parts) != 2:
            raise UnsafeUrl("GitHub repository URL must contain owner and repository")
        repository = parts[1][:-4] if parts[1].endswith(".git") else parts[1]
        return parts[0], repository

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _get_json(self, url: str) -> dict[str, Any]:
        _, content = _safe_request(
            self._client,
            "GET",
            url,
            timeout=self._timeout,
            max_bytes=self._max_bytes,
            headers=self._headers(),
        )
        return _json_object(content)

    def _get_list(self, url: str) -> list[dict[str, Any]]:
        _, content = _safe_request(
            self._client,
            "GET",
            url,
            timeout=self._timeout,
            max_bytes=self._max_bytes,
            headers=self._headers(),
        )
        try:
            value = httpx.Response(200, content=content).json()
        except ValueError as exc:
            raise AdapterError("GitHub returned malformed JSON") from exc
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise AdapterError("GitHub list response failed schema validation")
        return value


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _bounded_text(value: object, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("provider text field is missing")
    return value[:limit]
