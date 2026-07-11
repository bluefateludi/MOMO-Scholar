import math

import pytest

from paper_agent.vector.embedding import (
    EmbeddingResponseError,
    _validate_embedding_batch,
)


def test_empty_input_returns_empty_batch() -> None:
    assert _validate_embedding_batch([], []) == []


def test_rejects_input_output_count_mismatch_without_exposing_input() -> None:
    secret_text = "private paper text"

    with pytest.raises(EmbeddingResponseError) as exc_info:
        _validate_embedding_batch([secret_text], [])

    assert secret_text not in str(exc_info.value)


def test_rejects_empty_vector() -> None:
    with pytest.raises(EmbeddingResponseError, match="empty"):
        _validate_embedding_batch(["first"], [[]])


def test_rejects_inconsistent_vector_dimensions() -> None:
    with pytest.raises(EmbeddingResponseError, match="dimension"):
        _validate_embedding_batch(
            ["first", "second"],
            [[1.0, 2.0], [3.0]],
        )


@pytest.mark.parametrize("invalid_value", [True, False, "1", None, object()])
def test_rejects_boolean_and_non_numeric_values(invalid_value: object) -> None:
    with pytest.raises(EmbeddingResponseError, match="numeric"):
        _validate_embedding_batch(["first"], [[invalid_value]])


@pytest.mark.parametrize("invalid_value", [math.nan, math.inf, -math.inf])
def test_rejects_non_finite_values(invalid_value: float) -> None:
    with pytest.raises(EmbeddingResponseError, match="finite"):
        _validate_embedding_batch(["first"], [[invalid_value]])


def test_rejects_numeric_value_too_large_for_float_conversion() -> None:
    with pytest.raises(EmbeddingResponseError, match="numeric"):
        _validate_embedding_batch(["first"], [[10**1000]])


def test_valid_batch_preserves_order_and_converts_values_to_float() -> None:
    result = _validate_embedding_batch(
        ["first", "second"],
        [[1, 2.5], [-3, 4]],
    )

    assert result == [[1.0, 2.5], [-3.0, 4.0]]
    assert all(type(value) is float for row in result for value in row)
