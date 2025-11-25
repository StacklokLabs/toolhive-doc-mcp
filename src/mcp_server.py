"""MCP server implementation using fastmcp"""

from typing import Any
from uuid import UUID

from fastmcp import FastMCP
from fastmcp.exceptions import McpError
from mcp.types import ErrorData
from starlette.responses import JSONResponse

from src.config import config
from src.models.query import Query, QueryType
from src.models.search_result import QueryDocsOutput
from src.services.search import SearchService
from src.services.telemetry import get_telemetry_service
from src.services.vector_store import VectorStore

# Initialize fastmcp server
mcp = FastMCP(name="stacklok-docs-search", version="1.0.0")

# Initialize services (will be set up on first request)
_vector_store: VectorStore | None = None
_search_service: SearchService | None = None


async def _get_services() -> tuple[VectorStore, SearchService]:
    """Get or initialize services"""
    global _vector_store, _search_service

    if not _vector_store:
        _vector_store = VectorStore()
        await _vector_store.initialize()

        # Check if database is initialized
        if not await _vector_store.health_check():
            raise McpError(
                ErrorData(
                    code=-32001,
                    message="Documentation database is not initialized. Run build process first.",
                )
            )

    if not _search_service:
        _search_service = SearchService(_vector_store)

    return _vector_store, _search_service


@mcp.tool()
async def query_docs(
    query: str, limit: int = 5, query_type: str = "semantic", min_score: float | None = None
) -> QueryDocsOutput:
    """Search Stacklok documentation and return relevant snippets with relevance scores

    Args:
        query: Search query (natural language question or keywords)
        limit: Maximum number of results to return (1-50, default: 5)
        query_type: Type of search (semantic, keyword, hybrid, default: semantic)
        min_score: Minimum relevance score (0.0-1.0)

    Returns:
        QueryDocsOutput: Search results with metadata
    """
    telemetry = get_telemetry_service()
    error: Exception | None = None
    response = None

    try:
        # Get services
        _, search_service = await _get_services()

        # Validate query_type
        try:
            qt = QueryType(query_type)
        except ValueError as e:
            error = e
            raise McpError(
                ErrorData(
                    code=-32602,
                    message=(
                        f"Invalid query_type: {query_type}. "
                        "Must be: semantic, keyword, or hybrid"
                    ),
                )
            ) from e

        # Create query object
        query_obj = Query(text=query, limit=limit, query_type=qt, min_score=min_score)

        # Execute search
        try:
            result = await search_service.query(query_obj)
            response = result.model_dump()
            return result
        except Exception as e:
            error = e
            raise McpError(ErrorData(code=-32603, message=f"Search failed: {str(e)}")) from e

    finally:
        # Log telemetry regardless of success/failure
        telemetry.log_query(
            tool_name="query_docs",
            query=query,
            parameters={
                "limit": limit,
                "query_type": query_type,
                "min_score": min_score,
            },
            response=response,
            error=error,
        )


@mcp.tool()
async def get_chunk(chunk_id: str) -> dict[str, Any]:
    """Retrieve full details of a specific documentation chunk by its ID

    Args:
        chunk_id: UUID of the documentation chunk

    Returns:
        dict: Chunk details including content, source, and metadata
    """
    telemetry = get_telemetry_service()
    error: Exception | None = None
    response = None

    try:
        # Validate UUID format
        try:
            UUID(chunk_id)
        except ValueError as e:
            error = e
            raise McpError(
                ErrorData(code=-32602, message=f"chunk_id must be a valid UUID, got: {chunk_id}")
            ) from e

        # Get vector store
        vector_store, _ = await _get_services()

        # Fetch chunk
        chunk = await vector_store.get_chunk(chunk_id)

        if not chunk:
            error = ValueError(f"Chunk with ID {chunk_id} not found")
            raise McpError(ErrorData(code=-32002, message=f"Chunk with ID {chunk_id} not found"))

        response = chunk.model_dump()
        return response

    finally:
        # Log telemetry regardless of success/failure
        telemetry.log_query(
            tool_name="get_chunk",
            query=None,
            parameters={"chunk_id": chunk_id},
            response=response,
            error=error,
        )


# Health check endpoint
# Note: Both routes (/ and /health) point to the same function using double decorator pattern.
# This provides flexibility for clients - they can use either the root path or the explicit
# /health endpoint.
@mcp.custom_route("/", methods=["GET"])
@mcp.custom_route("/health", methods=["GET"])
def health_check(request):
    return JSONResponse({"status": "ok"})


def main() -> None:
    """Entry point for the MCP server"""
    # Run server using FastMCP's built-in runner
    # CORS is handled automatically by FastMCP via streamable-http transport
    mcp.run(transport="streamable-http", host="0.0.0.0", port=config.mcp_port)


if __name__ == "__main__":
    main()
