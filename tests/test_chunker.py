from paper_agent.schemas import Paper
from paper_agent.text.loader import load_paper_text


def _paper() -> Paper:
    return Paper(
        paper_id="arxiv:2401.00001",
        title="Example",
        authors=[],
        year=2024,
        abstract="Evidence-grounded paper agents cite source text.",
        url="https://arxiv.org/abs/2401.00001",
        source="arxiv",
    )


def test_load_paper_text_uses_abstract_in_no_pdf_mode():
    assert load_paper_text(_paper(), no_pdf=True) == (
        "Abstract\nEvidence-grounded paper agents cite source text."
    )


def test_load_paper_text_falls_back_when_primary_loader_fails():
    def failing_loader(paper: Paper) -> str:
        raise OSError("PDF unavailable")

    assert load_paper_text(_paper(), primary_loader=failing_loader) == (
        "Abstract\nEvidence-grounded paper agents cite source text."
    )
