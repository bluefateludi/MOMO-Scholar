import os
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Settings:
    openai_api_key: str | None = field(default=None, repr=False)
    openai_base_url: str | None = None
    paper_agent_model: str | None = None
    semantic_scholar_api_key: str | None = field(default=None, repr=False)
    openalex_mail_address: str | None = None


def _optional_string(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


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
    )
