from collections.abc import Sequence

import pytest

from paper_agent.vector.bailian import (
    BailianTextEmbedder,
    EmbeddingTimeoutError,
    EmbeddingTransportError,
)
from paper_agent.vector.embedding import EmbeddingResponseError


class FakeTransport:
    def __init__(
        self,
        vectors: list[list[float]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.vectors = vectors or []
        self.error = error
        self.calls: list[dict[str, object]] = []

    def embed(
        self,
        *,
        texts: Sequence[str],
        model: str,
        api_key: str,
        region: str,
        timeout: float,
    ) -> list[list[float]]:
        self.calls.append(
            {
                "texts": list(texts),
                "model": model,
                "api_key": api_key,
                "region": region,
                "timeout": timeout,
            }
        )
        if self.error is not None:
            raise self.error
        return self.vectors


def test_defaults_and_batch_order_are_forwarded() -> None:
    transport = FakeTransport([[1.0, 0.0], [0.0, 1.0]])
    embedder = BailianTextEmbedder(api_key="sentinel-key", transport=transport)

    result = embedder.embed(["second", "first"])

    assert result == [[1.0, 0.0], [0.0, 1.0]]
    assert embedder.model_name == "text-embedding-v4"
    assert transport.calls == [
        {
            "texts": ["second", "first"],
            "model": "text-embedding-v4",
            "api_key": "sentinel-key",
            "region": "beijing",
            "timeout": 30.0,
        }
    ]


def test_empty_input_does_not_require_key_or_call_transport() -> None:
    transport = FakeTransport()
    embedder = BailianTextEmbedder(api_key=None, transport=transport)

    assert embedder.embed([]) == []
    assert transport.calls == []


def test_non_empty_input_requires_api_key_without_leaking_text() -> None:
    transport = FakeTransport()
    embedder = BailianTextEmbedder(api_key="  ", transport=transport)

    with pytest.raises(ValueError, match="API key") as exc_info:
        embedder.embed(["private paper text"])

    assert "private paper text" not in str(exc_info.value)
    assert transport.calls == []


def test_custom_model_region_and_timeout_are_forwarded() -> None:
    transport = FakeTransport([[1.0]])
    embedder = BailianTextEmbedder(
        api_key="key",
        transport=transport,
        model="custom-model",
        region="custom-region",
        timeout=4.5,
    )

    embedder.embed(["text"])

    assert embedder.model_name == "custom-model"
    assert transport.calls[0]["region"] == "custom-region"
    assert transport.calls[0]["timeout"] == 4.5


@pytest.mark.parametrize(
    "error",
    [EmbeddingTimeoutError("timed out"), EmbeddingTransportError("failed")],
)
def test_domain_transport_errors_propagate(error: Exception) -> None:
    embedder = BailianTextEmbedder(
        api_key="key",
        transport=FakeTransport(error=error),
    )

    with pytest.raises(type(error)) as exc_info:
        embedder.embed(["text"])

    assert exc_info.value is error


@pytest.mark.parametrize(
    "vectors",
    [[], [[1.0], [2.0, 3.0]]],
)
def test_invalid_response_count_or_dimensions_use_shared_validation(
    vectors: list[list[float]],
) -> None:
    texts = ["first"] if not vectors else ["first", "second"]
    embedder = BailianTextEmbedder(
        api_key="key",
        transport=FakeTransport(vectors),
    )

    with pytest.raises(EmbeddingResponseError):
        embedder.embed(texts)


def test_api_key_is_hidden_from_repr_and_exceptions() -> None:
    secret = "sentinel-super-secret"
    embedder = BailianTextEmbedder(
        api_key=secret,
        transport=FakeTransport(error=EmbeddingTransportError("provider failed")),
    )

    assert secret not in repr(embedder)
    with pytest.raises(EmbeddingTransportError) as exc_info:
        embedder.embed(["text"])
    assert secret not in str(exc_info.value)

@pytest.mark.parametrize("timeout", [0.0, -1.0, float("nan"), float("inf")])
def test_embedder_rejects_invalid_timeout_without_calling_transport(timeout: float) -> None:
    transport = FakeTransport([[1.0]])
    embedder = BailianTextEmbedder(api_key="key", transport=transport, timeout=timeout)
    with pytest.raises(ValueError, match="timeout"):
        embedder.embed(["text"])
    assert transport.calls == []
