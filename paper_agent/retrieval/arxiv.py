from __future__ import annotations

from collections.abc import Callable
import math
import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlencode

import httpx

from paper_agent.schemas import Paper

ARXIV_API_URL = "https://export.arxiv.org/api/query"
ARXIV_USER_AGENT = (
    "MOMO-Scholar/0.1 (+https://github.com/bluefateludi/MOMO-Scholar)"
)
ARXIV_MAX_ATTEMPTS = 3
ARXIV_RETRY_AFTER_MAX_SECONDS = 30.0
ATOM = {"atom": "http://www.w3.org/2005/Atom"}


class ArxivSearchError(ValueError):
    def __init__(self, error_code: str) -> None:
        self.error_code = error_code
        super().__init__(error_code)


def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
    if response is not None:
        raw = response.headers.get("Retry-After")
        if raw is not None:
            try:
                supplied = float(raw)
            except ValueError:
                supplied = -1.0
            if math.isfinite(supplied) and supplied >= 0:
                return min(supplied, ARXIV_RETRY_AFTER_MAX_SECONDS)
    return 3.0 * (attempt + 1)


def _clean_arxiv_id(raw_id: str) -> str:
    match = re.search(r"/abs/([^/]+)$", raw_id)
    value = match.group(1) if match else raw_id
    value = re.sub(r"v\d+$", "", value)
    return f"arxiv:{value}"


def parse_arxiv_feed(xml_text: str) -> list[Paper]:
    root = ET.fromstring(xml_text)
    papers: list[Paper] = []
    for entry in root.findall("atom:entry", ATOM):
        raw_id = entry.findtext("atom:id", default="", namespaces=ATOM)
        title = " ".join(entry.findtext("atom:title", default="", namespaces=ATOM).split())
        summary = " ".join(entry.findtext("atom:summary", default="", namespaces=ATOM).split())
        published = entry.findtext("atom:published", default="", namespaces=ATOM)
        authors = [
            name.text.strip()
            for name in entry.findall("atom:author/atom:name", ATOM)
            if name.text
        ]
        pdf_url = None
        url = raw_id
        for link in entry.findall("atom:link", ATOM):
            rel = link.attrib.get("rel")
            title_attr = link.attrib.get("title")
            href = link.attrib.get("href")
            if rel == "alternate" and href:
                url = href
            if title_attr == "pdf" and href:
                pdf_url = href
        papers.append(
            Paper(
                paper_id=_clean_arxiv_id(raw_id),
                title=title,
                authors=authors,
                year=int(published[:4]) if published[:4].isdigit() else None,
                abstract=summary,
                url=url,
                pdf_url=pdf_url,
                source="arxiv",
            )
        )
    return papers


def search_arxiv(
    query: str,
    limit: int = 5,
    timeout: float = 20.0,
    *,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[Paper]:
    params = urlencode(
        {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": limit,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
    )
    url = f"{ARXIV_API_URL}?{params}"
    owns_client = client is None
    active_client = client if client is not None else httpx.Client()
    try:
        for attempt in range(ARXIV_MAX_ATTEMPTS):
            response: httpx.Response | None = None
            try:
                response = active_client.get(
                    url,
                    headers={
                        "Accept": "application/atom+xml",
                        "User-Agent": ARXIV_USER_AGENT,
                    },
                    timeout=timeout,
                )
            except httpx.TimeoutException:
                error_code = "arxiv_search_timeout"
            except httpx.RequestError:
                error_code = "arxiv_search_network_error"
            else:
                if response.status_code == 429:
                    error_code = "arxiv_search_rate_limited"
                elif 500 <= response.status_code <= 599:
                    error_code = "arxiv_search_server_error"
                elif not response.is_success:
                    raise ArxivSearchError("arxiv_search_http_error")
                else:
                    try:
                        return parse_arxiv_feed(response.text)
                    except ET.ParseError:
                        raise ArxivSearchError(
                            "arxiv_search_invalid_response"
                        ) from None

            if attempt == ARXIV_MAX_ATTEMPTS - 1:
                raise ArxivSearchError(error_code)
            sleep(_retry_delay(response, attempt))
    finally:
        if owns_client:
            active_client.close()
    raise AssertionError("bounded arXiv retry loop exhausted")
