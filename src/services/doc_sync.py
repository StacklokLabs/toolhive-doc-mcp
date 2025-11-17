"""Documentation synchronization service - Website-based"""

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path

from pydantic import HttpUrl

from src.config import config
from src.models.sources_config import FetchingConfig
from src.models.website_cache import CachedPage, CacheMetadata, ParsedContent, SyncStats
from src.services.chunker import Chunker
from src.services.doc_parser import ParsedContent as MarkdownParsedContent
from src.services.embedder import Embedder
from src.services.html_parser import HtmlParser
from src.services.vector_store import VectorStore
from src.services.website_fetcher import WebsiteFetcher

logger = logging.getLogger(__name__)


class SyncError(Exception):
    """Raised when documentation sync fails catastrophically"""

    def __init__(self, message: str, cause: Exception | None = None):
        self.message = message
        self.cause = cause
        super().__init__(message)


class DocSync:
    """Handle documentation synchronization from website source"""

    def __init__(
        self,
        base_url: HttpUrl,
        path_prefix: str,
        fetching_config: FetchingConfig | None = None,
        chunker: Chunker | None = None,
        embedder: Embedder | None = None,
        vector_store: VectorStore | None = None,
    ):
        """
        Initialize documentation sync service

        Args:
            base_url: Base URL of the website to sync
            path_prefix: Path prefix to limit crawling
            fetching_config: Fetching configuration (optional, uses defaults if None)
            chunker: Chunker service (optional, creates new if None)
            embedder: Embedder service (optional, creates new if None)
            vector_store: VectorStore service (optional, creates new if None)
        """
        self.base_url = base_url
        self.path_prefix = path_prefix
        self.fetching_config = fetching_config or FetchingConfig()
        self.fetcher = WebsiteFetcher(base_url, path_prefix, self.fetching_config)
        self.html_parser = HtmlParser()
        self.chunker = chunker or Chunker()
        self.embedder = embedder or Embedder()
        self.vector_store = vector_store
        self._cache_dir = Path(config.docs_website_cache_path)

    @property
    def cache_dir(self) -> Path:
        """Get the cache directory path"""
        return self._cache_dir

    @cache_dir.setter
    def cache_dir(self, value: str | Path) -> None:
        """Set the cache directory path"""
        self._cache_dir = Path(value)

    @property
    def pages_dir(self) -> Path:
        """Get the pages directory path (derived from cache_dir)"""
        return self.cache_dir / "pages"

    @property
    def metadata_file(self) -> Path:
        """Get the metadata file path (derived from cache_dir)"""
        return self.cache_dir / "metadata.json"

    async def sync_docs(
        self, *, force_refresh: bool = False, incremental: bool = True
    ) -> tuple[int, str]:
        """
        Synchronize documentation from website source

        Args:
            force_refresh: If True, bypass cache and re-fetch all pages
            incremental: If True, only fetch changed pages; if False, full sync

        Returns:
            Tuple of (page_count, last_sync_id)
            - page_count: Number of pages processed
            - last_sync_id: Unique identifier for this sync (timestamp-based)

        Raises:
            SyncError: If sync fails catastrophically
        """
        start_time = datetime.now()
        logger.info(f"Starting documentation sync from {self.base_url}")

        try:
            # Ensure cache directory exists
            self.pages_dir.mkdir(parents=True, exist_ok=True)

            # Load existing cache metadata
            cache_metadata = self._load_cache_metadata()

            # Discover and determine which pages to fetch
            discovered_urls, urls_to_fetch = await self._discover_and_filter_pages(
                cache_metadata, force_refresh, incremental
            )

            # Fetch and process pages
            (
                pages_updated,
                pages_failed,
                failed_urls,
                total_bytes,
                cache_metadata,
            ) = await self._fetch_and_process_pages(urls_to_fetch, cache_metadata)

            # Update cache metadata and stats
            cache_metadata = self._update_cache_metadata(
                cache_metadata,
                start_time,
                discovered_urls,
                urls_to_fetch,
                pages_updated,
                pages_failed,
                failed_urls,
                total_bytes,
            )

            sync_id = start_time.isoformat()
            duration = (datetime.now() - start_time).total_seconds()
            logger.info(
                f"✓ Sync complete: {pages_updated} pages updated, "
                f"{pages_failed} failed in {duration:.1f}s"
            )

            return len(discovered_urls), sync_id

        except Exception as e:
            logger.error(f"Sync failed: {e}")
            raise SyncError(f"Documentation sync failed: {e}", e) from e

    async def _discover_and_filter_pages(
        self, cache_metadata: CacheMetadata | None, force_refresh: bool, incremental: bool
    ) -> tuple[list[HttpUrl], list[HttpUrl]]:
        """Discover pages and determine which ones to fetch"""
        logger.info("Discovering documentation pages...")
        discovered_urls = await self.fetcher.discover_pages(str(self.base_url))
        logger.info(f"Discovered {len(discovered_urls)} pages")

        if force_refresh:
            urls_to_fetch = list(discovered_urls)
            logger.info("Force refresh: fetching all pages")
        elif incremental and cache_metadata:
            # Only fetch new or potentially changed pages
            urls_to_fetch = [url for url in discovered_urls if url not in cache_metadata.pages]
            logger.info(
                f"Incremental sync: {len(urls_to_fetch)} new pages, "
                f"{len(discovered_urls) - len(urls_to_fetch)} cached"
            )
        else:
            urls_to_fetch = list(discovered_urls)
            logger.info("Full sync: fetching all pages")

        return list(discovered_urls), urls_to_fetch

    async def _fetch_and_process_pages(
        self, urls_to_fetch: list[HttpUrl], cache_metadata: CacheMetadata | None
    ) -> tuple[int, int, list[str], int, CacheMetadata]:
        """Fetch pages and process them into cache and vector store"""
        fetch_results = await self.fetcher.fetch_multiple(
            urls_to_fetch, use_cache=False, fail_fast=False
        )

        pages_updated = 0
        pages_failed = 0
        failed_urls = []
        total_bytes = 0

        if cache_metadata is None:
            cache_metadata = CacheMetadata(
                base_url=str(self.base_url),
                last_full_sync=datetime.now(),
                total_pages=0,
            )

        for result in fetch_results:
            if result.success and result.content:
                await self._process_successful_fetch(result, cache_metadata)
                pages_updated += 1
                total_bytes += len(result.content)
                logger.info(f"✓ Fetched and cached: {result.url}")
            else:
                pages_failed += 1
                failed_urls.append(str(result.url))
                logger.warning(f"✗ Failed to fetch {result.url}: {result.error_message}")

        return pages_updated, pages_failed, failed_urls, total_bytes, cache_metadata

    async def _process_successful_fetch(self, result, cache_metadata: CacheMetadata) -> None:
        """Process a successfully fetched page"""
        # Save HTML to cache
        url_hash = hashlib.sha256(str(result.url).encode()).hexdigest()
        content_hash = hashlib.sha256(result.content.encode()).hexdigest()

        html_file = self.pages_dir / f"{url_hash}.html"
        html_file.write_text(result.content, encoding="utf-8")

        # Parse and process content
        parsed_html = None
        try:
            parsed_html = self.html_parser.parse(result.content, result.url)
            await self._process_parsed_content(parsed_html, str(result.url))
        except Exception as e:
            logger.error(f"Failed to parse/chunk/embed HTML for {result.url}: {e}")
            # Continue with caching even if parsing/chunking fails

        # Update cache metadata
        cached_page = CachedPage(
            url=result.url,
            url_hash=url_hash,
            fetch_timestamp=datetime.now(),
            content_hash=content_hash,
            content_length=len(result.content),
            http_status=result.status,
            etag=result.etag,
            last_modified=result.last_modified,
            title=parsed_html.title if parsed_html else None,
            extracted_at=datetime.now() if parsed_html else None,
        )
        cache_metadata.pages[str(result.url)] = cached_page

    async def _process_parsed_content(self, parsed_html: ParsedContent, url: str) -> None:
        """Process parsed HTML content through chunker and embedder"""
        # Convert to format expected by chunker
        markdown_parsed = self._convert_to_markdown_format(parsed_html)

        # Chunk the parsed content
        chunks = await self.chunker.chunk(markdown_parsed, url)
        logger.debug(f"Created {len(chunks)} chunks from {url}")

        # Generate embeddings and store if vector_store is available
        if self.vector_store and chunks:
            # Generate embeddings for all chunks
            chunk_texts = [chunk.content for chunk in chunks]
            embeddings = await self.embedder.embed_batch(
                chunk_texts, batch_size=config.embedding_batch_size
            )

            # Store chunks and embeddings in vector store
            for chunk, embedding in zip(chunks, embeddings, strict=True):
                await self.vector_store.insert_chunk(chunk, embedding)

            logger.debug(f"Stored {len(chunks)} chunks and embeddings for {url}")

    def _update_cache_metadata(
        self,
        cache_metadata: CacheMetadata | None,
        start_time: datetime,
        discovered_urls: list[HttpUrl],
        urls_to_fetch: list[HttpUrl],
        pages_updated: int,
        pages_failed: int,
        failed_urls: list[str],
        total_bytes: int,
    ) -> CacheMetadata:
        """Update cache metadata with sync results"""
        if cache_metadata is None:
            cache_metadata = CacheMetadata(
                base_url=str(self.base_url),
                last_full_sync=start_time,
                total_pages=0,
            )

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        cache_metadata.last_full_sync = start_time
        cache_metadata.last_incremental_sync = end_time
        cache_metadata.total_pages = len(cache_metadata.pages)
        cache_metadata.sync_stats = SyncStats(
            started_at=start_time,
            completed_at=end_time,
            duration_seconds=duration,
            pages_discovered=len(discovered_urls),
            pages_fetched=len(urls_to_fetch),
            pages_cached=len(discovered_urls) - len(urls_to_fetch),
            pages_updated=pages_updated,
            pages_failed=pages_failed,
            failed_urls=failed_urls,
            total_bytes_fetched=total_bytes,
            cache_hit_rate=(
                (len(discovered_urls) - len(urls_to_fetch)) / len(discovered_urls)
                if len(discovered_urls) > 0
                else 0.0
            ),
        )

        # Save cache metadata
        self._save_cache_metadata(cache_metadata)
        return cache_metadata

    async def get_current_sync_status(self) -> dict[str, object]:
        """
        Get current synchronization status

        Returns:
            Dictionary with sync status information

        Raises:
            None - returns empty dict if no sync performed yet
        """
        cache_metadata = self._load_cache_metadata()

        if not cache_metadata:
            return {}

        # Calculate cache size
        cache_size_bytes = sum(
            f.stat().st_size for f in self.pages_dir.glob("*.html") if f.is_file()
        )
        cache_size_mb = cache_size_bytes / (1024 * 1024)

        return {
            "last_sync": (cache_metadata.last_full_sync if cache_metadata.last_full_sync else None),
            "total_pages": cache_metadata.total_pages,
            "cache_size_mb": cache_size_mb,
            "last_sync_duration_seconds": (
                cache_metadata.sync_stats.duration_seconds if cache_metadata.sync_stats else 0.0
            ),
            "last_sync_stats": cache_metadata.sync_stats,
        }

    async def clear_cache(self) -> None:
        """
        Clear website cache (forces full re-fetch on next sync)

        Deletes all cached HTML files and metadata
        """
        if self.cache_dir.exists():
            # Delete all HTML files
            for html_file in self.pages_dir.glob("*.html"):
                html_file.unlink()

            # Delete metadata
            if self.metadata_file.exists():
                self.metadata_file.unlink()

            logger.info("Cache cleared")

    async def get_pages_list(self) -> list[str]:
        """
        Get list of all cached documentation page URLs

        Returns:
            List of URLs (as strings) in cache

        Raises:
            None - returns empty list if no pages cached
        """
        cache_metadata = self._load_cache_metadata()

        if not cache_metadata:
            return []

        return list(cache_metadata.pages.keys())

    def _load_cache_metadata(self) -> CacheMetadata | None:
        """Load cache metadata from JSON file"""
        if not self.metadata_file.exists():
            return None

        try:
            data = json.loads(self.metadata_file.read_text(encoding="utf-8"))
            return CacheMetadata(**data)
        except Exception as e:
            logger.error(f"Failed to load cache metadata: {e}")
            return None

    def _save_cache_metadata(self, metadata: CacheMetadata) -> None:
        """Save cache metadata to JSON file"""
        try:
            self.metadata_file.write_text(metadata.model_dump_json(indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to save cache metadata: {e}")
            raise SyncError(f"Failed to save cache metadata: {e}", e) from e

    def _convert_to_markdown_format(self, html_parsed: ParsedContent) -> MarkdownParsedContent:
        """
        Convert HtmlParser's ParsedContent to format expected by Chunker

        Args:
            html_parsed: ParsedContent from HtmlParser

        Returns:
            ParsedContent in format expected by Chunker (from doc_parser)
        """
        # Don't create sections to avoid duplicate chunks
        # Previously, this created one section per heading with the same content,
        # resulting in N duplicate chunks for N headings
        # Now we pass empty sections and let the chunker handle the full content once
        return MarkdownParsedContent(
            text=html_parsed.main_content,
            title=html_parsed.title,
            sections=[],  # Empty - let chunker handle the full content
            metadata=html_parsed.metadata,
        )
