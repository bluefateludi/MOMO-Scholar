from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

import httpx

from paper_agent.schemas import Paper


_ARXIV_ID = re.compile(
    r"(?:\d{4}\.\d{4,5}|[A-Za-z][A-Za-z0-9.-]*/\d{7})(?:v\d+)?"
)
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_ALLOWED_HOSTS = {"arxiv.org", "export.arxiv.org"}
_PDF_CONTENT_TYPES = {"application/pdf", "application/octet-stream"}


@dataclass(frozen=True, slots=True)
class DownloadedPdf:
    content: bytes
    source_url: str
    content_type: str


@dataclass(frozen=True, slots=True)
class PdfDownloadError(RuntimeError):
    code: Literal[
        "pdf_url_missing",
        "pdf_download_timeout",
        "pdf_not_found",
        "pdf_http_error",
        "pdf_redirect_rejected",
        "pdf_too_large",
        "pdf_content_invalid",
    ]
    message: str

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


def _canonical_arxiv_id(paper: Paper) -> str:
    prefix = "arxiv:"
    if not paper.paper_id.startswith(prefix):
        raise PdfDownloadError("pdf_url_missing", "paper has no canonical arXiv ID")
    arxiv_id = paper.paper_id[len(prefix) :]
    if not _ARXIV_ID.fullmatch(arxiv_id):
        raise PdfDownloadError("pdf_url_missing", "paper has no canonical arXiv ID")
    return arxiv_id


def canonical_pdf_url(paper: Paper) -> str:
    return f"https://arxiv.org/pdf/{_canonical_arxiv_id(paper)}"


def _is_valid_pdf_url(url: httpx.URL, arxiv_id: str) -> bool:
    allowed_paths = {
        f"/pdf/{arxiv_id}".encode("ascii"),
        f"/pdf/{arxiv_id}.pdf".encode("ascii"),
    }
    return not (
        url.scheme != "https"
        or url.host not in _ALLOWED_HOSTS
        or url.port not in {None, 443}
        or url.userinfo
        or url.query
        or url.fragment
        or url.raw_path not in allowed_paths
    )


class FullTextDownloader:
    def __init__(
        self,
        *,
        client: httpx.Client,
        timeout_seconds: float,
        max_bytes: int,
        max_redirects: int = 3,
    ) -> None:
        self._client = client
        self._timeout = httpx.Timeout(timeout_seconds)
        self._max_bytes = max_bytes
        self._max_redirects = max_redirects

    def download(self, paper: Paper) -> DownloadedPdf:
        arxiv_id = _canonical_arxiv_id(paper)
        url = httpx.URL(canonical_pdf_url(paper))
        redirects = 0

        while True:
            error: PdfDownloadError | None = None
            next_url: httpx.URL | None = None
            result: DownloadedPdf | None = None
            try:
                with self._client.stream(
                    "GET", url, follow_redirects=False, timeout=self._timeout
                ) as response:
                    if response.status_code in _REDIRECT_STATUSES:
                        location = response.headers.get("location")
                        if location is None or redirects >= self._max_redirects:
                            error = PdfDownloadError(
                                "pdf_redirect_rejected", "redirect limit exceeded or location missing"
                            )
                        else:
                            candidate = response.request.url.join(location)
                            if _is_valid_pdf_url(candidate, arxiv_id):
                                next_url = candidate
                            else:
                                error = PdfDownloadError(
                                    "pdf_redirect_rejected",
                                    "redirect target violates the arXiv PDF URL policy",
                                )
                    elif response.status_code in {404, 410}:
                        error = PdfDownloadError("pdf_not_found", "arXiv PDF was not found")
                    elif not response.is_success:
                        error = PdfDownloadError(
                            "pdf_http_error",
                            f"arXiv PDF request returned HTTP {response.status_code}",
                        )
                    else:
                        content_type = response.headers.get("content-type", "").split(";", 1)[0]
                        content_type = content_type.strip().lower()
                        if content_type not in _PDF_CONTENT_TYPES:
                            error = PdfDownloadError(
                                "pdf_content_invalid",
                                "response content type is not PDF-compatible",
                            )
                        content_length = response.headers.get("content-length")
                        if error is None and content_length is not None:
                            try:
                                declared_size = int(content_length)
                            except ValueError:
                                declared_size = -1
                            if declared_size > self._max_bytes:
                                error = PdfDownloadError(
                                    "pdf_too_large",
                                    "declared PDF size exceeds the configured limit",
                                )

                        if error is None:
                            chunks: list[bytes] = []
                            size = 0
                            for chunk in response.iter_bytes():
                                if size + len(chunk) > self._max_bytes:
                                    error = PdfDownloadError(
                                        "pdf_too_large", "PDF body exceeds the configured limit"
                                    )
                                    break
                                chunks.append(chunk)
                                size += len(chunk)
                            if error is None:
                                content = b"".join(chunks)
                                if not content.startswith(b"%PDF-"):
                                    error = PdfDownloadError(
                                        "pdf_content_invalid",
                                        "response does not begin with PDF magic",
                                    )
                                else:
                                    result = DownloadedPdf(
                                        content=content,
                                        source_url=str(response.request.url),
                                        content_type=content_type,
                                    )
            except httpx.TimeoutException as exc:
                raise PdfDownloadError(
                    "pdf_download_timeout", "arXiv PDF request timed out"
                ) from exc
            except httpx.RequestError as exc:
                raise PdfDownloadError("pdf_http_error", "arXiv PDF request failed") from exc

            if error is not None:
                raise error
            if result is not None:
                return result
            if next_url is not None:
                redirects += 1
                url = next_url
