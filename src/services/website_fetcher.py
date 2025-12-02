"""HTTP client for fetching documentation pages from website with retry logic and rate limiting"""

import asyncio
import logging
import time
from urllib.parse import urljoin, urlparse

import httpx
from pydantic import HttpUrl

from src.models.sources_config import FetchingConfig
from src.models.website_cache import FetchResult

logger = logging.getLogger(__name__)


class FetchError(Exception):
    """Raised when page fetch fails after all retries"""

    def __init__(self, url: str, status_code: int | None = None, message: str = ""):
        self.url = url
        self.status_code = status_code
        self.message = message
        super().__init__(f"Failed to fetch {url}: {message}")


class WebsiteFetcher:
    """HTTP client for fetching documentation pages with retry and rate limiting"""

    def __init__(
        self, base_url: HttpUrl, path_prefix: str, fetching_config: FetchingConfig | None = None
    ) -> None:
        """
        Initialize fetcher with configuration

        Args:
            base_url: Base URL of the website to fetch from
            path_prefix: Path prefix to limit crawling
            fetching_config: Fetching configuration (optional, uses defaults if None)
        """
        self.base_url = base_url
        self.path_prefix = path_prefix
        self.fetching_config = fetching_config or FetchingConfig()
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(float(self.fetching_config.timeout)),
            follow_redirects=True,
        )
        self.semaphore = asyncio.Semaphore(self.fetching_config.concurrent_limit)
        self._last_request_time = 0.0

    def _validate_url(self, url_str: str) -> None:
        """Validate URL is under allowed domain and path"""
        parsed = urlparse(url_str)
        base_parsed = urlparse(str(self.base_url))

        if parsed.netloc != base_parsed.netloc:
            raise ValueError(f"URL {url_str} is not under allowed domain {base_parsed.netloc}")

        if not parsed.path.startswith(self.path_prefix):
            raise ValueError(f"URL {url_str} is not under allowed path prefix {self.path_prefix}")

    def _create_fetch_result(
        self,
        url: HttpUrl,
        response: httpx.Response,
        start_time: float,
        success: bool,
        error_message: str | None = None,
    ) -> FetchResult:
        """Create FetchResult from HTTP response"""
        duration_ms = (time.time() - start_time) * 1000
        redirected_url = HttpUrl(str(response.url)) if HttpUrl(str(response.url)) != url else None

        return FetchResult(
            url=url,
            status=response.status_code,
            success=success,
            content=response.text if success else None,
            content_type=response.headers.get("content-type"),
            etag=response.headers.get("etag"),
            last_modified=response.headers.get("last-modified"),
            redirected_url=redirected_url,
            error_message=error_message,
            fetch_duration_ms=duration_ms,
        )

    def _create_error_result(
        self,
        url: HttpUrl,
        status: int,
        error_message: str,
        start_time: float,
    ) -> FetchResult:
        """Create FetchResult for error cases"""
        duration_ms = (time.time() - start_time) * 1000

        return FetchResult(
            url=url,
            status=status,
            success=False,
            content=None,
            error_message=error_message,
            fetch_duration_ms=duration_ms,
        )

    def _should_retry(self, status_code: int, attempt: int) -> bool:
        """Check if request should be retried based on status code and attempt"""
        if 400 <= status_code < 500:  # Client errors - don't retry
            return False
        if status_code >= 500 and attempt < self.fetching_config.max_retries - 1:
            return True
        return False

    async def _fetch_with_retries(self, url: HttpUrl, start_time: float) -> FetchResult:
        """Execute HTTP request with retry logic"""
        last_error = None
        last_response = None

        for attempt in range(self.fetching_config.max_retries):
            try:
                async with self.semaphore:
                    await self._enforce_rate_limit()
                    response = await self.client.get(str(url))
                    last_response = response

                    # Handle client errors (4xx) - don't retry
                    if 400 <= response.status_code < 500:
                        logger.warning(f"Client error {response.status_code} for {url}")
                        return self._create_fetch_result(
                            url,
                            response,
                            start_time,
                            success=False,
                            error_message=f"HTTP {response.status_code}: {response.text[:100]}",
                        )

                    # Handle server errors (5xx) - retry with backoff
                    if self._should_retry(response.status_code, attempt):
                        wait_time = 2**attempt
                        logger.warning(
                            f"Server error {response.status_code} for {url}, "
                            f"retry {attempt + 1}/{self.fetching_config.max_retries} "
                            f"after {wait_time}s"
                        )
                        await asyncio.sleep(wait_time)
                        continue

                    # Server error on final attempt
                    if response.status_code >= 500:
                        logger.error(f"All retries failed with {response.status_code} for {url}")
                        return self._create_fetch_result(
                            url,
                            response,
                            start_time,
                            success=False,
                            error_message=f"HTTP {response.status_code} after {attempt + 1} "
                            f"attempts",
                        )

                    # Success case
                    success = 200 <= response.status_code < 300
                    if success:
                        logger.info(f"Successfully fetched {url} ({response.status_code})")

                    return self._create_fetch_result(
                        url,
                        response,
                        start_time,
                        success=success,
                        error_message=None if success else f"HTTP {response.status_code}",
                    )

            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_error = e
                if attempt < self.fetching_config.max_retries - 1:
                    wait_time = 2**attempt
                    error_type = (
                        "Timeout" if isinstance(e, httpx.TimeoutException) else "Network error"
                    )
                    logger.warning(
                        f"{error_type} for {url}, "
                        f"retry {attempt + 1}/{self.fetching_config.max_retries} after {wait_time}s"
                    )
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    # All retries exhausted
                    error_type = (
                        "Timeout" if isinstance(e, httpx.TimeoutException) else "Network error"
                    )
                    logger.error(f"All retries failed with {error_type.lower()} for {url}")
                    return self._create_error_result(
                        url,
                        0,
                        f"{error_type} after {attempt + 1} attempts: {str(e)}",
                        start_time,
                    )

        # Should not reach here, but handle edge case
        error_msg = str(last_error) if last_error else "Unknown error"
        logger.error(f"Fetch failed for {url}: {error_msg}")
        return FetchResult(
            url=url,
            status=last_response.status_code if last_response else 0,
            success=False,
            content=None,
            error_message=error_msg,
            fetch_duration_ms=(time.time() - start_time) * 1000,
        )

    async def fetch_page(self, url: HttpUrl, *, use_cache: bool = True) -> FetchResult:
        """
        Fetch a single documentation page

        Args:
            url: URL to fetch
            use_cache: Whether to check cache before fetching (default: True)

        Returns:
            FetchResult with content and metadata

        Raises:
            FetchError: If fetch fails after all retries
            ValueError: If URL is invalid or not allowed by path prefix
        """
        url_str = str(url)
        start_time = time.time()

        # Validate URL is under allowed domain and path
        self._validate_url(url_str)

        # Check cache if use_cache=True
        # if use_cache:
        #     pass

        # Fetch with retry logic
        result = await self._fetch_with_retries(url, start_time)

        # Store successful results in cache
        # if use_cache and result.success:
        #     pass

        return result

    async def fetch_multiple(
        self,
        urls: list[HttpUrl],
        *,
        use_cache: bool = True,
        fail_fast: bool = False,
    ) -> list[FetchResult]:
        """
        Fetch multiple pages concurrently with rate limiting

        Args:
            urls: List of URLs to fetch
            use_cache: Whether to check cache before fetching (default: True)
            fail_fast: If True, stop on first error; if False, continue (default: False)

        Returns:
            List of FetchResults (same order as input URLs)
            Failed fetches have success=False in FetchResult

        Raises:
            FetchError: Only if fail_fast=True and a fetch fails
        """
        if not urls:
            return []

        async def fetch_with_error_handling(url: HttpUrl) -> FetchResult:
            try:
                result = await self.fetch_page(url, use_cache=use_cache)

                # If fail_fast is True and result is a failure, raise error
                if fail_fast and not result.success:
                    raise FetchError(
                        str(url),
                        result.status,
                        result.error_message or "Fetch failed",
                    )

                return result

            except FetchError as e:
                # This would only happen from ValueError in fetch_page or fail_fast above
                if fail_fast:
                    raise
                # Return error result
                return FetchResult(
                    url=url,
                    status=e.status_code or 0,
                    success=False,
                    error_message=e.message,
                    fetch_duration_ms=0.0,
                )
            except ValueError as e:
                # URL validation error
                error_result = FetchResult(
                    url=url,
                    status=0,
                    success=False,
                    error_message=str(e),
                    fetch_duration_ms=0.0,
                )
                if fail_fast:
                    raise FetchError(str(url), 0, str(e)) from e
                return error_result

        # Fetch all URLs concurrently (or fail fast on first error)
        if fail_fast:
            # Use return_exceptions=False so first exception stops all tasks
            tasks = [fetch_with_error_handling(url) for url in urls]
            try:
                results = await asyncio.gather(*tasks, return_exceptions=False)
                return list(results)
            except FetchError:
                # Re-raise to caller
                raise
        else:
            # Continue processing all URLs even if some fail
            tasks = [fetch_with_error_handling(url) for url in urls]
            results = await asyncio.gather(*tasks, return_exceptions=False)
            return list(results)

    async def discover_pages(
        self, start_url: str | HttpUrl, *, max_depth: int | None = None
    ) -> set[HttpUrl]:
        """
        Discover documentation pages by crawling from start URL

        Args:
            start_url: Initial URL to begin crawling
            max_depth: Maximum crawl depth (None = use config default)

        Returns:
            Set of discovered URLs (absolute URLs as strings)

        Raises:
            FetchError: If start URL cannot be fetched
            ValueError: If start URL is invalid
        """
        max_depth = max_depth or self.fetching_config.max_depth
        discovered: set[HttpUrl] = set()
        to_visit: list[tuple[str, int]] = [(str(start_url), 0)]  # (url, depth)
        visited: set[str] = set()

        base_netloc = urlparse(str(self.base_url)).netloc
        path_prefix = self.path_prefix

        while to_visit:
            url, depth = to_visit.pop(0)

            if url in visited or depth > max_depth:
                continue

            visited.add(url)
            discovered.add(HttpUrl(url))

            # Fetch page to extract links
            try:
                result = await self.fetch_page(HttpUrl(url), use_cache=False)
                if not result.success or not result.content:
                    logger.warning(f"Failed to fetch {url} for link discovery")
                    continue

                # Extract links from HTML (simple approach - will be improved by HtmlParser)
                from bs4 import BeautifulSoup

                soup = BeautifulSoup(result.content, "lxml")
                for link in soup.find_all("a", href=True):
                    href = link["href"]

                    # Resolve relative URLs
                    absolute_url = urljoin(url, href)
                    parsed = urlparse(absolute_url)

                    # Filter: same domain and path prefix
                    if (
                        parsed.netloc == base_netloc
                        and parsed.path.startswith(path_prefix)
                        and absolute_url not in visited
                    ):
                        # Remove fragment
                        clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                        if clean_url not in visited:
                            to_visit.append((clean_url, depth + 1))

            except (FetchError, ValueError) as e:
                logger.error(f"Error discovering links from {url}: {e}")
                continue

        logger.info(f"Discovered {len(discovered)} pages starting from {start_url}")
        return discovered

    async def _enforce_rate_limit(self) -> None:
        """Enforce rate limiting delay between requests"""
        if self.fetching_config.delay_ms > 0:
            delay_seconds = self.fetching_config.delay_ms / 1000.0
            current_time = time.time()
            elapsed = current_time - self._last_request_time

            if elapsed < delay_seconds:
                await asyncio.sleep(delay_seconds - elapsed)

            self._last_request_time = time.time()

    async def close(self) -> None:
        """
        Close HTTP client and cleanup resources

        Should be called when fetcher is no longer needed
        """
        await self.client.aclose()

    async def __aenter__(self) -> "WebsiteFetcher":
        """Context manager entry"""
        return self

    async def __aexit__(self, *args: object) -> None:
        """Context manager exit - closes client"""
        await self.close()
