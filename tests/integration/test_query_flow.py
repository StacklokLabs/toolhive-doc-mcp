"""Integration tests for end-to-end query flow"""

import pytest

from src.models.chunk import DocumentationChunk
from src.models.query import Query, QueryType
from src.services.search import SearchService
from src.services.vector_store import VectorStore


class TestQueryFlow:
    """Test complete query→embedding→search→results flow"""

    @pytest.mark.asyncio
    async def test_end_to_end_semantic_query(self):
        """Test full semantic query workflow"""
        # This test will verify the complete flow after implementation
        # query → embedding generation → vector search → result formatting
        pass

    @pytest.mark.asyncio
    async def test_keyword_search(self):
        """Test keyword-based search functionality"""
        # Setup: Create in-memory vector store
        vector_store = VectorStore(db_path=":memory:")
        await vector_store.initialize()

        # Insert test chunks with specific keywords
        test_chunks = [
            DocumentationChunk(
                content="Configure webhooks by setting the webhook_url in your configuration file",
                source_file="docs/webhooks/configuration.md",
                section_heading="Webhook Configuration",
                chunk_position=0,
                token_count=15,
            ),
            DocumentationChunk(
                content="API keys are used for authentication. Generate a new API key in settings.",
                source_file="docs/auth/api-keys.md",
                section_heading="API Key Management",
                chunk_position=0,
                token_count=14,
            ),
        ]

        # Insert test data (with mock embeddings - 384 dimensions for bge-small-en-v1.5)
        for chunk in test_chunks:
            await vector_store.insert_chunk(chunk, embedding=[0.0] * 384)

        # Execute: Perform keyword search
        search_service = SearchService(vector_store)
        query = Query(text="webhook configuration", query_type=QueryType.KEYWORD, limit=5)
        result = await search_service.query(query)

        # Verify: Should return webhook-related chunk with exact keyword match
        assert len(result.results) > 0
        assert "webhook" in result.results[0].chunk.content.lower()
        assert result.query_info.original_query == "webhook configuration"

    @pytest.mark.asyncio
    async def test_hybrid_search(self):
        """Test hybrid search combining semantic and keyword approaches"""
        # Setup: Create in-memory vector store
        vector_store = VectorStore(db_path=":memory:")
        await vector_store.initialize()

        # Insert test chunks
        test_chunks = [
            DocumentationChunk(
                content="Security best practices for Minder include using strong authentication",
                source_file="docs/security/best-practices.md",
                section_heading="Security Best Practices",
                chunk_position=0,
                token_count=12,
            ),
            DocumentationChunk(
                content="Authentication mechanisms support OAuth2 and API keys",
                source_file="docs/auth/overview.md",
                section_heading="Authentication Overview",
                chunk_position=0,
                token_count=10,
            ),
        ]

        # Insert with mock embeddings (384 dimensions)
        for chunk in test_chunks:
            await vector_store.insert_chunk(chunk, embedding=[0.1] * 384)

        # Execute: Perform hybrid search
        search_service = SearchService(vector_store)
        query = Query(text="authentication security", query_type=QueryType.HYBRID, limit=5)
        result = await search_service.query(query)

        # Verify: Should combine semantic similarity and keyword matches
        assert len(result.results) > 0
        # Both semantic and keyword ranking should be applied
        assert result.query_info.original_query == "authentication security"
        # Results should contain relevant keywords
        assert any(
            "authentication" in r.chunk.content.lower() or "security" in r.chunk.content.lower()
            for r in result.results
        )
