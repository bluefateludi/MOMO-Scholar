import json

import httpx
import pytest

from paper_agent.generation import (
    DashScopeChatTransport,
    GenerationAuthenticationError,
    GenerationNetworkError,
    GenerationRateLimitError,
    GenerationRequestError,
    GenerationResponseError,
    GenerationServerError,
    GenerationTimeoutError,
)


MESSAGES = [
    {"role": "system", "content": "Return JSON."},
    {"role": "user", "content": "Summarize the evidence."},
]


def make_transport(handler) -> DashScopeChatTransport:
    return DashScopeChatTransport(
        httpx.Client(transport=httpx.MockTransport(handler))
    )


def send(transport: DashScopeChatTransport):
    return transport.send(
        messages=MESSAGES,
        model="qwen3.7-plus",
        api_key="top-secret-key",
        base_url="https://dashscope.example/compatible-mode/v1/",
        timeout=7.25,
    )


def test_posts_exact_chat_request_and_parses_response_with_usage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == (
            "https://dashscope.example/compatible-mode/v1/chat/completions"
        )
        assert request.headers["authorization"] == "Bearer top-secret-key"
        assert request.headers["content-type"] == "application/json"
        assert json.loads(request.content) == {
            "model": "qwen3.7-plus",
            "messages": MESSAGES,
            "response_format": {"type": "json_object"},
        }
        assert request.extensions["timeout"] == {
            "connect": 7.25,
            "read": 7.25,
            "write": 7.25,
            "pool": 7.25,
        }
        return httpx.Response(
            200,
            json={
                "model": "qwen3.7-plus-2026-07-01",
                "choices": [{"message": {"content": '{"answer":"ok"}'}}],
                "usage": {
                    "prompt_tokens": 11,
                    "completion_tokens": 5,
                    "total_tokens": 16,
                },
            },
        )

    response = send(make_transport(handler))

    assert response.content == '{"answer":"ok"}'
    assert response.model == "qwen3.7-plus-2026-07-01"
    assert response.usage is not None
    assert response.usage.prompt_tokens == 11
    assert response.usage.completion_tokens == 5
    assert response.usage.total_tokens == 16


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({}, None),
        ({"usage": {}}, (None, None, None)),
        ({"usage": {"prompt_tokens": 4}}, (4, None, None)),
    ],
)
def test_usage_is_optional_and_preserves_partial_integer_fields(payload, expected) -> None:
    envelope = {
        "model": "qwen3.7-plus",
        "choices": [{"message": {"content": "{}"}}],
        **payload,
    }
    response = send(make_transport(lambda _: httpx.Response(200, json=envelope)))
    if expected is None:
        assert response.usage is None
    else:
        assert response.usage is not None
        assert (
            response.usage.prompt_tokens,
            response.usage.completion_tokens,
            response.usage.total_tokens,
        ) == expected


@pytest.mark.parametrize(
    "status,error_type",
    [
        (401, GenerationAuthenticationError),
        (403, GenerationAuthenticationError),
        (400, GenerationRequestError),
        (404, GenerationRequestError),
        (422, GenerationRequestError),
        (500, GenerationServerError),
        (599, GenerationServerError),
    ],
)
def test_maps_http_status_without_leaking_key_or_body(status, error_type) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, text="raw provider body top-secret-key")

    with pytest.raises(error_type) as caught:
        send(make_transport(handler))

    assert calls == 1
    assert caught.value.metadata.attempts == 1
    assert "top-secret-key" not in str(caught.value)
    assert "raw provider body" not in str(caught.value)
    assert "top-secret-key" not in repr(caught.value)
    assert "raw provider body" not in repr(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize(
    "header,expected",
    [("2", 2.0), ("1.5", 1.5), ("-1", None), ("NaN", None), ("soon", None)],
)
def test_rate_limit_safely_parses_delta_seconds_retry_after(header, expected) -> None:
    transport = make_transport(
        lambda _: httpx.Response(429, headers={"Retry-After": header})
    )
    with pytest.raises(GenerationRateLimitError) as caught:
        send(transport)
    assert caught.value.retry_delay_seconds == expected
    assert caught.value.metadata.attempts == 1


@pytest.mark.parametrize(
    "error,error_type",
    [
        (httpx.ReadTimeout("late"), GenerationTimeoutError),
        (httpx.ConnectError("offline"), GenerationNetworkError),
    ],
)
def test_maps_request_exceptions_once(error, error_type) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise error

    with pytest.raises(error_type) as caught:
        send(make_transport(handler))
    assert calls == 1
    assert caught.value.metadata.attempts == 1
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json=[]),
        httpx.Response(200, json={}),
        httpx.Response(200, json={"model": "qwen", "choices": []}),
        httpx.Response(
            200, json={"model": "qwen", "choices": [{"message": {}}]}
        ),
        httpx.Response(
            200,
            json={"model": "qwen", "choices": [{"message": {"content": 3}}]},
        ),
        httpx.Response(
            200,
            json={
                "model": "qwen",
                "choices": [{"message": {"content": "{}"}}],
                "usage": {"prompt_tokens": "4"},
            },
        ),
    ],
)
def test_maps_invalid_json_or_envelope_to_response_error(response) -> None:
    with pytest.raises(GenerationResponseError) as caught:
        send(make_transport(lambda _: response))
    assert caught.value.metadata.attempts == 1
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), True])
def test_rejects_invalid_timeout_before_sending(timeout) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    transport = make_transport(handler)
    with pytest.raises(ValueError, match="timeout"):
        transport.send(
            messages=MESSAGES,
            model="qwen3.7-plus",
            api_key="top-secret-key",
            base_url="https://dashscope.example/v1",
            timeout=timeout,
        )
    assert calls == 0
