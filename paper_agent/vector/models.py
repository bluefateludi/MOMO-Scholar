from pydantic import BaseModel, ConfigDict, Field, model_validator


class FrozenVectorModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class VectorFilter(FrozenVectorModel):
    paper_id: str | None = None


class VectorRecordMetadata(FrozenVectorModel):
    paper_id: str
    chunk_id: str
    section: str | None
    page: int | None
    content_hash: str
    embedding_model: str


class VectorSearchResult(FrozenVectorModel):
    chunk_id: str
    text: str
    score: float = Field(ge=0.0, le=1.0)
    metadata: VectorRecordMetadata

    @model_validator(mode="after")
    def identity_matches_metadata(self) -> "VectorSearchResult":
        if self.chunk_id != self.metadata.chunk_id:
            raise ValueError("chunk_id must match metadata.chunk_id")
        return self


class VectorCandidate(FrozenVectorModel):
    chunk_id: str
    paper_id: str
    text: str
    score: float = Field(ge=0.0, le=1.0)
    metadata: VectorRecordMetadata

    @model_validator(mode="after")
    def identity_matches_metadata(self) -> "VectorCandidate":
        if self.chunk_id != self.metadata.chunk_id:
            raise ValueError("chunk_id must match metadata.chunk_id")
        if self.paper_id != self.metadata.paper_id:
            raise ValueError("paper_id must match metadata.paper_id")
        return self
