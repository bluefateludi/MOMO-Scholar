from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel

from paper_agent.generation.contracts import (
    GenerationMessage,
    GenerationProviderError,
    StructuredGeneration,
)


ModelT = TypeVar("ModelT", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class GenerationCall:
    operation: str
    messages: tuple[GenerationMessage, ...]
    response_schema: type[BaseModel]
    timeout: float


class FakeGenerationProvider:
    def __init__(self, queued: Sequence[StructuredGeneration[Any] | GenerationProviderError]) -> None:
        self._queued = deque(queued)
        self.calls: list[GenerationCall] = []

    def generate_structured(
        self,
        *,
        operation: str,
        messages: Sequence[GenerationMessage],
        response_schema: type[ModelT],
        timeout: float,
    ) -> StructuredGeneration[ModelT]:
        self.calls.append(
            GenerationCall(operation, tuple(messages), response_schema, timeout)
        )
        if not self._queued:
            raise AssertionError("fake generation queue is empty")
        queued = self._queued.popleft()
        if isinstance(queued, GenerationProviderError):
            raise queued
        if not isinstance(queued.result, response_schema):
            raise AssertionError(
                "queued result schema does not match requested response schema"
            )
        return queued
