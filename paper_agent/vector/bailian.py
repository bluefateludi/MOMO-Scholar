from collections.abc import Sequence
from dataclasses import dataclass, field
import math
from typing import Protocol

import httpx

from paper_agent.vector.embedding import (
    EmbeddingResponseError,
    _validate_embedding_batch,
)

# Official synchronous API: https://help.aliyun.com/zh/model-studio/text-embedding-synchronous-api
_BEIJING_EMBEDDINGS_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
_TEXT_EMBEDDING_V4_BATCH_SIZE = 10


def _validate_timeout(timeout: float) -> None:
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(float(timeout))
        or timeout <= 0
    ):
        raise ValueError("timeout must be a positive finite number")


class EmbeddingTimeoutError(TimeoutError):
    """Raised when an embedding request exceeds its configured timeout."""


class EmbeddingTransportError(RuntimeError):
    """Raised when an embedding provider request or response is invalid."""


class EmbeddingNetworkError(EmbeddingTransportError):
    pass


class EmbeddingRateLimitError(EmbeddingTransportError):
    pass


class EmbeddingServerError(EmbeddingTransportError):
    pass


class EmbeddingAuthenticationError(EmbeddingTransportError):
    pass


class EmbeddingRequestError(EmbeddingTransportError):
    pass


class EmbeddingConfigurationError(EmbeddingTransportError):
    pass


class EmbeddingTransport(Protocol):
    def embed(
        self,
        *,
        texts: Sequence[str],
        model: str,
        api_key: str,
        region: str,
        timeout: float,
    ) -> list[list[float]]: ...


@dataclass(init=False)
class HttpxEmbeddingTransport:
    client: httpx.Client = field(repr=False)
    _owns_client: bool = field(repr=False)

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._owns_client = client is None
        self.client = client if client is not None else httpx.Client()

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "HttpxEmbeddingTransport":
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()

    def embed(
        self,
        *,
        texts: Sequence[str],
        model: str,
        api_key: str,
        region: str,
        timeout: float,
    ) -> list[list[float]]:
        _validate_timeout(timeout)
        if region != "beijing":
            raise EmbeddingConfigurationError("unsupported Bailian region")
        try:
            response = self.client.post(
                _BEIJING_EMBEDDINGS_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": model, "input": list(texts)},
                timeout=timeout,
            )
        except httpx.TimeoutException:
            raise EmbeddingTimeoutError("embedding request timed out") from None
        except httpx.RequestError:
            raise EmbeddingNetworkError("embedding network request failed") from None

        if response.status_code in (401, 403):
            raise EmbeddingAuthenticationError("embedding authentication failed")
        if response.status_code == 429:
            raise EmbeddingRateLimitError("embedding rate limit exceeded")
        if 500 <= response.status_code <= 599:
            raise EmbeddingServerError("embedding server request failed")
        if 400 <= response.status_code <= 499:
            raise EmbeddingRequestError("embedding request was rejected")

        try:
            payload = response.json()
        except ValueError:
            raise EmbeddingResponseError("invalid embedding response") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise EmbeddingResponseError("invalid embedding response")

        indexed_vectors: list[tuple[int, list[float]]] = []
        seen_indices: set[int] = set()
        for item in payload["data"]:
            if not isinstance(item, dict):
                raise EmbeddingResponseError("invalid embedding response row")
            index = item.get("index")
            embedding = item.get("embedding")
            if (
                isinstance(index, bool)
                or not isinstance(index, int)
                or not isinstance(embedding, list)
                or index in seen_indices
            ):
                raise EmbeddingResponseError("invalid embedding response row")
            seen_indices.add(index)
            indexed_vectors.append((index, embedding))

        indexed_vectors.sort(key=lambda item: item[0])
        if [index for index, _ in indexed_vectors] != list(range(len(indexed_vectors))):
            raise EmbeddingResponseError("invalid embedding response indices")
        return [embedding for _, embedding in indexed_vectors]


@dataclass
class BailianTextEmbedder:
    api_key: str | None = field(repr=False)
    transport: EmbeddingTransport = field(default_factory=HttpxEmbeddingTransport)
    model: str = "text-embedding-v4"
    region: str = "beijing"
    timeout: float = 30.0

    @property
    def model_name(self) -> str:
        return self.model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        _validate_timeout(self.timeout)
        if not self.api_key or not self.api_key.strip():
            raise ValueError("Bailian API key is required")

        batch_size = (
            _TEXT_EMBEDDING_V4_BATCH_SIZE
            if self.model == "text-embedding-v4"
            else len(texts)
        )
        vectors: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            vectors.extend(
                self.transport.embed(
                    texts=texts[start : start + batch_size],
                    model=self.model,
                    api_key=self.api_key,
                    region=self.region,
                    timeout=self.timeout,
                )
            )
        return _validate_embedding_batch(texts, vectors)
