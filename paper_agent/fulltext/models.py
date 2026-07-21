from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from paper_agent.modeling import StrictModel


ContentSource = Literal["pdf", "abstract"]


class DocumentPage(StrictModel):
    page_number: int = Field(ge=1)
    text: str = Field(min_length=1)

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("page text must not be blank")
        return value


class PaperDocument(StrictModel):
    paper_id: str
    content_source: ContentSource
    pages: list[DocumentPage] = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    warnings: list[str] = Field(default_factory=list)


class DocumentRecord(StrictModel):
    paper_id: str
    content_source: ContentSource
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_count: int = Field(ge=1)
    warnings: list[str] = Field(default_factory=list)
    fallback_code: str | None = None

    @classmethod
    def from_document(
        cls,
        document: PaperDocument,
        fallback_code: str | None = None,
    ) -> DocumentRecord:
        return cls(
            paper_id=document.paper_id,
            content_source=document.content_source,
            content_sha256=document.content_sha256,
            page_count=len(document.pages),
            warnings=list(document.warnings),
            fallback_code=fallback_code,
        )
