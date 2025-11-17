"""Integration tests for website fetching functionality"""

import pytest
from pydantic import HttpUrl

from src.services.website_fetcher import WebsiteFetcher

# Test configuration
TEST_BASE_URL = HttpUrl("https://docs.stacklok.com/toolhive")
TEST_PATH_PREFIX = "/toolhive"


@pytest.mark.asyncio
async def test_fetch_single_page():
    """Test fetching a single documentation page"""
    async with WebsiteFetcher(TEST_BASE_URL, TEST_PATH_PREFIX) as fetcher:
        # Fetch the base documentation page
        result = await fetcher.fetch_page(TEST_BASE_URL)

        # Verify successful fetch
        assert result.success, f"Fetch failed: {result.error_message}"
        assert result.status == 200
        assert result.content is not None
        assert len(result.content) > 0
        assert result.fetch_duration_ms > 0


@pytest.mark.asyncio
async def test_page_discovery():
    """Test discovering documentation pages from start URL"""
    async with WebsiteFetcher(TEST_BASE_URL, TEST_PATH_PREFIX) as fetcher:
        # Discover pages starting from base URL
        discovered = await fetcher.discover_pages(str(TEST_BASE_URL), max_depth=2)

        # Verify pages were discovered
        assert len(discovered) > 0, "No pages discovered"

        # All discovered pages should be under the path prefix
        for url in discovered:
            assert TEST_PATH_PREFIX in str(url), (
                f"Page {url} not under path prefix {TEST_PATH_PREFIX}"
            )


@pytest.mark.asyncio
async def test_cache_hit_behavior():
    """Test that cache reduces fetch time on subsequent requests"""
    async with WebsiteFetcher(TEST_BASE_URL, TEST_PATH_PREFIX) as fetcher:
        url = TEST_BASE_URL

        # First fetch (no cache)
        result1 = await fetcher.fetch_page(url, use_cache=False)
        first_duration = result1.fetch_duration_ms

        # Second fetch (should use cache if implemented)
        result2 = await fetcher.fetch_page(url, use_cache=True)
        second_duration = result2.fetch_duration_ms

        # Both should succeed
        assert result1.success
        assert result2.success
        assert result1.content == result2.content
        assert first_duration >= second_duration


@pytest.mark.asyncio
async def test_fetch_invalid_url():
    """Test that fetching invalid URLs raises appropriate errors"""
    async with WebsiteFetcher(TEST_BASE_URL, TEST_PATH_PREFIX) as fetcher:
        # Try to fetch URL outside allowed domain
        with pytest.raises(ValueError, match="not under allowed domain"):
            await fetcher.fetch_page(HttpUrl("https://example.com/page"))

        # Try to fetch URL outside allowed path
        from urllib.parse import urlparse

        parsed = urlparse(str(TEST_BASE_URL))
        with pytest.raises(ValueError, match="not under allowed path prefix"):
            await fetcher.fetch_page(HttpUrl(f"{parsed.scheme}://{parsed.netloc}/other"))


@pytest.mark.asyncio
async def test_fetch_multiple_pages():
    """Test fetching multiple pages concurrently"""
    async with WebsiteFetcher(TEST_BASE_URL, TEST_PATH_PREFIX) as fetcher:
        # Discover some pages first
        discovered = await fetcher.discover_pages(str(TEST_BASE_URL), max_depth=1)

        if len(discovered) < 2:
            pytest.skip("Not enough pages discovered for multiple fetch test")

        # Fetch multiple pages
        urls_to_fetch = list(discovered)[:3]  # Fetch up to 3 pages
        results = await fetcher.fetch_multiple(urls_to_fetch, fail_fast=False)

        # Verify results
        assert len(results) == len(urls_to_fetch)

        # Count successful fetches
        successful = sum(1 for r in results if r.success)
        assert successful > 0, "No pages fetched successfully"


@pytest.mark.asyncio
async def test_rate_limiting_behavior():
    """Test that rate limiting enforces delays between requests"""
    import time

    # Use a fetching config with strict rate limiting
    from src.models.sources_config import FetchingConfig

    rate_limited_config = FetchingConfig(
        delay_ms=500,  # 500ms delay between requests
        concurrent_limit=1,  # Only 1 concurrent request
    )

    async with WebsiteFetcher(
        TEST_BASE_URL, TEST_PATH_PREFIX, rate_limited_config
    ) as fetcher:
        # Discover some pages
        discovered = await fetcher.discover_pages(str(TEST_BASE_URL), max_depth=1)

        if len(discovered) < 2:
            pytest.skip("Not enough pages discovered for rate limiting test")

        # Fetch 2 pages and measure time
        urls_to_fetch = list(discovered)[:2]
        start_time = time.time()
        results = await fetcher.fetch_multiple(urls_to_fetch, use_cache=False)
        end_time = time.time()

        # Verify rate limiting was applied
        duration_ms = (end_time - start_time) * 1000

        # With 500ms delay and 2 requests, should take at least 500ms
        # (plus fetch time, so let's check for at least 400ms to account for overhead)
        assert duration_ms >= 400, f"Requests completed too quickly: {duration_ms}ms"

        # Count successful fetches
        successful = sum(1 for r in results if r.success)
        assert successful > 0, "No pages fetched successfully"
