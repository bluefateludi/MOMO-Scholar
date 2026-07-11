from collections.abc import Sequence
from dataclasses import dataclass, field
import math
from typing import Protocol

import httpx

from paper_agent.vector.embedding import _validate_embedding_batch

# Official synchronous API: https://help.aliyun.com/zh/model-studio/text-embedding-synchronous-api
_BEIJING_EMBEDDINGS_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"


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
            raise EmbeddingTransportError("unsupported Bailian region")
        try:
            response = self.client.post(
                _BEIJING_EMBEDDINGS_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": model, "input": list(texts)},
                timeout=timeout,
            )
            response.raise_for_status()
        except httpx.TimeoutException:
            raise EmbeddingTimeoutError("embedding request timed out") from None
        except httpx.HTTPError:
            raise EmbeddingTransportError("embedding HTTP request failed") from None

        try:
            payload = response.json()
        except ValueError:
            raise EmbeddingTransportError("invalid embedding response") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise EmbeddingTransportError("invalid embedding response")

        indexed_vectors: list[tuple[int, list[float]]] = []
        seen_indices: set[int] = set()
        for item in payload["data"]:
            if not isinstance(item, dict):
                raise EmbeddingTransportError("invalid embedding response row")
            index = item.get("index")
            embedding = item.get("embedding")
            if (
                isinstance(index, bool)
                or not isinstance(index, int)
                or not isinstance(embedding, list)
                or index in seen_indices
            ):
                raise EmbeddingTransportError("invalid embedding response row")
            seen_indices.add(index)
            indexed_vectors.append((index, embedding))

        indexed_vectors.sort(key=lambda item: item[0])
        if [index for index, _ in indexed_vectors] != list(range(len(indexed_vectors))):
            raise EmbeddingTransportError("invalid embedding response indices")
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

        vectors = self.transport.embed(
            texts=texts,
            model=self.model,
            api_key=self.api_key,
            region=self.region,
            timeout=self.timeout,
        )
        return _validate_embedding_batch(texts, vectors)
