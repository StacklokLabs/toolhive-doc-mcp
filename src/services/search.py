"""Search service for querying documentation"""

import time

from src.models.query import Query, QueryType
from src.models.search_result import (
    QueryDocsOutput,
    QueryInfo,
    SearchMetadata,
    SearchResult,
)
from src.services.embedder import Embedder
from src.services.vector_store import VectorStore


class SearchService:
    """Handle documentation search queries"""

    def __init__(self, vector_store: VectorStore):
        self.vector_store = vector_store
        self.embedder = Embedder()

    async def query(self, query: Query) -> QueryDocsOutput:
        """
        Execute a documentation search query

        Args:
            query: Query object with search parameters

        Returns:
            QueryDocsOutput: Search results with metadata
        """
        start_time = time.time()

        search_results: list[SearchResult] = []

        # Handle different query types
        if query.query_type == QueryType.SEMANTIC:
            # Generate query embedding
            query_embedding = await self.embedder.embed_text(query.text)

            # Perform vector similarity search
            raw_results = await self.vector_store.search(query_embedding, limit=query.limit)

            # Format results
            for rank, (chunk, score) in enumerate(raw_results, start=1):
                # Filter by min_score if specified
                if query.min_score and score < query.min_score:
                    continue

                result = SearchResult(
                    chunk=chunk,
                    score=score,
                    rank=rank,
                    metadata=SearchMetadata(
                        source_url=None,  # TODO: Generate from source_file
                        breadcrumb=[chunk.section_heading] if chunk.section_heading else [],
                        match_type="semantic",
                    ),
                )
                search_results.append(result)

        elif query.query_type == QueryType.KEYWORD:
            # Perform keyword-based search
            raw_results = await self.vector_store.keyword_search(query.text, limit=query.limit)

            # Format results
            for rank, (chunk, score) in enumerate(raw_results, start=1):
                # Filter by min_score if specified
                if query.min_score and score < query.min_score:
                    continue

                result = SearchResult(
                    chunk=chunk,
                    score=score,
                    rank=rank,
                    metadata=SearchMetadata(
                        source_url=None,
                        breadcrumb=[chunk.section_heading] if chunk.section_heading else [],
                        match_type="keyword",
                    ),
                )
                search_results.append(result)

        elif query.query_type == QueryType.HYBRID:
            # Perform both semantic and keyword searches
            query_embedding = await self.embedder.embed_text(query.text)
            semantic_results = await self.vector_store.search(
                query_embedding, limit=query.limit * 2
            )
            keyword_results = await self.vector_store.keyword_search(
                query.text, limit=query.limit * 2
            )

            # Apply Reciprocal Rank Fusion (RRF)
            search_results = await self._reciprocal_rank_fusion(
                semantic_results, keyword_results, query.limit
            )

            # Apply min_score filter
            if query.min_score:
                search_results = [r for r in search_results if r.score >= query.min_score]

        # Calculate query time
        query_time_ms = (time.time() - start_time) * 1000

        # Create query info
        query_info = QueryInfo(
            original_query=query.text,
            total_results=len(search_results),
            query_time_ms=query_time_ms,
        )

        return QueryDocsOutput(results=search_results, query_info=query_info)

    async def _reciprocal_rank_fusion(
        self,
        semantic_results: list[tuple],
        keyword_results: list[tuple],
        limit: int,
        k: int = 60,
    ) -> list[SearchResult]:
        """
        Combine semantic and keyword results using Reciprocal Rank Fusion

        Args:
            semantic_results: Vector similarity search results
            keyword_results: Keyword search results
            limit: Maximum number of results to return
            k: RRF constant (default: 60)

        Returns:
            Merged and re-ranked results
        """
        # Build RRF scores for all chunks
        rrf_scores: dict[str, float] = {}
        chunk_map: dict[str, tuple] = {}

        # Add semantic results
        for rank, (chunk, _) in enumerate(semantic_results, start=1):
            chunk_id = chunk.id
            rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0) + 1 / (k + rank)
            if chunk_id not in chunk_map:
                chunk_map[chunk_id] = (chunk, "semantic")

        # Add keyword results
        for rank, (chunk, _) in enumerate(keyword_results, start=1):
            chunk_id = chunk.id
            rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0) + 1 / (k + rank)
            if chunk_id not in chunk_map:
                chunk_map[chunk_id] = (chunk, "keyword")
            else:
                # Update match type to hybrid if found in both
                chunk_map[chunk_id] = (chunk_map[chunk_id][0], "hybrid")

        # Sort by RRF score and create SearchResult objects
        sorted_chunks = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)[:limit]

        results: list[SearchResult] = []
        for rank, (chunk_id, rrf_score) in enumerate(sorted_chunks, start=1):
            chunk, match_type = chunk_map[chunk_id]
            result = SearchResult(
                chunk=chunk,
                score=min(rrf_score, 1.0),  # Normalize score to 0-1 range
                rank=rank,
                metadata=SearchMetadata(
                    source_url=None,
                    breadcrumb=[chunk.section_heading] if chunk.section_heading else [],
                    match_type=match_type,
                ),
            )
            results.append(result)

        return results

    async def close(self) -> None:
        """Cleanup resources"""
        await self.embedder.close()
