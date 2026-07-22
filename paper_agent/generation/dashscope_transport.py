from collections.abc import Mapping, Sequence
import math
from typing import Any

import httpx
from pydantic import ConfigDict, Field, ValidationError

from paper_agent.generation.contracts import (
    GenerationAuthenticationError,
    GenerationFailureMetadata,
    GenerationMessage,
    GenerationNetworkError,
    GenerationRateLimitError,
    GenerationRequestError,
    GenerationResponseError,
    GenerationServerError,
    GenerationTimeoutError,
)
from paper_agent.modeling import StrictModel


class _ImmutableModel(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GenerationUsage(_ImmutableModel):
    prompt_tokens: int | None = Field(default=None, ge=0, strict=True)
    completion_tokens: int | None = Field(default=None, ge=0, strict=True)
    total_tokens: int | None = Field(default=None, ge=0, strict=True)


class GenerationHttpResponse(_ImmutableModel):
    content: str = Field(min_length=1)
    model: str = Field(min_length=1)
    usage: GenerationUsage | None = None


def _failure_metadata() -> GenerationFailureMetadata:
    return GenerationFailureMetadata(attempts=1, elapsed_seconds=0.0)


def _retry_delay(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        delay = float(value)
    except ValueError:
        return None
    if not math.isfinite(delay) or delay < 0:
        return None
    return delay


def _message_payload(
    message: GenerationMessage | Mapping[str, Any],
) -> dict[str, Any]:
    if isinstance(message, GenerationMessage):
        return message.model_dump()
    return dict(message)


def _parse_response(response: httpx.Response) -> GenerationHttpResponse:
    parsed: GenerationHttpResponse | None = None
    try:
        payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError
        choices = payload["choices"]
        if not isinstance(choices, list) or not choices:
            raise TypeError
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise TypeError
        message = first_choice["message"]
        if not isinstance(message, dict):
            raise TypeError

        usage_payload = payload.get("usage")
        if usage_payload is None:
            usage = None
        elif isinstance(usage_payload, dict):
            usage = GenerationUsage.model_validate(
                {
                    field: usage_payload[field]
                    for field in (
                        "prompt_tokens",
                        "completion_tokens",
                        "total_tokens",
                    )
                    if field in usage_payload
                }
            )
        else:
            raise TypeError

        parsed = GenerationHttpResponse.model_validate(
            {
                "content": message["content"],
                "model": payload["model"],
                "usage": usage,
            }
        )
    except (KeyError, TypeError, ValueError, ValidationError):
        pass
    if parsed is None:
        raise GenerationResponseError(metadata=_failure_metadata())
    return parsed


class DashScopeChatTransport:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def send(
        self,
        *,
        messages: Sequence[GenerationMessage | Mapping[str, Any]],
        model: str,
        api_key: str,
        base_url: str,
        timeout: float,
    ) -> GenerationHttpResponse:
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(float(timeout))
            or timeout <= 0
        ):
            raise ValueError("timeout must be a positive finite number")

        url = f"{base_url.removesuffix('/')}/chat/completions"
        error_type: type[GenerationTimeoutError | GenerationNetworkError] | None = None
        try:
            response = self._client.post(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": [_message_payload(message) for message in messages],
                    "response_format": {"type": "json_object"},
                },
                timeout=timeout,
            )
        except httpx.TimeoutException:
            error_type = GenerationTimeoutError
        except httpx.RequestError:
            error_type = GenerationNetworkError
        if error_type is not None:
            raise error_type(metadata=_failure_metadata())

        if response.status_code in (401, 403):
            raise GenerationAuthenticationError(metadata=_failure_metadata())
        if response.status_code in (400, 404, 422):
            raise GenerationRequestError(metadata=_failure_metadata())
        if response.status_code == 429:
            raise GenerationRateLimitError(
                metadata=_failure_metadata(), retry_delay_seconds=_retry_delay(response)
            )
        if 500 <= response.status_code <= 599:
            raise GenerationServerError(metadata=_failure_metadata())
        if not response.is_success:
            raise GenerationResponseError(metadata=_failure_metadata())

        return _parse_response(response)
