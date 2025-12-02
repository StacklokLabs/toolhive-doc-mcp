"""Models for background refresh system"""

from datetime import datetime

from pydantic import BaseModel, Field


class RefreshResult(BaseModel):
    """Result of a refresh operation"""

    success: bool = Field(description="Whether the refresh succeeded")
    start_time: datetime = Field(description="When the refresh started")
    end_time: datetime = Field(description="When the refresh ended")
    duration_seconds: float = Field(description="Duration in seconds")
    error: str | None = Field(default=None, description="Error message if failed")
