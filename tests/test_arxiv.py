from pathlib import Path

from paper_agent.retrieval.arxiv import parse_arxiv_feed


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
