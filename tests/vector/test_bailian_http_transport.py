from collections.abc import Callable

import httpx
import pytest

from paper_agent.vector.bailian import (
    EmbeddingTimeoutError,
    EmbeddingTransportError,
    HttpxEmbeddingTransport,
)

_TEST_CLIENTS: list[httpx.Client] = []


@pytest.fixture(autouse=True)
def close_test_clients() -> object:
    try:
        yield
    finally:
        for client in _TEST_CLIENTS:
            if not client.is_closed:
                client.close()
        _TEST_CLIENTS.clear()


def _transport(handler: Callable[[httpx.Request], httpx.Response]) -> HttpxEmbeddingTransport:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    _TEST_CLIENTS.append(client)
    return HttpxEmbeddingTransport(client=client)


def _embed(transport: HttpxEmbeddingTransport) -> list[list[float]]:
    return transport.embed(
        texts=["second", "first"],
        model="text-embedding-v4",
        api_key="sentinel-key",
        region="beijing",
        timeout=7.25,
    )


def test_posts_official_beijing_contract_with_explicit_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL(
            "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
        )
        assert request.method == "POST"
        assert request.headers["Authorization"] == "Bearer sentinel-key"
        assert request.headers["Content-Type"].startswith("application/json")
        assert request.extensions["timeout"] == {
            "connect": 7.25,
            "read": 7.25,
            "write": 7.25,
            "pool": 7.25,
        }
        assert request.read()
        assert __import__("json").loads(request.content) == {
            "model": "text-embedding-v4",
            "input": ["second", "first"],
        }
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 0, "embedding": [1.0, 0.0]},
                    {"index": 1, "embedding": [0.0, 1.0]},
                ]
            },
        )

    assert _embed(_transport(handler)) == [[1.0, 0.0], [0.0, 1.0]]


def test_response_rows_are_sorted_by_index() -> None:
    transport = _transport(
        lambda _: httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.0, 1.0]},
                    {"index": 0, "embedding": [1.0, 0.0]},
                ]
            },
        )
    )

    assert _embed(transport) == [[1.0, 0.0], [0.0, 1.0]]


def test_httpx_timeout_is_mapped_without_leaking_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("sentinel-key", request=request)

    with pytest.raises(EmbeddingTimeoutError) as exc_info:
        _embed(_transport(handler))

    assert "sentinel-key" not in str(exc_info.value)


@pytest.mark.parametrize("status", [400, 401, 500, 503])
def test_http_errors_are_mapped(status: int) -> None:
    transport = _transport(
        lambda _: httpx.Response(status, json={"message": "sentinel-key"})
    )

    with pytest.raises(EmbeddingTransportError) as exc_info:
        _embed(transport)

    assert "sentinel-key" not in str(exc_info.value)


def test_api_error_payload_is_mapped() -> None:
    transport = _transport(
        lambda _: httpx.Response(
            200,
            json={"code": "InvalidParameter", "message": "sentinel-key"},
        )
    )

    with pytest.raises(EmbeddingTransportError) as exc_info:
        _embed(transport)

    assert "sentinel-key" not in str(exc_info.value)


def test_non_json_response_is_mapped() -> None:
    transport = _transport(
        lambda _: httpx.Response(200, content=b"not-json")
    )

    with pytest.raises(EmbeddingTransportError, match="response"):
        _embed(transport)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"data": None},
        {"data": [{}]},
        {"data": [{"index": 0}]},
        {"data": [{"embedding": [1.0]}]},
        {"data": [{"index": "0", "embedding": [1.0]}]},
        {"data": [{"index": True, "embedding": [1.0]}]},
        {"data": [{"index": 0, "embedding": "invalid"}]},
        {"data": [{"index": 0, "embedding": [1.0]}, {"index": 0, "embedding": [2.0]}]},
    ],
)
def test_missing_fields_and_invalid_rows_are_mapped(payload: object) -> None:
    transport = _transport(lambda _: httpx.Response(200, json=payload))

    with pytest.raises(EmbeddingTransportError, match="response"):
        _embed(transport)


def test_unsupported_region_is_rejected_without_request() -> None:
    called = False

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"data": []})

    transport = _transport(handler)
    with pytest.raises(EmbeddingTransportError, match="region"):
        transport.embed(
            texts=["text"],
            model="text-embedding-v4",
            api_key="key",
            region="hangzhou",
            timeout=30.0,
        )

    assert called is False

def test_default_owned_client_can_be_closed_and_used_as_context_manager() -> None:
    transport = HttpxEmbeddingTransport()
    owned_client = transport.client
    with transport as entered:
        assert entered is transport
        assert owned_client.is_closed is False
    assert owned_client.is_closed is True
    transport.close()


def test_close_does_not_close_injected_client() -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    try:
        transport = HttpxEmbeddingTransport(client=client)
        transport.close()
        assert client.is_closed is False
    finally:
        client.close()


@pytest.mark.parametrize("timeout", [0.0, -1.0, float("nan"), float("inf")])
def test_http_transport_rejects_invalid_timeout_before_request(timeout: float) -> None:
    called = False
    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"data": []})
    transport = _transport(handler)
    with pytest.raises(ValueError, match="timeout"):
        transport.embed(texts=["text"], model="text-embedding-v4", api_key="key", region="beijing", timeout=timeout)
    assert called is False
