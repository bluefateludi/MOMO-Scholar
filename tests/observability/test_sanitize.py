import pytest

from paper_agent.observability.sanitize import (
    TraceDataPolicyError,
    sanitize_event_data,
    validate_event_attributes,
)


def test_sanitize_event_data_removes_secrets_and_raw_payloads() -> None:
    result = sanitize_event_data(
        {
            "Authorization": "Bearer secret-value",
            "raw_response": {"choices": ["private"]},
            "stage": "generation",
            "prompt_tokens": 42,
            "message": "failed for secret-value",
        },
        secrets=("secret-value",),
    )

    assert result == {
        "Authorization": "[REDACTED]",
        "raw_response": "[REDACTED]",
        "stage": "generation",
        "prompt_tokens": 42,
        "message": "failed for [REDACTED]",
    }


def test_sanitize_event_data_recurses_without_mutating_input() -> None:
    value = {
        "nested": [
            {"Api_Key": "hidden", "detail": "token=known-secret"},
            [True, None, 3, 2.5],
        ],
        "RAW_REQUEST": {"messages": ["private"]},
    }

    result = sanitize_event_data(value, secrets=("known-secret", ""))

    assert result == {
        "nested": [
            {"Api_Key": "[REDACTED]", "detail": "token=[REDACTED]"},
            [True, None, 3, 2.5],
        ],
        "RAW_REQUEST": "[REDACTED]",
    }
    assert value["nested"][0]["Api_Key"] == "hidden"
    assert value["RAW_REQUEST"] == {"messages": ["private"]}


def test_sanitize_event_data_describes_unsupported_type_without_rendering_it() -> None:
    class Dangerous:
        def __str__(self) -> str:
            raise AssertionError("must not call str")

        def __repr__(self) -> str:
            raise AssertionError("must not call repr")

    result = sanitize_event_data(Dangerous(), secrets=())

    assert result == (
        "[UNSUPPORTED_TYPE:tests.observability.test_sanitize."
        "test_sanitize_event_data_describes_unsupported_type_without_rendering_it."
        "<locals>.Dangerous]"
    )


@pytest.mark.parametrize(
    'key',
    [
        'prompt',
        'prompt_text',
        'response',
        'abstract',
        'pdf_text',
        'evidence_quote',
        'authorization',
        'cookie',
        'stack_trace',
        'exception_message',
        'endpoint_url',
    ],
)
def test_trace_events_reject_prohibited_keys(key: str) -> None:
    with pytest.raises(TraceDataPolicyError):
        validate_event_attributes(
            'paper_agent.pipeline.analysis',
            {key: 'private'},
        )


def test_trace_attributes_redact_known_secret_and_reject_nested_payload() -> None:
    assert validate_event_attributes(
        'paper_agent.pipeline.analysis',
        {'model_name': 'model-runtime-secret'},
        secrets=('runtime-secret',),
    ) == {'model_name': 'model-[REDACTED]'}
    with pytest.raises(TraceDataPolicyError):
        validate_event_attributes(
            'paper_agent.pipeline.analysis',
            {'details': {'cookie': 'private'}},
        )
    with pytest.raises(TraceDataPolicyError, match='not allowlisted'):
        validate_event_attributes(
            'paper_agent.pipeline.analysis',
            {'novel_scalar': 'content'},
        )
