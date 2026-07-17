import pytest

from paper_agent.config import Settings
from paper_agent.evidence import factory as factory_module
from paper_agent.evidence.factory import (
    RetrievalConfigurationError,
    build_retrieval_service,
)


class FakeTransport:
    def __init__(self) -> None:
        self.enter_calls = 0
        self.closed = False

    def embed(self, **kwargs):
        raise AssertionError("embed must not be called during assembly")

    def __enter__(self):
        self.enter_calls += 1
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.closed = True


@pytest.mark.parametrize("key", [None, "", "   "])
def test_auto_without_nonblank_key_is_lexical_and_constructs_no_transport(
    key, monkeypatch
) -> None:
    monkeypatch.setattr(
        factory_module,
        "HttpxEmbeddingTransport",
        lambda: pytest.fail("transport constructed"),
    )
    with build_retrieval_service(
        Settings(retrieval_mode="auto", dashscope_api_key=key)
    ) as service:
        assert service.requested_mode == "auto"
        assert service.vector_source is None


def test_lexical_with_key_never_touches_any_transport(monkeypatch) -> None:
    borrowed = FakeTransport()
    monkeypatch.setattr(
        factory_module,
        "HttpxEmbeddingTransport",
        lambda: pytest.fail("production transport constructed"),
    )
    with build_retrieval_service(
        Settings(retrieval_mode="lexical", dashscope_api_key="key"),
        transport=borrowed,
    ) as service:
        assert service.requested_mode == "lexical"
        assert service.vector_source is None
    assert borrowed.enter_calls == 0
    assert borrowed.closed is False


@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        ("requested_mode", "hybrid"),
        ("vector_source", object()),
    ],
)
def test_factory_service_configuration_observation_is_read_only(
    attribute, value
) -> None:
    with build_retrieval_service(
        Settings(retrieval_mode="lexical")
    ) as service:
        with pytest.raises(AttributeError):
            setattr(service, attribute, value)


@pytest.mark.parametrize("key", [None, "", "   "])
def test_forced_hybrid_without_nonblank_key_is_configuration_error(key) -> None:
    with pytest.raises(
        RetrievalConfigurationError, match="DASHSCOPE_API_KEY"
    ) as exc_info:
        with build_retrieval_service(
            Settings(retrieval_mode="hybrid", dashscope_api_key=key)
        ):
            pytest.fail("factory must not yield")
    assert exc_info.value.error_code == "retrieval_configuration_error"


def test_default_path_closes_owned_transport_on_success(monkeypatch) -> None:
    transport = FakeTransport()
    monkeypatch.setattr(factory_module, "HttpxEmbeddingTransport", lambda: transport)
    with build_retrieval_service(
        Settings(retrieval_mode="auto", dashscope_api_key="key")
    ) as service:
        assert service.vector_source is not None
        assert transport.closed is False
    assert transport.closed is True


def test_default_path_closes_owned_transport_when_consumer_raises(monkeypatch) -> None:
    transport = FakeTransport()
    monkeypatch.setattr(factory_module, "HttpxEmbeddingTransport", lambda: transport)
    with pytest.raises(RuntimeError, match="consumer"):
        with build_retrieval_service(
            Settings(retrieval_mode="hybrid", dashscope_api_key="key")
        ):
            raise RuntimeError("consumer")
    assert transport.closed is True


def test_borrowed_transport_is_never_entered_or_closed() -> None:
    transport = FakeTransport()
    with build_retrieval_service(
        Settings(retrieval_mode="hybrid", dashscope_api_key="key"),
        transport=transport,
    ) as service:
        assert service.vector_source is not None
    assert transport.enter_calls == 0
    assert transport.closed is False


def test_assembly_error_closes_owned_transport(monkeypatch) -> None:
    sentinel = RuntimeError("assembly")
    transport = FakeTransport()
    monkeypatch.setattr(factory_module, "HttpxEmbeddingTransport", lambda: transport)
    monkeypatch.setattr(
        factory_module,
        "BailianTextEmbedder",
        lambda **kwargs: (_ for _ in ()).throw(sentinel),
    )
    with pytest.raises(RuntimeError) as exc_info:
        with build_retrieval_service(
            Settings(retrieval_mode="hybrid", dashscope_api_key="key")
        ):
            pytest.fail("factory must not yield")
    assert exc_info.value is sentinel
    assert transport.enter_calls == 1
    assert transport.closed is True


def test_assembly_error_does_not_close_borrowed_transport(monkeypatch) -> None:
    sentinel = RuntimeError("assembly")
    transport = FakeTransport()
    monkeypatch.setattr(
        factory_module,
        "BailianTextEmbedder",
        lambda **kwargs: (_ for _ in ()).throw(sentinel),
    )
    with pytest.raises(RuntimeError) as exc_info:
        with build_retrieval_service(
            Settings(retrieval_mode="hybrid", dashscope_api_key="key"),
            transport=transport,
        ):
            pytest.fail("factory must not yield")
    assert exc_info.value is sentinel
    assert transport.enter_calls == 0
    assert transport.closed is False


def test_factory_forwards_settings_and_dependencies(monkeypatch) -> None:
    recorded = {}
    transport = FakeTransport()

    class RecordingEmbedder:
        def __init__(self, *, api_key, model, region, transport):
            recorded["embedder"] = (api_key, model, region, transport)
            recorded["embedder_instance"] = self

    class RecordingStore:
        def __init__(self, *, embedding_model):
            recorded["store_model"] = embedding_model
            recorded["store_instance"] = self

    class RecordingRetriever:
        def __init__(self, *, embedder, store):
            recorded["retriever"] = (embedder, store)
            recorded["retriever_instance"] = self

    class RecordingVectorSource:
        def __init__(self, retriever):
            recorded["vector_retriever"] = retriever
            recorded["vector_source_instance"] = self

    class RecordingLexicalSource:
        pass

    class RecordingService:
        def __init__(
            self,
            *,
            lexical_source,
            vector_source,
            requested_mode,
            candidate_k,
            top_k,
            rrf_k,
        ):
            recorded["service_instance"] = self
            recorded["service"] = (
                lexical_source,
                vector_source,
                requested_mode,
                candidate_k,
                top_k,
                rrf_k,
            )

    monkeypatch.setattr(factory_module, "LexicalCandidateSource", RecordingLexicalSource)
    monkeypatch.setattr(factory_module, "BailianTextEmbedder", RecordingEmbedder)
    monkeypatch.setattr(factory_module, "InMemoryVectorStore", RecordingStore)
    monkeypatch.setattr(factory_module, "VectorRetriever", RecordingRetriever)
    monkeypatch.setattr(factory_module, "VectorCandidateSource", RecordingVectorSource)
    monkeypatch.setattr(factory_module, "HybridEvidenceRetriever", RecordingService)
    settings = Settings(
        retrieval_mode="hybrid",
        dashscope_api_key="secret",
        bailian_embedding_model="text-embedding-v4",
        bailian_region="beijing",
        retrieval_candidate_k=21,
        retrieval_top_k=7,
        retrieval_rrf_k=42,
    )
    with build_retrieval_service(settings, transport=transport):
        pass
    assert recorded["embedder"] == (
        "secret",
        "text-embedding-v4",
        "beijing",
        transport,
    )
    assert recorded["store_model"] == "text-embedding-v4"
    assert recorded["retriever"] == (
        recorded["embedder_instance"],
        recorded["store_instance"],
    )
    assert recorded["vector_retriever"] is recorded["retriever_instance"]
    lexical, vector, mode, candidate_k, top_k, rrf_k = recorded["service"]
    assert lexical.__class__ is RecordingLexicalSource
    assert vector is recorded["vector_source_instance"]
    assert (mode, candidate_k, top_k, rrf_k) == ("hybrid", 21, 7, 42)
