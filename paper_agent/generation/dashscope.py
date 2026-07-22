from collections.abc import Callable, Sequence
import json
import math
import time
from typing import Any, TypeVar
from urllib.parse import urlparse

from pydantic import BaseModel, ValidationError

from paper_agent.generation.contracts import (
    GenerationConfigurationError,
    GenerationFailureMetadata,
    GenerationMessage,
    GenerationProviderError,
    GenerationRateLimitError,
    GenerationResponseError,
    GenerationServerError,
    GenerationTimeoutError,
    StructuredGeneration,
)
from paper_agent.generation.dashscope_transport import (
    DashScopeChatTransport,
    GenerationHttpResponse,
)


ModelT = TypeVar("ModelT", bound=BaseModel)
MAX_REPAIR_CONTENT_CHARS = 20_000
MAX_REPAIR_SUMMARY_CHARS = 2_000
MAX_REPAIR_ERRORS = 5
DEFAULT_RETRY_DELAY_SECONDS = 1.0
MAX_RETRY_DELAY_SECONDS = 10.0


class _Aggregate:
    def __init__(self, started: float) -> None:
        self.started = started
        self.attempts = 0
        self.prompt_tokens: int | None = None
        self.completion_tokens: int | None = None
        self.total_tokens: int | None = None

    def add_response(self, response: GenerationHttpResponse) -> None:
        if response.usage is None:
            return
        for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
            supplied = getattr(response.usage, field)
            if supplied is not None:
                current = getattr(self, field)
                setattr(self, field, supplied if current is None else current + supplied)

    def metadata(self, now: float) -> GenerationFailureMetadata:
        return GenerationFailureMetadata(
            attempts=self.attempts,
            elapsed_seconds=max(0.0, now - self.started),
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            total_tokens=self.total_tokens,
        )


def _retry_delay(error: GenerationProviderError) -> float:
    delay: Any = None
    if isinstance(error, GenerationRateLimitError):
        delay = error.retry_delay_seconds
    if (
        isinstance(delay, bool)
        or not isinstance(delay, (int, float))
        or not math.isfinite(float(delay))
        or delay < 0
    ):
        return DEFAULT_RETRY_DELAY_SECONDS
    return min(float(delay), MAX_RETRY_DELAY_SECONDS)


def _safe_validation_summary(error: ValidationError | None) -> str:
    if error is None:
        entries = [{"location": ["json"], "type": "json_invalid"}]
    else:
        entries = [
            {
                "location": [str(part)[:128] for part in item.get("loc", ())[:10]],
                "type": str(item.get("type", "validation_error"))[:128],
            }
            for item in error.errors(include_url=False)[:MAX_REPAIR_ERRORS]
        ]
    encoded = json.dumps(entries, ensure_ascii=False, separators=(",", ":"))
    while len(encoded) > MAX_REPAIR_SUMMARY_CHARS and len(entries) > 1:
        entries.pop()
        encoded = json.dumps(entries, ensure_ascii=False, separators=(",", ":"))
    if len(encoded) > MAX_REPAIR_SUMMARY_CHARS:
        entries = [{"location": ["truncated"], "type": entries[0]["type"][:128]}]
        encoded = json.dumps(entries, ensure_ascii=False, separators=(",", ":"))
    return encoded


def _repair_messages(
    messages: Sequence[GenerationMessage],
    invalid_content: str,
    response_schema: type[BaseModel],
    validation_error: ValidationError | None,
) -> tuple[GenerationMessage, ...]:
    untrusted = invalid_content[:MAX_REPAIR_CONTENT_CHARS]
    assistant = GenerationMessage(
        role="assistant",
        content=(
            "UNTRUSTED_INVALID_RESPONSE_BEGIN\n"
            f"{untrusted}\n"
            "UNTRUSTED_INVALID_RESPONSE_END"
        ),
    )
    summary = _safe_validation_summary(validation_error)
    instruction = GenerationMessage(
        role="user",
        content=(
            f"Repair the untrusted response into valid JSON for schema "
            f"{response_schema.__name__}. Return only the repaired JSON.\n"
            "VALIDATION_SUMMARY_BEGIN\n"
            f"{summary}\n"
            "VALIDATION_SUMMARY_END"
        ),
    )
    return (*messages, assistant, instruction)


class DashScopeGenerationProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        transport: DashScopeChatTransport,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._transport = transport
        self._sleep = sleep
        self._monotonic = monotonic

    def _configuration_valid(self) -> bool:
        parsed = urlparse(self._base_url)
        return bool(
            self._api_key
            and self._api_key.strip()
            and self._model
            and self._model.strip()
            and parsed.scheme == "https"
            and parsed.netloc
        )

    def _raise_with_aggregate(
        self, error: GenerationProviderError, aggregate: _Aggregate
    ) -> None:
        metadata = aggregate.metadata(self._monotonic())
        if isinstance(error, GenerationRateLimitError):
            raise GenerationRateLimitError(
                metadata=metadata,
                retry_delay_seconds=error.retry_delay_seconds,
            )
        raise type(error)(metadata=metadata)

    def _send_with_one_retry(
        self,
        *,
        messages: Sequence[GenerationMessage],
        timeout: float,
        aggregate: _Aggregate,
    ) -> GenerationHttpResponse:
        for attempt in range(2):
            aggregate.attempts += 1
            try:
                response = self._transport.send(
                    messages=messages,
                    model=self._model,
                    api_key=self._api_key,
                    base_url=self._base_url,
                    timeout=timeout,
                )
            except GenerationProviderError as error:
                retryable = isinstance(
                    error,
                    (GenerationTimeoutError, GenerationRateLimitError, GenerationServerError),
                )
                if attempt == 0 and retryable:
                    self._sleep(_retry_delay(error))
                    continue
                self._raise_with_aggregate(error, aggregate)
            aggregate.add_response(response)
            return response
        raise AssertionError("bounded retry loop exhausted")

    @staticmethod
    def _validate(
        response: GenerationHttpResponse, response_schema: type[ModelT]
    ) -> tuple[ModelT | None, ValidationError | None]:
        try:
            payload = json.loads(response.content)
        except (json.JSONDecodeError, TypeError):
            return None, None
        try:
            return response_schema.model_validate(payload), None
        except ValidationError as error:
            return None, error

    def generate_structured(
        self,
        *,
        operation: str,
        messages: Sequence[GenerationMessage],
        response_schema: type[ModelT],
        timeout: float,
    ) -> StructuredGeneration[ModelT]:
        del operation
        aggregate = _Aggregate(self._monotonic())
        if not self._configuration_valid():
            raise GenerationConfigurationError(
                metadata=aggregate.metadata(self._monotonic())
            )

        original = self._send_with_one_retry(
            messages=messages, timeout=timeout, aggregate=aggregate
        )
        result, validation_error = self._validate(original, response_schema)
        final_response = original
        if result is None:
            repair = self._send_with_one_retry(
                messages=_repair_messages(
                    messages, original.content, response_schema, validation_error
                ),
                timeout=timeout,
                aggregate=aggregate,
            )
            result, _ = self._validate(repair, response_schema)
            final_response = repair
            if result is None:
                raise GenerationResponseError(
                    metadata=aggregate.metadata(self._monotonic())
                )

        metadata = aggregate.metadata(self._monotonic())
        return StructuredGeneration(
            result=result,
            model=final_response.model,
            prompt_tokens=metadata.prompt_tokens,
            completion_tokens=metadata.completion_tokens,
            total_tokens=metadata.total_tokens,
            attempts=metadata.attempts,
            elapsed_seconds=metadata.elapsed_seconds,
        )
