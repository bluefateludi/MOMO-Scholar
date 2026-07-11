from paper_agent.retrieval.normalize import dedupe_papers
from paper_agent.schemas import Paper


def test_dedupe_papers_prefers_first_seen_id():
    first = Paper(
        paper_id="arxiv:2401.00001",
        title="Same Title",
        authors=["A"],
        year=2024,
        abstract="abstract",
        url="https://arxiv.org/abs/2401.00001",
        source="arxiv",
    )
    duplicate = first.model_copy(update={"paper_id": "s2:abc"})
    assert dedupe_papers([first, duplicate]) == [first]
