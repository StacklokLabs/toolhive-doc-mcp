"""SQLite vector store with sqlite_vec extension"""

import sqlite3
import struct
from pathlib import Path

import sqlite_vec

from src.config import config
from src.models.chunk import DocumentationChunk


class VectorStore:
    """SQLite-based vector store for documentation chunks and embeddings"""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or config.db_path
        self.conn: sqlite3.Connection | None = None

    async def initialize(self) -> None:
        """Initialize database and create tables"""
        # Ensure directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        # Connect to database
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row

        # Load sqlite_vec extension
        try:
            self.conn.enable_load_extension(True)
            sqlite_vec.load(self.conn)
        except Exception as e:
            # sqlite_vec might be statically linked or not needed for basic operation
            print(f"Warning: Could not load sqlite_vec extension: {e}")

        # Create tables
        await self._create_tables()

    async def _create_tables(self) -> None:
        """Create database schema"""
        if not self.conn:
            raise RuntimeError("Database not initialized")

        # Chunks table
        self.conn.execute("""
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

        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_chunks_source_file
            ON chunks(source_file)
        """)

        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_chunks_created_at
            ON chunks(created_at)
        """)

        # Create vec0 virtual table for embeddings using sqlite_vec
        # vec0 is optimized for vector similarity search
        embedding_dim = config.embedding_dimension
        self.conn.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
                chunk_id TEXT PRIMARY KEY,
                embedding FLOAT[{embedding_dim}]
            )
        """)

        # Metadata table for tracking model and timestamp
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS chunk_embeddings_metadata (
                chunk_id TEXT PRIMARY KEY,
                model_name TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chunk_id) REFERENCES chunks(id) ON DELETE CASCADE
            )
        """)

        # Metadata table
        self.conn.execute("""
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
        self.conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                chunk_id UNINDEXED,
                content,
                source_file UNINDEXED,
                section_heading,
                tokenize='porter unicode61'
            )
        """)

        self.conn.commit()

    async def insert_chunk(self, chunk: DocumentationChunk, embedding: list[float]) -> None:
        """Insert chunk and its embedding"""
        if not self.conn:
            raise RuntimeError("Database not initialized")

        # Validate embedding dimension
        expected_dim = config.embedding_dimension
        if len(embedding) != expected_dim:
            raise ValueError(
                f"Embedding dimension mismatch: expected {expected_dim}, got {len(embedding)}"
            )

        # Insert chunk
        self.conn.execute(
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

        self.conn.execute(
            """
            INSERT OR REPLACE INTO vec_chunks (chunk_id, embedding)
            VALUES (?, ?)
        """,
            (chunk.id, embedding_bytes),
        )

        # Insert metadata
        self.conn.execute(
            """
            INSERT OR REPLACE INTO chunk_embeddings_metadata (
                chunk_id, model_name, created_at
            ) VALUES (?, ?, datetime('now'))
        """,
            (chunk.id, config.embedding_model),
        )

        # Insert into FTS5 table for full-text search
        self.conn.execute(
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

        self.conn.commit()

    async def search(
        self, query_embedding: list[float], limit: int = 5
    ) -> list[tuple[DocumentationChunk, float]]:
        """
        Vector similarity search using sqlite_vec

        Uses vec0 virtual table for efficient KNN search with cosine distance.
        """
        if not self.conn:
            raise RuntimeError("Database not initialized")

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
        cursor = self.conn.execute(
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

    async def get_chunk(self, chunk_id: str) -> DocumentationChunk | None:
        """Retrieve a specific chunk by ID"""
        if not self.conn:
            raise RuntimeError("Database not initialized")

        cursor = self.conn.execute(
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

    async def keyword_search(
        self, query_text: str, limit: int = 5
    ) -> list[tuple[DocumentationChunk, float]]:
        """
        Keyword-based search using SQLite FTS5 with BM25 ranking

        Returns chunks that contain the query keywords, ranked by BM25 relevance score.
        """
        if not self.conn:
            raise RuntimeError("Database not initialized")

        # Use FTS5 MATCH syntax for full-text search
        # The rank column contains BM25 scores (negative values, higher is better)
        cursor = self.conn.execute(
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

    async def health_check(self) -> bool:
        """Check if database is properly initialized"""
        if not self.conn:
            return False

        try:
            cursor = self.conn.execute("SELECT COUNT(*) FROM chunks")
            cursor.fetchone()
            return True
        except Exception:
            return False

    async def count_chunks(self) -> int:
        """Get total number of chunks in database"""
        if not self.conn:
            return 0

        cursor = self.conn.execute("SELECT COUNT(*) FROM chunks")
        result = cursor.fetchone()
        return result[0] if result else 0

    def close(self) -> None:
        """Close database connection"""
        if self.conn:
            self.conn.close()
            self.conn = None
