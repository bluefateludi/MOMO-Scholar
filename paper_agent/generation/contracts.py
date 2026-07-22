from collections.abc import Sequence
import math
from typing import Generic, Literal, Protocol, TypeVar

from pydantic import BaseModel, Field

from paper_agent.modeling import StrictModel


ModelT = TypeVar("ModelT", bound=BaseModel)


class GenerationMessage(StrictModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1)


class StructuredGeneration(StrictModel, Generic[ModelT]):
    result: ModelT
    model: str = Field(min_length=1)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    attempts: int = Field(ge=1)
    elapsed_seconds: float = Field(ge=0.0)


class GenerationFailureMetadata(StrictModel):
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    attempts: int = Field(ge=0)
    elapsed_seconds: float = Field(ge=0.0)


class GenerationProvider(Protocol):
    def generate_structured(
        self,
        *,
        operation: str,
        messages: Sequence[GenerationMessage],
        response_schema: type[ModelT],
        timeout: float,
    ) -> StructuredGeneration[ModelT]: ...


class GenerationProviderError(RuntimeError):
    code = "generation_provider_error"

    def __init__(self, *, metadata: GenerationFailureMetadata) -> None:
        self.metadata = metadata
        super().__init__(self.code)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code!r}, metadata={self.metadata!r})"


class GenerationConfigurationError(GenerationProviderError):
    code = "generation_configuration_error"


class GenerationAuthenticationError(GenerationProviderError):
    code = "generation_authentication_error"


class GenerationRequestError(GenerationProviderError):
    code = "generation_request_error"


class GenerationTimeoutError(GenerationProviderError):
    code = "generation_timeout_error"


class GenerationNetworkError(GenerationProviderError):
    code = "generation_network_error"


class GenerationRateLimitError(GenerationProviderError):
    code = "generation_rate_limit_error"

    def __init__(
        self,
        *,
        metadata: GenerationFailureMetadata,
        retry_delay_seconds: float | None = None,
    ) -> None:
        if retry_delay_seconds is not None and (
            isinstance(retry_delay_seconds, bool)
            or not isinstance(retry_delay_seconds, (int, float))
            or not math.isfinite(float(retry_delay_seconds))
            or retry_delay_seconds < 0
        ):
            raise ValueError("retry_delay_seconds must be a non-negative finite number")
        self.retry_delay_seconds = retry_delay_seconds
        super().__init__(metadata=metadata)


class GenerationServerError(GenerationProviderError):
    code = "generation_server_error"


class GenerationResponseError(GenerationProviderError):
    code = "generation_response_error"
