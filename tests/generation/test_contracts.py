import pytest
from pydantic import ValidationError

from paper_agent.generation.contracts import (
    GenerationAuthenticationError,
    GenerationConfigurationError,
    GenerationFailureMetadata,
    GenerationMessage,
    GenerationNetworkError,
    GenerationProvider,
    GenerationRateLimitError,
    GenerationRequestError,
    GenerationResponseError,
    GenerationServerError,
    GenerationTimeoutError,
    StructuredGeneration,
)
from paper_agent.modeling import StrictModel
from tests.generation.fakes import FakeGenerationProvider


class Answer(StrictModel):
    value: str


def generation(*, result: StrictModel | None = None) -> StructuredGeneration:
    return StructuredGeneration(
        result=result or Answer(value="ok"),
        model="qwen3.7-plus",
        attempts=1,
        elapsed_seconds=0.0,
    )


@pytest.mark.parametrize("role", ["system", "user", "assistant"])
def test_generation_message_accepts_supported_roles(role: str) -> None:
    assert GenerationMessage(role=role, content="text").role == role


@pytest.mark.parametrize("payload", [
    {"role": "tool", "content": "text"},
    {"role": "user", "content": ""},
    {"role": "user", "content": "text", "extra": True},
])
def test_generation_message_rejects_invalid_payload(payload: dict) -> None:
    with pytest.raises(ValidationError):
        GenerationMessage.model_validate(payload)


def test_structured_generation_has_only_flattened_optional_usage_fields() -> None:
    result = generation()
    assert result.prompt_tokens is None
    assert result.completion_tokens is None
    assert result.total_tokens is None
    assert "usage" not in type(result).model_fields
    with pytest.raises(AttributeError):
        _ = result.usage


@pytest.mark.parametrize("field,value", [
    ("attempts", 0),
    ("elapsed_seconds", -0.01),
    ("prompt_tokens", -1),
    ("completion_tokens", -1),
    ("total_tokens", -1),
])
def test_structured_generation_rejects_invalid_metrics(field: str, value: int | float) -> None:
    payload = generation().model_dump()
    payload[field] = value
    with pytest.raises(ValidationError):
        StructuredGeneration.model_validate(payload)


def test_failure_metadata_allows_zero_attempts_but_rejects_negative_metrics() -> None:
    assert GenerationFailureMetadata(attempts=0, elapsed_seconds=0).attempts == 0
    with pytest.raises(ValidationError):
        GenerationFailureMetadata(attempts=-1, elapsed_seconds=0)


@pytest.mark.parametrize(
    "error_type,code",
    [
        (GenerationConfigurationError, "generation_configuration_error"),
        (GenerationAuthenticationError, "generation_authentication_error"),
        (GenerationRequestError, "generation_request_error"),
        (GenerationTimeoutError, "generation_timeout_error"),
        (GenerationNetworkError, "generation_network_error"),
        (GenerationRateLimitError, "generation_rate_limit_error"),
        (GenerationServerError, "generation_server_error"),
        (GenerationResponseError, "generation_response_error"),
    ],
)
def test_typed_errors_expose_only_safe_details(error_type: type[Exception], code: str) -> None:
    metadata = GenerationFailureMetadata(attempts=2, elapsed_seconds=0.5)
    error = error_type(metadata=metadata)
    assert error.code == code
    assert error.metadata == metadata
    assert set(vars(error)) <= {"code", "metadata", "retry_delay_seconds"}
    rendered = repr(error)
    assert code in rendered
    for forbidden in ("api_key", "body", "raw_response", "provider_payload", "prompt"):
        assert not hasattr(error, forbidden)


def test_rate_limit_error_exposes_optional_non_negative_retry_delay() -> None:
    metadata = GenerationFailureMetadata(attempts=1, elapsed_seconds=0.1)
    error = GenerationRateLimitError(metadata=metadata, retry_delay_seconds=1.5)
    assert error.retry_delay_seconds == 1.5
    with pytest.raises(ValueError):
        GenerationRateLimitError(metadata=metadata, retry_delay_seconds=-1)


def test_fake_returns_queued_result_and_records_exact_call() -> None:
    queued = generation()
    fake: GenerationProvider = FakeGenerationProvider([queued])
    messages = [GenerationMessage(role="user", content="question")]
    result = fake.generate_structured(
        operation="paper_analysis",
        messages=messages,
        response_schema=Answer,
        timeout=3.0,
    )
    assert result == queued
    call = fake.calls[0]
    assert (call.operation, call.messages, call.response_schema, call.timeout) == (
        "paper_analysis", tuple(messages), Answer, 3.0
    )


def test_fake_raises_queued_typed_error_without_sleeping() -> None:
    error = GenerationTimeoutError(
        metadata=GenerationFailureMetadata(attempts=2, elapsed_seconds=3.0)
    )
    fake = FakeGenerationProvider([error])
    with pytest.raises(GenerationTimeoutError) as raised:
        fake.generate_structured(
            operation="survey", messages=[], response_schema=Answer, timeout=1.0
        )
    assert raised.value is error


def test_fake_rejects_empty_queue_and_wrong_schema() -> None:
    empty = FakeGenerationProvider([])
    with pytest.raises(AssertionError, match="queue is empty"):
        empty.generate_structured(
            operation="survey", messages=[], response_schema=Answer, timeout=1.0
        )

    class Other(StrictModel):
        value: str

    wrong = FakeGenerationProvider([generation(result=Other(value="no"))])
    with pytest.raises(AssertionError, match="schema"):
        wrong.generate_structured(
            operation="survey", messages=[], response_schema=Answer, timeout=1.0
        )
