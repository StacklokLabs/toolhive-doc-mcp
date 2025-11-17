"""Documentation chunk data model"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


class DocumentationChunk(BaseModel):
    """A semantically meaningful segment of documentation text"""

    model_config = {"ser_json_timedelta": "iso8601"}

    id: str = Field(
        default_factory=lambda: str(uuid4()), description="Unique identifier (UUID format)"
    )
    content: str = Field(min_length=1, description="The actual text content of the chunk")
    source_file: str = Field(description="Relative path to source markdown file")
    section_heading: str | None = Field(
        default=None, description="Heading of the section containing this chunk"
    )
    chunk_position: int = Field(
        ge=0, description="Sequential position within the source file (0-indexed)"
    )
    token_count: int = Field(gt=0, description="Number of tokens in content")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Timestamp when chunk was created"
    )

    @field_validator("id")
    @classmethod
    def validate_uuid(cls, v: str) -> str:
        """Validate that id is a valid UUID"""
        try:
            UUID(v)
        except ValueError as e:
            raise ValueError(f"Invalid UUID format: {v}") from e
        return v
