from typing import Sequence, get_type_hints

import inspect

import pytest
from pydantic import ValidationError

from paper_agent.vector.contracts import Embedder, VectorStore
from paper_agent.vector.models import (
    VectorCandidate,
    VectorFilter,
    VectorRecordMetadata,
    VectorSearchResult,
)


def make_metadata() -> VectorRecordMetadata:
    return VectorRecordMetadata(
        paper_id="paper-1",
        chunk_id="paper-1:chunk-1",
        section="Methods",
        page=3,
        content_hash="abc123",
        embedding_model="text-embedding-v4",
    )


def test_vector_metadata_contains_required_provenance_and_is_frozen() -> None:
    metadata = make_metadata()

    assert metadata.model_dump() == {
        "paper_id": "paper-1",
        "chunk_id": "paper-1:chunk-1",
        "section": "Methods",
        "page": 3,
        "content_hash": "abc123",
        "embedding_model": "text-embedding-v4",
    }
    with pytest.raises(ValidationError):
        metadata.paper_id = "paper-2"


@pytest.mark.parametrize("score", [-0.01, 1.01])
def test_vector_search_result_rejects_score_outside_unit_interval(
    score: float,
) -> None:
    with pytest.raises(ValidationError):
        VectorSearchResult(
            chunk_id="paper-1:chunk-1",
            text="Relevant passage",
            score=score,
            metadata=make_metadata(),
        )


def test_vector_filter_accepts_only_typed_paper_id_and_is_frozen() -> None:
    filters = VectorFilter(paper_id="paper-1")

    assert filters.paper_id == "paper-1"
    assert VectorFilter().paper_id is None
    with pytest.raises(ValidationError):
        VectorFilter(paper_id="paper-1", sql="DROP TABLE vectors")
    with pytest.raises(ValidationError):
        filters.paper_id = "paper-2"


def test_vector_candidate_preserves_stable_chunk_identity_and_text() -> None:
    candidate = VectorCandidate(
        chunk_id="paper-1:chunk-1",
        paper_id="paper-1",
        text="Relevant passage",
        score=0.75,
        metadata=make_metadata(),
    )

    assert candidate.chunk_id == "paper-1:chunk-1"
    assert candidate.paper_id == "paper-1"
    assert candidate.text == "Relevant passage"
    assert candidate.score == 0.75
    with pytest.raises(ValidationError):
        candidate.score = 0.5


def test_search_result_rejects_chunk_id_that_disagrees_with_metadata() -> None:
    with pytest.raises(ValidationError, match="chunk_id must match metadata.chunk_id"):
        VectorSearchResult(
            chunk_id="paper-1:different",
            text="Relevant passage",
            score=0.75,
            metadata=make_metadata(),
        )


@pytest.mark.parametrize(
    ("chunk_id", "paper_id"),
    [("paper-1:different", "paper-1"), ("paper-1:chunk-1", "paper-2")],
)
def test_candidate_rejects_identity_that_disagrees_with_metadata(
    chunk_id: str, paper_id: str
) -> None:
    with pytest.raises(ValidationError, match="must match metadata"):
        VectorCandidate(
            chunk_id=chunk_id,
            paper_id=paper_id,
            text="Relevant passage",
            score=0.75,
            metadata=make_metadata(),
        )


@pytest.mark.parametrize(
    ("model", "data"),
    [
        (VectorRecordMetadata, make_metadata().model_dump()),
        (
            VectorSearchResult,
            {
                "chunk_id": "paper-1:chunk-1",
                "text": "Relevant passage",
                "score": 0.75,
                "metadata": make_metadata(),
            },
        ),
        (
            VectorCandidate,
            {
                "chunk_id": "paper-1:chunk-1",
                "paper_id": "paper-1",
                "text": "Relevant passage",
                "score": 0.75,
                "metadata": make_metadata(),
            },
        ),
    ],
)
def test_vector_contract_models_forbid_unknown_fields(model: type, data: dict) -> None:
    with pytest.raises(ValidationError):
        model(**data, database_expression="paper_id = 'paper-1'")


def assert_signature(
    method: object,
    parameters: list[tuple[str, inspect._ParameterKind]],
) -> None:
    signature = inspect.signature(method)
    assert [(item.name, item.kind) for item in signature.parameters.values()] == parameters


def test_contract_protocols_expose_exact_operation_signatures() -> None:
    positional = inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert isinstance(Embedder.model_name, property)
    assert_signature(Embedder.embed, [("self", positional), ("texts", positional)])
    assert isinstance(VectorStore.embedding_model, property)
    assert_signature(VectorStore.ensure_collection, [("self", positional), ("vector_size", positional)])
    assert_signature(VectorStore.upsert, [("self", positional), ("chunks", positional), ("embeddings", positional)])
    assert_signature(VectorStore.search, [("self", positional), ("query_embedding", positional), ("limit", positional), ("filters", positional)])
    assert inspect.signature(VectorStore.search).parameters["filters"].default is None
    assert_signature(VectorStore.delete_by_paper, [("self", positional), ("paper_id", positional)])



def test_embedder_protocol_is_runtime_checkable_with_structural_fake() -> None:
    class FakeEmbedder:
        @property
        def model_name(self) -> str:
            return "fake"

        def embed(self, texts: Sequence[str]) -> list[list[float]]:
            return [[1.0] for _ in texts]

    assert isinstance(FakeEmbedder(), Embedder)


def test_embedder_protocol_exposes_exact_type_contract() -> None:
    assert get_type_hints(Embedder.model_name.fget) == {"return": str}
    assert get_type_hints(Embedder.embed) == {
        "texts": Sequence[str],
        "return": list[list[float]],
    }


def test_vector_store_protocol_exposes_exact_type_contract() -> None:
    from paper_agent.schemas import Chunk

    assert get_type_hints(VectorStore.embedding_model.fget) == {"return": str}
    assert get_type_hints(VectorStore.ensure_collection) == {
        "vector_size": int,
        "return": type(None),
    }
    assert get_type_hints(VectorStore.upsert) == {
        "chunks": Sequence[Chunk],
        "embeddings": Sequence[Sequence[float]],
        "return": type(None),
    }
    assert get_type_hints(VectorStore.search) == {
        "query_embedding": Sequence[float],
        "limit": int,
        "filters": VectorFilter | None,
        "return": list[VectorSearchResult],
    }
    assert get_type_hints(VectorStore.delete_by_paper) == {
        "paper_id": str,

        "return": type(None),
    }


def test_vector_store_protocol_is_runtime_checkable_with_structural_fake() -> None:
    class FakeVectorStore:
        @property
        def embedding_model(self) -> str:
            return "fake"

        def ensure_collection(self, vector_size: int) -> None:
            return None

        def upsert(self, chunks: Sequence, embeddings: Sequence[Sequence[float]]) -> None:
            return None

        def search(
            self,
            query_embedding: Sequence[float],
            limit: int,
            filters: VectorFilter | None = None,
        ) -> list[VectorSearchResult]:
            return []

        def delete_by_paper(self, paper_id: str) -> None:
            return None

    assert isinstance(FakeVectorStore(), VectorStore)
