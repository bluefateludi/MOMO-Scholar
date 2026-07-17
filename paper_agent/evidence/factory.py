from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass

from paper_agent.config import Settings
from paper_agent.vector import InMemoryVectorStore, VectorRetriever
from paper_agent.vector.bailian import (
    BailianTextEmbedder,
    EmbeddingTransport,
    HttpxEmbeddingTransport,
)

from .hybrid import HybridEvidenceRetriever
from .retriever import LexicalCandidateSource
from .vector_source import VectorCandidateSource


@dataclass(frozen=True, slots=True)
class RetrievalConfigurationError(ValueError):
    message: str
    error_code: str = "retrieval_configuration_error"

    def __post_init__(self) -> None:
        ValueError.__init__(self, self.message)


def _service(
    settings: Settings,
    *,
    lexical_source: LexicalCandidateSource,
    vector_source: VectorCandidateSource | None,
) -> HybridEvidenceRetriever:
    service = HybridEvidenceRetriever(
        lexical_source=lexical_source,
        vector_source=vector_source,
        requested_mode=settings.retrieval_mode,
        candidate_k=settings.retrieval_candidate_k,
        top_k=settings.retrieval_top_k,
        rrf_k=settings.retrieval_rrf_k,
    )
    return service


@contextmanager
def build_retrieval_service(
    settings: Settings,
    *,
    transport: EmbeddingTransport | None = None,
) -> Iterator[HybridEvidenceRetriever]:
    lexical_source = LexicalCandidateSource()
    api_key = settings.dashscope_api_key
    has_api_key = bool(api_key and api_key.strip())

    if settings.retrieval_mode == "lexical" or (
        settings.retrieval_mode == "auto" and not has_api_key
    ):
        yield _service(
            settings, lexical_source=lexical_source, vector_source=None
        )
        return

    if not has_api_key:
        raise RetrievalConfigurationError(
            "DASHSCOPE_API_KEY is required for hybrid retrieval"
        )

    with ExitStack() as stack:
        active_transport = transport
        if active_transport is None:
            active_transport = stack.enter_context(HttpxEmbeddingTransport())
        embedder = BailianTextEmbedder(
            api_key=api_key,
            model=settings.bailian_embedding_model,
            region=settings.bailian_region,
            transport=active_transport,
        )
        store = InMemoryVectorStore(
            embedding_model=settings.bailian_embedding_model
        )
        retriever = VectorRetriever(embedder=embedder, store=store)
        vector_source = VectorCandidateSource(retriever)
        yield _service(
            settings,
            lexical_source=lexical_source,
            vector_source=vector_source,
        )
