import math
from collections.abc import Sequence


class EmbeddingResponseError(ValueError):
    """Raised when an embedding provider returns an invalid vector batch."""


def _validate_embedding_batch(
    texts: Sequence[str],
    vectors: Sequence[Sequence[float]],
) -> list[list[float]]:
    """Validate and normalize an embedding response without exposing inputs."""
    if len(vectors) != len(texts):
        raise EmbeddingResponseError("embedding response count does not match input count")
    if not texts:
        return []

    normalized: list[list[float]] = []
    vector_size: int | None = None
    for vector in vectors:
        if not vector:
            raise EmbeddingResponseError("embedding response contains an empty vector")
        if vector_size is None:
            vector_size = len(vector)
        elif len(vector) != vector_size:
            raise EmbeddingResponseError("embedding response dimensions are inconsistent")

        row: list[float] = []
        for value in vector:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise EmbeddingResponseError(
                    "embedding response values must be numeric"
                )
            try:
                normalized_value = float(value)
            except OverflowError:
                raise EmbeddingResponseError(
                    "embedding response numeric value cannot be represented as a float"
                ) from None
            if not math.isfinite(normalized_value):
                raise EmbeddingResponseError(
                    "embedding response values must be finite"
                )
            row.append(normalized_value)
        normalized.append(row)

    return normalized
