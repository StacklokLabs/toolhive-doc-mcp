"""SQLite vector store with sqlite_vec extension"""

import sqlite3
import struct
from pathlib import Path

import sqlite_vec

from src.config import config
from src.models.chunk import DocumentationChunk
from src.models.source import DocumentationSource


class VectorStore:
    """SQLite-based vector store for documentation chunks and embeddings"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        # For :memory: databases, we need to keep a persistent connection
        # because each connection gets a separate in-memory database
        self._memory_conn: sqlite3.Connection | None = None

    def _get_connection(self) -> sqlite3.Connection:
        """
        Create and configure a new database connection

        For :memory: databases, returns the persistent connection.
        For file databases, creates a new connection.

        Returns:
            Configured sqlite3.Connection with row_factory and sqlite_vec loaded
        """
        # For :memory: databases, use persistent connection
        if self.db_path == ":memory:":
            if self._memory_conn is None:
                self._memory_conn = sqlite3.connect(self.db_path)
                self._memory_conn.row_factory = sqlite3.Row
                try:
                    self._memory_conn.enable_load_extension(True)
                    sqlite_vec.load(self._memory_conn)
                except Exception as e:
                    print(f"Warning: Could not load sqlite_vec extension: {e}")
            return self._memory_conn

        # For file databases, create new connection
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        try:
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
        except Exception as e:
            # sqlite_vec might be statically linked or not needed for basic operation
            print(f"Warning: Could not load sqlite_vec extension: {e}")

        return conn

    def _ensure_connection(
        self, conn: sqlite3.Connection | None
    ) -> tuple[sqlite3.Connection, bool]:
        """
        Ensure we have a connection, creating one if needed

        Args:
            conn: Optional existing connection

        Returns:
            Tuple of (connection, should_close)
            - connection: The connection to use
            - should_close: True if caller should close it when done
        """
        if conn is not None:
            return conn, False

        new_conn = self._get_connection()
        # Never close :memory: connections (they're persistent)
        should_close = self.db_path != ":memory:"
        return new_conn, should_close

    async def initialize(self) -> None:
        """
        Initialize database and create tables

        Note: Creates schema but does not maintain a connection for file databases.
        For :memory: databases, maintains a persistent connection.
        Each method call will create its own connection (or use persistent for :memory:).
        """
        # Ensure directory exists (skip for :memory: databases)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        # Create connection for schema setup
        conn = self._get_connection()
        try:
            await self._create_tables(conn=conn)
        finally:
            # Only close for file databases (not :memory:)
            if self.db_path != ":memory:":
                conn.close()

    async def _create_tables(self, conn: sqlite3.Connection | None = None) -> None:
        """
        Create database schema

        Args:
            conn: Optional connection (for transactions)
        """
        conn, should_close = self._ensure_connection(conn)

        try:
            # Chunks table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    source_file TEXT NOT NULL,
                    section_heading TEXT,
                    chunk_position INTEGER NOT NULL,
                    token_count INTEGER NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    CHECK(chunk_position >= 0),
                    CHECK(token_count > 0)
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_chunks_source_file
                ON chunks(source_file)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_chunks_created_at
                ON chunks(created_at)
            """)

            # Create vec0 virtual table for embeddings using sqlite_vec
            # vec0 is optimized for vector similarity search
            embedding_dim = config.embedding_dimension
            conn.execute(f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
                    chunk_id TEXT PRIMARY KEY,
                    embedding FLOAT[{embedding_dim}]
                )
            """)

            # Metadata table for tracking model and timestamp
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chunk_embeddings_metadata (
                    chunk_id TEXT PRIMARY KEY,
                    model_name TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (chunk_id) REFERENCES chunks(id) ON DELETE CASCADE
                )
            """)

            # Metadata table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS metadata (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    sources_summary TEXT NOT NULL,
                    local_path TEXT NOT NULL,
                    last_sync TIMESTAMP,
                    total_files INTEGER DEFAULT 0,
                    total_chunks INTEGER DEFAULT 0
                )
            """)

            # Create FTS5 virtual table for full-text search
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                    chunk_id UNINDEXED,
                    content,
                    source_file UNINDEXED,
                    section_heading,
                    tokenize='porter unicode61'
                )
            """)

            conn.commit()
        finally:
            if should_close:
                conn.close()

    async def insert_chunk(
        self,
        chunk: DocumentationChunk,
        embedding: list[float],
        conn: sqlite3.Connection | None = None,
    ) -> None:
        """
        Insert chunk and its embedding

        Args:
            chunk: Documentation chunk to insert
            embedding: Vector embedding
            conn: Optional connection (for transactions)
        """
        conn, should_close = self._ensure_connection(conn)

        try:
            # Validate embedding dimension
            expected_dim = config.embedding_dimension
            if len(embedding) != expected_dim:
                raise ValueError(
                    f"Embedding dimension mismatch: expected {expected_dim}, got {len(embedding)}"
                )

            # Insert chunk
            conn.execute(
                """
                INSERT OR REPLACE INTO chunks (
                    id, content, source_file, section_heading,
                    chunk_position, token_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    chunk.id,
                    chunk.content,
                    chunk.source_file,
                    chunk.section_heading,
                    chunk.chunk_position,
                    chunk.token_count,
                    chunk.created_at.isoformat(),
                ),
            )

            # Insert embedding into vec0 virtual table
            # Convert list to serialized format for vec0
            embedding_bytes = struct.pack(f"{len(embedding)}f", *embedding)

            conn.execute(
                """
                INSERT OR REPLACE INTO vec_chunks (chunk_id, embedding)
                VALUES (?, ?)
            """,
                (chunk.id, embedding_bytes),
            )

            # Insert metadata
            conn.execute(
                """
                INSERT OR REPLACE INTO chunk_embeddings_metadata (
                    chunk_id, model_name, created_at
                ) VALUES (?, ?, datetime('now'))
            """,
                (chunk.id, config.embedding_model),
            )

            # Insert into FTS5 table for full-text search
            conn.execute(
                """
                INSERT OR REPLACE INTO chunks_fts (
                    chunk_id, content, source_file, section_heading
                ) VALUES (?, ?, ?, ?)
            """,
                (
                    chunk.id,
                    chunk.content,
                    chunk.source_file,
                    chunk.section_heading,
                ),
            )

            conn.commit()
        finally:
            if should_close:
                conn.close()

    async def search(
        self,
        query_embedding: list[float],
        limit: int = 5,
        conn: sqlite3.Connection | None = None,
    ) -> list[tuple[DocumentationChunk, float]]:
        """
        Vector similarity search using sqlite_vec

        Uses vec0 virtual table for efficient KNN search with cosine distance.

        Args:
            query_embedding: Query vector embedding
            limit: Maximum number of results
            conn: Optional connection (for transactions)
        """
        conn, should_close = self._ensure_connection(conn)

        try:
            # Validate query embedding dimension
            expected_dim = config.embedding_dimension
            if len(query_embedding) != expected_dim:
                raise ValueError(
                    f"Query embedding dimension mismatch: expected {expected_dim}, "
                    f"got {len(query_embedding)}"
                )

            # Serialize query embedding for vec0
            query_bytes = struct.pack(f"{len(query_embedding)}f", *query_embedding)

            # Use vec0's KNN search with distance metric
            # The distance column will contain the cosine distance (lower is more similar)
            # Note: sqlite_vec requires k = ? in WHERE clause instead of separate LIMIT
            cursor = conn.execute(
                """
                SELECT
                    c.id, c.content, c.source_file, c.section_heading,
                    c.chunk_position, c.token_count, c.created_at,
                    v.distance
                FROM vec_chunks v
                INNER JOIN chunks c ON v.chunk_id = c.id
                WHERE v.embedding MATCH ? AND k = ?
                ORDER BY v.distance
            """,
                (query_bytes, limit),
            )

            results: list[tuple[DocumentationChunk, float]] = []
            for row in cursor.fetchall():
                chunk = DocumentationChunk(
                    id=row["id"],
                    content=row["content"],
                    source_file=row["source_file"],
                    section_heading=row["section_heading"],
                    chunk_position=row["chunk_position"],
                    token_count=row["token_count"],
                    created_at=row["created_at"],
                )
                # Convert distance to similarity score (1 - distance for cosine)
                # Distance is in range [0, 2], convert to similarity [0, 1]
                distance = row["distance"]
                similarity = 1.0 - (distance / 2.0)
                results.append((chunk, similarity))

            return results
        finally:
            if should_close:
                conn.close()

    async def get_chunk(
        self, chunk_id: str, conn: sqlite3.Connection | None = None
    ) -> DocumentationChunk | None:
        """
        Retrieve a specific chunk by ID

        Args:
            chunk_id: Chunk identifier
            conn: Optional connection (for transactions)
        """
        conn, should_close = self._ensure_connection(conn)

        try:
            cursor = conn.execute(
                """
                SELECT id, content, source_file, section_heading,
                       chunk_position, token_count, created_at
                FROM chunks
                WHERE id = ?
            """,
                (chunk_id,),
            )

            row = cursor.fetchone()
            if not row:
                return None

            return DocumentationChunk(
                id=row["id"],
                content=row["content"],
                source_file=row["source_file"],
                section_heading=row["section_heading"],
                chunk_position=row["chunk_position"],
                token_count=row["token_count"],
                created_at=row["created_at"],
            )
        finally:
            if should_close:
                conn.close()

    async def keyword_search(
        self,
        query_text: str,
        limit: int = 5,
        conn: sqlite3.Connection | None = None,
    ) -> list[tuple[DocumentationChunk, float]]:
        """
        Keyword-based search using SQLite FTS5 with BM25 ranking

        Returns chunks that contain the query keywords, ranked by BM25 relevance score.

        Args:
            query_text: Search query text
            limit: Maximum number of results
            conn: Optional connection (for transactions)
        """
        conn, should_close = self._ensure_connection(conn)

        try:
            # Use FTS5 MATCH syntax for full-text search
            # The rank column contains BM25 scores (negative values, higher is better)
            cursor = conn.execute(
                """
                SELECT
                    c.id, c.content, c.source_file, c.section_heading,
                    c.chunk_position, c.token_count, c.created_at,
                    fts.rank
                FROM chunks_fts fts
                INNER JOIN chunks c ON fts.chunk_id = c.id
                WHERE chunks_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """,
                (query_text, limit),
            )

            results: list[tuple[DocumentationChunk, float]] = []
            for row in cursor.fetchall():
                chunk = DocumentationChunk(
                    id=row["id"],
                    content=row["content"],
                    source_file=row["source_file"],
                    section_heading=row["section_heading"],
                    chunk_position=row["chunk_position"],
                    token_count=row["token_count"],
                    created_at=row["created_at"],
                )

                # Convert BM25 rank to a normalized score [0, 1]
                # FTS5 rank is negative, with values closer to 0 being better
                # We'll use a simple transformation: score = 1 / (1 + abs(rank))
                rank = row["rank"]
                score = 1.0 / (1.0 + abs(rank))

                results.append((chunk, score))

            return results
        finally:
            if should_close:
                conn.close()

    async def health_check(self, conn: sqlite3.Connection | None = None) -> bool:
        """
        Check if database is properly initialized

        Args:
            conn: Optional connection (for transactions)
        """
        conn, should_close = self._ensure_connection(conn)

        try:
            cursor = conn.execute("SELECT COUNT(*) FROM chunks")
            cursor.fetchone()
            return True
        except Exception:
            return False
        finally:
            if should_close:
                conn.close()

    async def count_chunks(self, conn: sqlite3.Connection | None = None) -> int:
        """
        Get total number of chunks in database

        Args:
            conn: Optional connection (for transactions)
        """
        conn, should_close = self._ensure_connection(conn)

        try:
            cursor = conn.execute("SELECT COUNT(*) FROM chunks")
            result = cursor.fetchone()
            return result[0] if result else 0
        finally:
            if should_close:
                conn.close()

    def update_metadata(
        self, metadata: DocumentationSource, conn: sqlite3.Connection | None = None
    ) -> None:
        conn, should_close = self._ensure_connection(conn)

        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO metadata (
                    id, sources_summary, local_path, last_sync, total_files, total_chunks
                ) VALUES (1, ?, ?, datetime('now'), ?, ?)
            """,
                (
                    metadata.sources_summary,
                    metadata.local_path,
                    metadata.total_files,
                    metadata.total_chunks,
                ),
            )

            conn.commit()
        finally:
            if should_close:
                conn.close()

    def close(self) -> None:
        """
        Close database connection

        For :memory: databases, closes the persistent connection.
        For file databases, this is a no-op (connections are per-method).
        """
        if self._memory_conn is not None:
            self._memory_conn.close()
            self._memory_conn = None
