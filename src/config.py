"""Centralized configuration using Pydantic BaseSettings"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    """Application configuration with environment variable support"""

    # Documentation source - Website-based
    # Note: Website URLs and fetching configuration are now in sources.yaml
    docs_website_cache_path: str = Field(
        default="./data/website_cache",
        description="Local cache directory for website content",
    )

    # Database
    db_path: str = Field(default="./data/docs.db", description="SQLite database file path")
    db_temp_path: str = Field(
        default="./data/docs.db.new", description="Temporary database path for refresh operations"
    )
    vector_distance_metric: str = Field(
        default="cosine", description="Distance metric for vector similarity (cosine, l2, ip)"
    )

    # Embedding (Local model using fastembed)
    embedding_model: str = Field(
        default="BAAI/bge-small-en-v1.5", description="Local embedding model name (fastembed)"
    )
    fastembed_cache_dir: str = Field(
        default="./data/models", description="Directory to cache embedding model"
    )
    embedding_batch_size: int = Field(
        default=32, ge=1, le=256, description="Batch size for embedding generation"
    )
    embedding_dimension: int = Field(
        default=384, description="Embedding vector dimension (384 for bge-small-en-v1.5)"
    )

    # Chunking
    chunk_size_tokens: int = Field(
        default=512, ge=256, le=1024, description="Target chunk size in tokens"
    )
    chunk_overlap_tokens: int = Field(
        default=100, ge=0, le=200, description="Token overlap between adjacent chunks"
    )
    min_chunk_size_tokens: int = Field(
        default=100,
        ge=50,
        le=512,
        description="Minimum chunk size in tokens - smaller sections will be aggregated",
    )

    # MCP Server
    mcp_host: str = Field(default="0.0.0.0", description="MCP server bind address")
    mcp_port: int = Field(default=8080, ge=1024, le=65535, description="MCP server port")
    mcp_cors_enabled: bool = Field(default=True, description="Enable CORS for MCP server")

    # Query
    query_result_limit: int = Field(
        default=5, ge=1, le=50, description="Default maximum number of search results"
    )

    # OpenTelemetry
    otel_enabled: bool = Field(default=True, description="Enable OpenTelemetry logging")
    otel_tracing_enabled: bool = Field(
        default=True, description="Enable OpenTelemetry tracing for HTTP requests"
    )
    otel_endpoint: str = Field(
        default="http://otel-collector.otel.svc.cluster.local:4318",
        description="OpenTelemetry collector endpoint (HTTP/protobuf)",
    )
    otel_service_name: str = Field(
        default="toolhive-doc-mcp", description="Service name for OpenTelemetry"
    )
    otel_service_version: str = Field(
        default="1.0.0", description="Service version for OpenTelemetry"
    )
    otel_log_full_results: bool = Field(
        default=True,
        description="Include full query results in telemetry logs (needed for analytics)",
    )

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )


# Global config instance
config = AppConfig()
