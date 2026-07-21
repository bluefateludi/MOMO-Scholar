from paper_agent.observability.sanitize import sanitize_event_data


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
