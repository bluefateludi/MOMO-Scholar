from __future__ import annotations

import httpx
import pytest

from paper_agent.fulltext.downloader import (
    FullTextDownloader,
    PdfDownloadError,
    canonical_pdf_url,
)
from paper_agent.schemas import Paper


PDF = b"%PDF-1.7\nsmall test document"


def _paper(*, paper_id: str = "arxiv:2401.00001", pdf_url: str | None = None) -> Paper:
    return Paper(
        paper_id=paper_id,
        title="Test paper",
        url="https://arxiv.org/abs/2401.00001",
        pdf_url=pdf_url,
        source="arxiv",
    )


def _downloader(
    handler,
    *,
    max_bytes: int = 1024,
    max_redirects: int = 3,
) -> tuple[FullTextDownloader, httpx.Client]:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return (
        FullTextDownloader(
            client=client,
            timeout_seconds=2,
            max_bytes=max_bytes,
            max_redirects=max_redirects,
        ),
        client,
    )


@pytest.mark.parametrize(
    ("paper_id", "expected"),
    [
        ("arxiv:2401.00001", "https://arxiv.org/pdf/2401.00001"),
        ("arxiv:2401.00001v2", "https://arxiv.org/pdf/2401.00001v2"),
        ("arxiv:cs/9901001", "https://arxiv.org/pdf/cs/9901001"),
    ],
)
def test_canonical_pdf_url_is_derived_from_paper_id(paper_id: str, expected: str) -> None:
    assert canonical_pdf_url(_paper(paper_id=paper_id)) == expected


@pytest.mark.parametrize("paper_id", ["", "2401.00001", "doi:10.1/example", "arxiv:bad"])
def test_canonical_pdf_url_rejects_missing_or_non_arxiv_id(paper_id: str) -> None:
    with pytest.raises(PdfDownloadError, match="pdf_url_missing") as caught:
        canonical_pdf_url(_paper(paper_id=paper_id))
    assert caught.value.code == "pdf_url_missing"


def test_download_never_requests_paper_pdf_url() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=PDF)

    downloader, client = _downloader(handler)
    try:
        downloader.download(_paper(pdf_url="http://evil.example/Paper.pdf"))
    finally:
        client.close()

    assert requested == ["https://arxiv.org/pdf/2401.00001"]


@pytest.mark.parametrize(
    "location",
    [
        "http://arxiv.org/pdf/2401.00001",
        "https://example.com/pdf/2401.00001",
        "https://localhost/pdf/2401.00001",
        "https://127.0.0.1/pdf/2401.00001",
        "https://user@arxiv.org/pdf/2401.00001",
        "https://arxiv.org:444/pdf/2401.00001",
        "https://arxiv.org/pdf/2401.00001?download=1",
        "https://arxiv.org/pdf/2401.00001#page=1",
        "https://arxiv.org/pdf/2401.00002",
        "https://arxiv.org/pdf/2401.00001/extra",
        "https://arxiv.org/pdf%2F2401.00001",
        "https://arxiv.org/pdf/2401.00001%2Fextra",
    ],
)
def test_redirect_policy_rejects_unsafe_location(location: str) -> None:
    downloader, client = _downloader(
        lambda request: httpx.Response(302, headers={"location": location})
    )
    try:
        with pytest.raises(PdfDownloadError) as caught:
            downloader.download(_paper())
    finally:
        client.close()
    assert caught.value.code == "pdf_redirect_rejected"


@pytest.mark.parametrize(
    "location",
    [
        "https://arxiv.org/pdf/2401.00001",
        "https://arxiv.org:443/pdf/2401.00001.pdf",
        "https://export.arxiv.org/pdf/2401.00001",
    ],
)
def test_redirect_policy_allows_exact_arxiv_pdf_location(location: str) -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        if requests == 1:
            return httpx.Response(302, headers={"location": location})
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=PDF)

    downloader, client = _downloader(handler)
    try:
        result = downloader.download(_paper())
    finally:
        client.close()
    assert result.content == PDF
    assert result.source_url == str(httpx.URL(location))


def test_each_redirect_hop_is_revalidated() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "arxiv.org":
            return httpx.Response(
                302, headers={"location": "https://export.arxiv.org/pdf/2401.00001"}
            )
        return httpx.Response(302, headers={"location": "https://evil.example/file.pdf"})

    downloader, client = _downloader(handler)
    try:
        with pytest.raises(PdfDownloadError) as caught:
            downloader.download(_paper())
    finally:
        client.close()
    assert caught.value.code == "pdf_redirect_rejected"


def test_more_than_three_redirects_is_rejected() -> None:
    downloader, client = _downloader(
        lambda request: httpx.Response(
            302, headers={"location": "https://arxiv.org/pdf/2401.00001.pdf"}
        )
    )
    try:
        with pytest.raises(PdfDownloadError) as caught:
            downloader.download(_paper())
    finally:
        client.close()
    assert caught.value.code == "pdf_redirect_rejected"


@pytest.mark.parametrize("content_type", ["application/pdf", "application/octet-stream"])
def test_download_accepts_pdf_content_types_and_magic(content_type: str) -> None:
    downloader, client = _downloader(
        lambda request: httpx.Response(200, headers={"content-type": content_type}, content=PDF)
    )
    try:
        result = downloader.download(_paper())
    finally:
        client.close()
    assert result.content == PDF
    assert result.content_type == content_type


@pytest.mark.parametrize("status", [404, 410])
def test_not_found_status_is_mapped(status: int) -> None:
    downloader, client = _downloader(lambda request: httpx.Response(status))
    try:
        with pytest.raises(PdfDownloadError) as caught:
            downloader.download(_paper())
    finally:
        client.close()
    assert caught.value.code == "pdf_not_found"


def test_other_http_error_is_mapped() -> None:
    downloader, client = _downloader(lambda request: httpx.Response(503))
    try:
        with pytest.raises(PdfDownloadError) as caught:
            downloader.download(_paper())
    finally:
        client.close()
    assert caught.value.code == "pdf_http_error"


@pytest.mark.parametrize("error", [httpx.ConnectTimeout("late"), httpx.ReadTimeout("late")])
def test_timeout_is_mapped(error: httpx.TimeoutException) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    downloader, client = _downloader(handler)
    try:
        with pytest.raises(PdfDownloadError) as caught:
            downloader.download(_paper())
    finally:
        client.close()
    assert caught.value.code == "pdf_download_timeout"


def test_declared_content_length_over_cap_is_rejected_without_reading_body() -> None:
    class UnreadableStream(httpx.SyncByteStream):
        def __iter__(self):
            raise AssertionError("oversized declared body must not be read")

    downloader, client = _downloader(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "application/pdf", "content-length": "100"},
            stream=UnreadableStream(),
        ),
        max_bytes=20,
    )
    try:
        with pytest.raises(PdfDownloadError) as caught:
            downloader.download(_paper())
    finally:
        client.close()
    assert caught.value.code == "pdf_too_large"


def test_streamed_overflow_stops_before_reading_another_chunk() -> None:
    class OverflowStream(httpx.SyncByteStream):
        def __iter__(self):
            yield b"%PDF-12345"
            yield b"x"
            raise AssertionError("downloader read beyond first overflowing chunk")

    downloader, client = _downloader(
        lambda request: httpx.Response(
            200, headers={"content-type": "application/pdf"}, stream=OverflowStream()
        ),
        max_bytes=10,
    )
    try:
        with pytest.raises(PdfDownloadError) as caught:
            downloader.download(_paper())
    finally:
        client.close()
    assert caught.value.code == "pdf_too_large"


def test_body_exactly_at_cap_succeeds() -> None:
    downloader, client = _downloader(
        lambda request: httpx.Response(
            200, headers={"content-type": "application/pdf"}, content=PDF
        ),
        max_bytes=len(PDF),
    )
    try:
        assert downloader.download(_paper()).content == PDF
    finally:
        client.close()


@pytest.mark.parametrize(
    ("content_type", "content"),
    [("text/html", PDF), ("application/pdf", b"not a pdf")],
)
def test_invalid_content_type_or_magic_is_rejected(content_type: str, content: bytes) -> None:
    downloader, client = _downloader(
        lambda request: httpx.Response(
            200, headers={"content-type": content_type}, content=content
        )
    )
    try:
        with pytest.raises(PdfDownloadError) as caught:
            downloader.download(_paper())
    finally:
        client.close()
    assert caught.value.code == "pdf_content_invalid"


def test_midstream_protocol_error_is_mapped() -> None:
    class BrokenStream(httpx.SyncByteStream):
        def __iter__(self):
            yield b"%PDF-"
            raise httpx.RemoteProtocolError("truncated")

    downloader, client = _downloader(
        lambda request: httpx.Response(
            200, headers={"content-type": "application/pdf"}, stream=BrokenStream()
        )
    )
    try:
        with pytest.raises(PdfDownloadError) as caught:
            downloader.download(_paper())
    finally:
        client.close()
    assert caught.value.code == "pdf_http_error"


def test_short_completed_pdf_magic_body_is_returned_for_parser_validation() -> None:
    content = b"%PDF-"
    downloader, client = _downloader(
        lambda request: httpx.Response(
            200, headers={"content-type": "application/pdf"}, content=content
        )
    )
    try:
        assert downloader.download(_paper()).content == content
    finally:
        client.close()


def test_downloader_does_not_close_caller_supplied_client() -> None:
    downloader, client = _downloader(
        lambda request: httpx.Response(
            200, headers={"content-type": "application/pdf"}, content=PDF
        )
    )
    downloader.download(_paper())
    assert not client.is_closed
    client.close()
