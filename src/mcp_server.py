"""MCP server implementation using fastmcp"""

import logging
import threading
from typing import Any
from uuid import UUID

from apscheduler.schedulers.background import BackgroundScheduler
from fastmcp import FastMCP
from fastmcp.exceptions import McpError
from mcp.types import ToolAnnotations
from starlette.responses import JSONResponse

from src.config import config
from src.models.query import MinScore, Query, QueryLimit, QueryText, QueryType
from src.models.search_result import QueryDocsOutput
from src.services.refresh_orchestrator import RefreshOrchestrator
from src.services.search import SearchService
from src.services.telemetry import get_telemetry_service
from src.services.vector_store import VectorStore
from src.utils.sources_loader import load_sources_config

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize fastmcp server
mcp = FastMCP(name="stacklok-docs-search", version=config.server_version)

# Initialize services (will be set up on first request)
_vector_store: VectorStore | None = None
_search_service: SearchService | None = None

# Background refresh orchestrator
_refresh_orchestrator: RefreshOrchestrator | None = None
_scheduler: BackgroundScheduler | None = None

# Both tools only read the local documentation database
READ_ONLY_TOOL = {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False}

# Database swap lock - ensures atomic database swaps don't interfere with service init
_db_swap_lock = threading.Lock()


async def _get_services() -> tuple[VectorStore, SearchService]:
    """
    Get or initialize services

    Uses lock to ensure service initialization doesn't happen during database swap.
    """
    global _vector_store, _search_service

    # Acquire lock to prevent initialization during database swap
    with _db_swap_lock:
        if not _vector_store:
            _vector_store = VectorStore(config.db_path)
            await _vector_store.initialize()

            # Check if database is initialized
            if not await _vector_store.health_check():
                raise McpError(
                    code=-32001,
                    message="Documentation database is not initialized. Run build process first.",
                )

        if not _search_service:
            _search_service = SearchService(_vector_store)

    return _vector_store, _search_service


@mcp.tool(
    title="Search Stacklok Docs",
    annotations=ToolAnnotations(title="Search Stacklok Docs", **READ_ONLY_TOOL),
)
async def query_docs(
    query: QueryText,
    limit: QueryLimit = 5,
    query_type: QueryType = QueryType.SEMANTIC,
    min_score: MinScore | None = None,
) -> QueryDocsOutput:
    """Search Stacklok documentation and return relevant snippets with relevance scores

    Args:
        query: Search query (natural language question or keywords)
        limit: Maximum number of results to return
        query_type: Type of search: semantic, keyword, or hybrid
        min_score: Minimum relevance score

    Returns:
        QueryDocsOutput: Search results with metadata
    """
    telemetry = get_telemetry_service()
    error: Exception | None = None
    response = None

    try:
        # Get services
        _, search_service = await _get_services()

        # Create query object (input bounds are already enforced by the tool schema)
        query_obj = Query(text=query, limit=limit, query_type=query_type, min_score=min_score)

        # Execute search
        try:
            result = await search_service.query(query_obj)
            response = result.model_dump()
            return result
        except Exception as e:
            error = e
            raise McpError(code=-32603, message=f"Search failed: {str(e)}") from e

    finally:
        # Log telemetry regardless of success/failure
        telemetry.log_query(
            tool_name="query_docs",
            query=query,
            parameters={
                "limit": limit,
                "query_type": query_type.value,
                "min_score": min_score,
            },
            response=response,
            error=error,
        )


@mcp.tool(
    title="Get Documentation Chunk",
    annotations=ToolAnnotations(title="Get Documentation Chunk", **READ_ONLY_TOOL),
)
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
                code=-32602, message=f"chunk_id must be a valid UUID, got: {chunk_id}"
            ) from e

        # Get vector store
        vector_store, _ = await _get_services()

        # Fetch chunk
        chunk = await vector_store.get_chunk(chunk_id)

        if not chunk:
            error = ValueError(f"Chunk with ID {chunk_id} not found")
            raise McpError(code=-32002, message=f"Chunk with ID {chunk_id} not found")

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


def _startup_sync() -> None:
    """Initialize background refresh on server startup"""
    global _refresh_orchestrator, _scheduler

    # Load sources config to check if refresh is enabled
    try:
        sources_config = load_sources_config()
        refresh_config = sources_config.refresh

        if refresh_config.enabled:
            logger.info("Initializing background refresh orchestrator")
            _scheduler = BackgroundScheduler()

            # Pass the db_swap_lock to coordinate with service initialization
            _refresh_orchestrator = RefreshOrchestrator(db_swap_lock=_db_swap_lock)
            _refresh_orchestrator.configure_scheduler_sync(
                scheduler=_scheduler,
                interval_hours=refresh_config.interval_hours,
                max_concurrent_jobs=refresh_config.max_concurrent_jobs,
            )

            _scheduler.start()
            logger.info("Background refresh orchestrator started successfully")
        else:
            logger.info("Background refresh is disabled")
    except Exception as e:
        logger.error(f"Failed to start background refresh orchestrator: {e}")
        # Don't fail server startup if refresh fails to initialize


def _shutdown_sync() -> None:
    """Gracefully shutdown on server shutdown"""
    global _scheduler, _refresh_orchestrator

    if _refresh_orchestrator:
        try:
            _refresh_orchestrator.stop_scheduler_sync()
        except Exception as e:
            logger.error(f"Error shutting down refresh orchestrator: {e}")

    if _scheduler:
        try:
            logger.info("Shutting down background refresh scheduler")
            _scheduler.shutdown(wait=False)
            logger.info("Background refresh scheduler stopped")
        except Exception as e:
            logger.error(f"Error shutting down scheduler: {e}")


def main() -> None:
    """Entry point for the MCP server"""
    # Initialize background refresh service synchronously
    _startup_sync()

    try:
        # Run server using FastMCP's built-in runner. The server keeps no
        # per-session state, so it runs stateless: 2026-07-28 has no protocol
        # sessions, and earlier protocol versions simply get no Mcp-Session-Id.
        mcp.run(
            transport="streamable-http",
            host="0.0.0.0",
            port=config.mcp_port,
            stateless_http=True,
        )
    finally:
        # Cleanup on shutdown
        _shutdown_sync()


if __name__ == "__main__":
    main()
