from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from urllib.parse import urlencode

import httpx

from paper_agent.schemas import Paper

ARXIV_API_URL = "https://export.arxiv.org/api/query"
ATOM = {"atom": "http://www.w3.org/2005/Atom"}


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


def search_arxiv(query: str, limit: int = 5, timeout: float = 20.0) -> list[Paper]:
    params = urlencode(
        {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": limit,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
    )
    response = httpx.get(f"{ARXIV_API_URL}?{params}", timeout=timeout)
    response.raise_for_status()
    return parse_arxiv_feed(response.text)
