"""Pydantic models for website documentation cache"""

from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl


class CachedPage(BaseModel):
    """Metadata for a cached documentation page"""

    url: HttpUrl = Field(description="Full URL of the documentation page")

    url_hash: str = Field(
        min_length=64, max_length=64, description="SHA256 hash of URL (used for filename)"
    )

    fetch_timestamp: datetime = Field(
        description="When this page was last fetched from the website"
    )

    content_hash: str = Field(
        min_length=64,
        max_length=64,
        description="SHA256 hash of HTML content (for change detection)",
    )

    content_length: int = Field(ge=0, description="Size of HTML content in bytes")

    http_status: int = Field(ge=100, le=599, description="HTTP status code from last fetch")

    etag: str | None = Field(default=None, description="ETag header from response (if available)")

    last_modified: str | None = Field(
        default=None, description="Last-Modified header from response (if available)"
    )

    title: str | None = Field(default=None, description="Extracted page title from HTML")

    extracted_at: datetime | None = Field(
        default=None, description="When content was last extracted/parsed"
    )


class SyncStats(BaseModel):
    """Statistics from a documentation sync operation"""

    started_at: datetime = Field(description="When sync operation started")

    completed_at: datetime = Field(description="When sync operation completed")

    duration_seconds: float = Field(ge=0.0, description="Total sync duration in seconds")

    pages_discovered: int = Field(ge=0, description="Number of unique pages discovered")

    pages_fetched: int = Field(ge=0, description="Number of pages fetched from website")

    pages_cached: int = Field(ge=0, description="Number of pages retrieved from cache (unchanged)")

    pages_updated: int = Field(ge=0, description="Number of pages with content changes")

    pages_failed: int = Field(ge=0, description="Number of pages that failed to fetch")

    failed_urls: list[str] = Field(default_factory=list, description="URLs that failed to fetch")

    total_bytes_fetched: int = Field(ge=0, description="Total bytes of HTML content fetched")

    cache_hit_rate: float = Field(
        ge=0.0, le=1.0, description="Ratio of cached pages to total pages"
    )


class CacheMetadata(BaseModel):
    """Global metadata for website documentation cache"""

    version: str = Field(
        default="1.0.0", description="Cache format version (for future migrations)"
    )

    base_url: str = Field(description="Base URL for documentation website")

    last_full_sync: datetime = Field(description="Timestamp of last complete documentation sync")

    last_incremental_sync: datetime | None = Field(
        default=None, description="Timestamp of last incremental update check"
    )

    total_pages: int = Field(ge=0, description="Total number of pages in cache")

    pages: dict[str, CachedPage] = Field(
        default_factory=dict, description="Mapping of URL to cached page metadata"
    )

    sync_stats: SyncStats | None = Field(
        default=None, description="Statistics from last sync operation"
    )


class FetchResult(BaseModel):
    """Result of fetching a documentation page"""

    url: HttpUrl = Field(description="URL that was fetched")

    status: int = Field(ge=100, le=599, description="HTTP status code")

    success: bool = Field(description="Whether fetch was successful (2xx status)")

    content: str | None = Field(default=None, description="HTML content (None if fetch failed)")

    content_type: str | None = Field(default=None, description="Content-Type header from response")

    etag: str | None = Field(default=None, description="ETag header (for caching)")

    last_modified: str | None = Field(default=None, description="Last-Modified header")

    redirected_url: HttpUrl | None = Field(
        default=None, description="Final URL after redirects (if different)"
    )

    error_message: str | None = Field(default=None, description="Error message if fetch failed")

    fetch_duration_ms: float = Field(ge=0.0, description="Time taken to fetch in milliseconds")


class ParsedContent(BaseModel):
    """Structured content extracted from HTML documentation page"""

    url: HttpUrl = Field(description="Source URL of the page")

    title: str = Field(min_length=1, description="Page title extracted from <title> or <h1>")

    main_content: str = Field(
        min_length=1, description="Main documentation content (text only, formatted)"
    )

    headings: list[str] = Field(
        default_factory=list, description="List of all headings (h1-h6) in order"
    )

    code_blocks: list[str] = Field(default_factory=list, description="List of code block contents")

    links: list[str] = Field(default_factory=list, description="List of internal links discovered")

    metadata: dict[str, str] = Field(
        default_factory=dict,
        description="Additional metadata (e.g., meta tags, description)",
    )

    extraction_method: str = Field(
        description="Method used to extract content (e.g., 'main_tag', 'article_tag', 'fallback')"
    )

    word_count: int = Field(ge=0, description="Word count of main content")
