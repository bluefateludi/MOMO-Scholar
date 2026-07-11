from __future__ import annotations

import re

from paper_agent.schemas import Paper


def title_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def dedupe_papers(papers: list[Paper]) -> list[Paper]:
    seen: set[str] = set()
    result: list[Paper] = []
    for paper in papers:
        key = title_key(paper.title)
        if key in seen:
            continue
        seen.add(key)
        result.append(paper)
    return result
