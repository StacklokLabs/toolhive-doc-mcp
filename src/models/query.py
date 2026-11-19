"""Query request/response models"""

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field


class QueryType(str, Enum):
    """Type of search to perform"""

    SEMANTIC = "semantic"
    KEYWORD = "keyword"
    HYBRID = "hybrid"


# Input constraints shared by the Query model and the query_docs tool schema
QueryText = Annotated[str, Field(min_length=1)]
QueryLimit = Annotated[int, Field(ge=1, le=50)]
MinScore = Annotated[float, Field(ge=0.0, le=1.0)]


class Query(BaseModel):
    """User-submitted request for documentation search"""

    text: QueryText = Field(description="The query string (natural language or keywords)")
    limit: QueryLimit = Field(default=5, description="Maximum number of results to return")
    min_score: MinScore | None = Field(
        default=None, description="Minimum relevance score threshold (0.0-1.0)"
    )
    query_type: QueryType = Field(
        default=QueryType.SEMANTIC, description="Type of search to perform"
    )
