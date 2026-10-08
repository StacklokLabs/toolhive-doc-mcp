"""Unit tests for the minimal CI sources config and shallow crawling"""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from pydantic import HttpUrl

from src.models.sources_config import FetchingConfig
from src.models.website_cache import FetchResult
from src.services.website_fetcher import WebsiteFetcher
from src.utils.sources_loader import load_sources_config

ROOT = Path(__file__).resolve().parents[2]
BASE_URL = HttpUrl("https://docs.example.com/docs")


def test_ci_sources_config_is_small_and_valid():
    ci = load_sources_config(ROOT / "sources.ci.yaml")
    full = load_sources_config(ROOT / "sources.yaml")

    assert ci.fetching.max_depth == 0
    assert len(ci.get_enabled_websites()) >= 1
    assert len(ci.get_enabled_github_repos()) < len(full.get_enabled_github_repos())


@pytest.mark.asyncio
async def test_discover_pages_depth_zero_returns_start_page_only():
    page = FetchResult(
        url=BASE_URL,
        status=200,
        success=True,
        content='<a href="/docs/a">A</a><a href="/docs/b">B</a>',
        fetch_duration_ms=1.0,
    )
    async with WebsiteFetcher(BASE_URL, "/docs", FetchingConfig(max_depth=0)) as fetcher:
        fetcher.fetch_page = AsyncMock(return_value=page)

        discovered = await fetcher.discover_pages(BASE_URL)

    assert discovered == {BASE_URL}
    fetcher.fetch_page.assert_awaited_once()
