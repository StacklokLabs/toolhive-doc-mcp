"""Search result models"""

from pydantic import BaseModel, Field

from src.models.chunk import DocumentationChunk


class SearchMetadata(BaseModel):
    """Additional context and source information for search results"""

    source_url: str | None = Field(default=None, description="Link to original doc page")
    breadcrumb: list[str] = Field(
        default_factory=list,
        description="Hierarchical path to content (e.g., ['Getting Started', 'Installation'])",
    )
    match_type: str = Field(description="How this result matched (semantic, keyword, hybrid)")


class SearchResult(BaseModel):
    """Documentation chunk returned in response to a query"""

    chunk: DocumentationChunk = Field(description="The matching documentation chunk")
    score: float = Field(ge=0.0, le=1.0, description="Relevance score (0.0-1.0, higher is better)")
    rank: int = Field(ge=1, description="Position in result list (1-indexed)")
    metadata: SearchMetadata = Field(description="Additional context and source information")


class QueryInfo(BaseModel):
    """Metadata about the query execution"""

    original_query: str = Field(description="The query that was executed")
    total_results: int = Field(ge=0, description="Total number of results found (before limit)")
    query_time_ms: float = Field(ge=0.0, description="Query execution time in milliseconds")


class QueryDocsOutput(BaseModel):
    """Complete output from query_docs tool"""

    results: list[SearchResult] = Field(description="List of search results")
    query_info: QueryInfo = Field(description="Metadata about the query")
