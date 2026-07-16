import os
from dataclasses import dataclass, field
from typing import Literal


RetrievalMode = Literal["auto", "lexical", "hybrid"]

_VALID_RETRIEVAL_MODES: tuple[RetrievalMode, ...] = (
    "auto",
    "lexical",
    "hybrid",
)


@dataclass(frozen=True, slots=True)
class Settings:
    openai_api_key: str | None = field(default=None, repr=False)
    openai_base_url: str | None = None
    paper_agent_model: str | None = None
    semantic_scholar_api_key: str | None = field(default=None, repr=False)
    openalex_mail_address: str | None = None
    dashscope_api_key: str | None = field(default=None, repr=False)
    bailian_region: str = "beijing"
    bailian_embedding_model: str = "text-embedding-v4"
    vector_collection: str = "momo_scholar_chunks_v1"
    retrieval_candidate_k: int = 30
    retrieval_mode: RetrievalMode = "auto"
    retrieval_top_k: int = 8
    retrieval_rrf_k: int = 60


def _optional_string(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _string_with_default(value: str | None, default: str) -> str:
    return _optional_string(value) or default


def _positive_int(name: str, value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value.strip())
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed < 1:
        raise ValueError(f"{name} must be at least 1")
    return parsed


def _retrieval_mode(value: str | None) -> RetrievalMode:
    normalized = "auto" if value is None else value.strip().lower()
    if normalized not in _VALID_RETRIEVAL_MODES:
        raise ValueError("RETRIEVAL_MODE must be auto, lexical, or hybrid")
    return normalized  # type: ignore[return-value]


def load_settings() -> Settings:
    return Settings(
        openai_api_key=_optional_string(os.environ.get("OPENAI_API_KEY")),
        openai_base_url=_optional_string(os.environ.get("OPENAI_BASE_URL")),
        paper_agent_model=_optional_string(os.environ.get("PAPER_AGENT_MODEL")),
        semantic_scholar_api_key=_optional_string(
            os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
        ),
        openalex_mail_address=_optional_string(
            os.environ.get("OPENALEX_MAIL_ADDRESS")
        ),
        dashscope_api_key=_optional_string(os.environ.get("DASHSCOPE_API_KEY")),
        bailian_region=_string_with_default(
            os.environ.get("BAILIAN_REGION"), "beijing"
        ),
        bailian_embedding_model=_string_with_default(
            os.environ.get("BAILIAN_EMBEDDING_MODEL"), "text-embedding-v4"
        ),
        vector_collection=_string_with_default(
            os.environ.get("VECTOR_COLLECTION"), "momo_scholar_chunks_v1"
        ),
        retrieval_candidate_k=_positive_int(
            "RETRIEVAL_CANDIDATE_K",
            os.environ.get("RETRIEVAL_CANDIDATE_K"),
            30,
        ),
        retrieval_mode=_retrieval_mode(os.environ.get("RETRIEVAL_MODE")),
        retrieval_top_k=_positive_int(
            "RETRIEVAL_TOP_K", os.environ.get("RETRIEVAL_TOP_K"), 8
        ),
        retrieval_rrf_k=_positive_int(
            "RETRIEVAL_RRF_K", os.environ.get("RETRIEVAL_RRF_K"), 60
        ),
    )
