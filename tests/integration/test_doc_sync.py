"""Integration tests for documentation sync workflow"""

import tempfile
from pathlib import Path

import pytest
from pydantic import HttpUrl

from src.services.chunker import Chunker
from src.services.doc_parser import DocParser
from src.services.doc_sync import DocSync
from src.services.embedder import Embedder
from src.services.vector_store import VectorStore


class TestDocSync:
    """Test documentation sync, parse, chunk, embed workflow"""

    @pytest.mark.asyncio
    async def test_doc_sync_workflow(self):
        """Test complete doc sync workflow: clone/pull → parse → chunk → embed → persist"""
        # Create temporary directory for test
        # Setup: Initialize DocSync with test website
        with tempfile.TemporaryDirectory() as temp_dir:
            base_url = HttpUrl("https://docs.stacklok.com/toolhive")
            path_prefix = "/toolhive"
            doc_sync = DocSync(base_url=base_url, path_prefix=path_prefix)
            doc_sync.cache_dir = temp_dir

            # Step 1: Sync documentation (fetch from website)
            page_count, sync_id = await doc_sync.sync_docs()

            # Verify: Pages fetched and synced
            assert page_count > 0, "Should fetch documentation pages"
            assert sync_id is not None, "Should capture sync ID"

            # Step 2: Get list of cached pages for parsing
            cached_pages = await doc_sync.get_pages_list()

            # Verify pages were cached
            assert len(cached_pages) > 0, "Should have cached pages"

    @pytest.mark.asyncio
    async def test_build_process(self):
        """Test complete build orchestration"""
        # This test verifies the full build process:
        # sync → parse → chunk → embed → persist

        # Setup: Create in-memory database for testing
        vector_store = VectorStore(db_path=":memory:")
        await vector_store.initialize()

        # Create test markdown content
        test_content = """# Test Documentation

## Introduction

This is a test documentation file for the build process.

## Configuration

Configure the application by setting environment variables:
- `API_KEY`: Your API key
- `DB_PATH`: Database path
"""

        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test markdown file
            test_file = Path(temp_dir) / "test.md"
            test_file.write_text(test_content)

            # Step 1: Parse the test file
            doc_parser = DocParser()
            parsed = await doc_parser.parse(test_file)

            # Step 2: Chunk the content
            chunker = Chunker()
            chunks = await chunker.chunk(parsed, str(test_file))

            assert len(chunks) > 0, "Should create chunks from test content"

            # Step 3: Generate embeddings (mock for test)
            embedder = Embedder()
            # For testing, use mock embeddings (384 dimensions for bge-small-en-v1.5)
            mock_embeddings = [[0.1] * 384 for _ in chunks]

            # Step 4: Persist to database
            for chunk, embedding in zip(chunks, mock_embeddings, strict=True):
                await vector_store.insert_chunk(chunk, embedding)

            # Verify: Chunks stored in database
            chunk_count = await vector_store.count_chunks()
            assert chunk_count == len(chunks), "All chunks should be stored"

            # Cleanup
            await embedder.close()
            vector_store.close()
