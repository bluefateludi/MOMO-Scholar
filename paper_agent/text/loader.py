from __future__ import annotations

from collections.abc import Callable

from paper_agent.schemas import Paper
from paper_agent.fulltext.service import AcquisitionOutcome, DocumentAcquirer

PrimaryTextLoader = Callable[[Paper], str]


def acquire_paper_document(
    acquirer: DocumentAcquirer, paper: Paper, *, no_pdf: bool
) -> AcquisitionOutcome:
    """Load a provenance-preserving document through the injected acquisition boundary."""
    return acquirer.acquire(paper, no_pdf=no_pdf)


def _abstract_text(paper: Paper) -> str:
    return f"Abstract\n{paper.abstract}".strip()


def load_paper_text(
    paper: Paper,
    no_pdf: bool = False,
    primary_loader: PrimaryTextLoader | None = None,
) -> str:
    if no_pdf or primary_loader is None:
        return _abstract_text(paper)
    try:
        text = primary_loader(paper).strip()
    except (OSError, ValueError):
        return _abstract_text(paper)
    return text or _abstract_text(paper)
