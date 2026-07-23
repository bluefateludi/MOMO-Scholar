from pathlib import Path

import httpx
import pytest

from paper_agent.retrieval import arxiv as arxiv_module
from paper_agent.retrieval.arxiv import parse_arxiv_feed, search_arxiv


def test_parse_arxiv_feed_extracts_paper_fields():
    xml = Path("tests/fixtures/arxiv_feed.xml").read_text(encoding="utf-8")
    papers = parse_arxiv_feed(xml)
    assert len(papers) == 1
    paper = papers[0]
    assert paper.paper_id == "arxiv:2401.00001"
    assert paper.title == "Example Paper Agent Study"
    assert paper.authors == ["Alice Researcher", "Bob Scientist"]
    assert paper.year == 2024
    assert paper.pdf_url == "http://arxiv.org/pdf/2401.00001v1"


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_search_retries_429_with_retry_after_and_identifies_client() -> None:
    feed = Path("tests/fixtures/arxiv_feed.xml").read_text(encoding="utf-8")
    requests: list[httpx.Request] = []
    responses = iter(
        [
            httpx.Response(429, headers={"Retry-After": "4"}),
            httpx.Response(200, text=feed),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return next(responses)

    sleeps: list[float] = []
    with _client(handler) as client:
        papers = search_arxiv(
            "hybrid retrieval",
            1,
            client=client,
            sleep=sleeps.append,
        )

    assert len(papers) == 1
    assert sleeps == [4.0]
    assert len(requests) == 2
    assert all("MOMO-Scholar" in request.headers["User-Agent"] for request in requests)


def test_search_retries_timeout_and_server_error_with_bounded_delays() -> None:
    feed = Path("tests/fixtures/arxiv_feed.xml").read_text(encoding="utf-8")
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ReadTimeout("late", request=request)
        if attempts == 2:
            return httpx.Response(503)
        return httpx.Response(200, text=feed)

    sleeps: list[float] = []
    with _client(handler) as client:
        papers = search_arxiv("hybrid retrieval", 1, client=client, sleep=sleeps.append)

    assert len(papers) == 1
    assert attempts == 3
    assert sleeps == [3.0, 6.0]


def test_search_does_not_retry_permanent_client_error() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(400)

    sleeps: list[float] = []
    with _client(handler) as client:
        with pytest.raises(arxiv_module.ArxivSearchError) as caught:
            search_arxiv("invalid", 1, client=client, sleep=sleeps.append)

    assert caught.value.error_code == "arxiv_search_http_error"
    assert attempts == 1
    assert sleeps == []


def test_search_exhausts_rate_limit_retries_with_specific_safe_code() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(429)

    sleeps: list[float] = []
    with _client(handler) as client:
        with pytest.raises(arxiv_module.ArxivSearchError) as caught:
            search_arxiv("hybrid retrieval", 1, client=client, sleep=sleeps.append)

    assert caught.value.error_code == "arxiv_search_rate_limited"
    assert attempts == 3
    assert sleeps == [3.0, 6.0]
