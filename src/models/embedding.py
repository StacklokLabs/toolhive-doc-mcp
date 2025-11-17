"""Vector embedding data model"""

from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator


class VectorEmbedding(BaseModel):
    """Numerical vector representation of a documentation chunk"""

    chunk_id: str = Field(description="Foreign key to DocumentationChunk.id")
    embedding: list[float] = Field(
        min_length=384,
        max_length=384,
        description="Vector representation (384 dimensions for text-embedding-3-small)",
    )
    model_name: str = Field(description="Embedding model used (e.g., text-embedding-3-small)")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When embedding was generated",
    )

    @field_validator("embedding")
    @classmethod
    def validate_dimension(cls, v: list[float]) -> list[float]:
        """Validate embedding has exactly 384 dimensions"""
        if len(v) != 384:
            raise ValueError(f"Embedding must have 384 dimensions, got {len(v)}")
        return v
