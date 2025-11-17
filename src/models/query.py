"""Query request/response models"""

from enum import Enum

from pydantic import BaseModel, Field


class QueryType(str, Enum):
    """Type of search to perform"""

    SEMANTIC = "semantic"
    KEYWORD = "keyword"
    HYBRID = "hybrid"


class Query(BaseModel):
    """User-submitted request for documentation search"""

    text: str = Field(min_length=1, description="The query string (natural language or keywords)")
    limit: int = Field(default=5, ge=1, le=50, description="Maximum number of results to return")
    min_score: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Minimum relevance score threshold (0.0-1.0)"
    )
    query_type: QueryType = Field(
        default=QueryType.SEMANTIC, description="Type of search to perform"
    )
