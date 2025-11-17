"""Documentation source metadata model"""

from datetime import datetime

from pydantic import BaseModel, Field


class DocumentationSource(BaseModel):
    """Metadata about the documentation repository"""

    sources_summary: str = Field(description="Sources summary")
    local_path: str = Field(description="Local clone directory path")
    last_sync: datetime | None = Field(default=None, description="When sources were last synced")
    total_files: int = Field(default=0, ge=0, description="Number of markdown files indexed")
    total_chunks: int = Field(default=0, ge=0, description="Number of chunks generated")
