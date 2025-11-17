"""Integration tests for HTML parsing flow"""

import pytest

from src.services.html_parser import HtmlParser
from src.services.website_fetcher import WebsiteFetcher


@pytest.mark.asyncio
async def test_parse_real_documentation():
    """Test parsing actual documentation page structure"""
    from pydantic import HttpUrl

    # Define test URL
    base_url = HttpUrl("https://docs.stacklok.com/toolhive")
    path_prefix = "/toolhive"

    # Fetch a real page
    async with WebsiteFetcher(base_url, path_prefix) as fetcher:
        result = await fetcher.fetch_page(base_url)

        if not result.success:
            pytest.skip("Could not fetch documentation page for parsing test")

        # Parse the HTML
        parser = HtmlParser()
        parsed = parser.parse(result.content, url=str(base_url))

        # Verify parsed content
        assert parsed.title, "No title extracted"
        assert parsed.main_content, "No main content extracted"
        assert parsed.word_count > 10, "Content too short"
        assert len(parsed.headings) > 0, "No headings extracted"

        # Check extraction method was successful (not fallback)
        assert parsed.extraction_method in [
            "main_tag",
            "article_tag",
            "content_div",
        ], f"Used fallback extraction: {parsed.extraction_method}"


@pytest.mark.asyncio
async def test_parse_with_complex_navigation():
    """Test that navigation is properly filtered out"""
    # This test uses a mock HTML with typical documentation site structure
    html = """
    <html>
    <head><title>Test Doc</title></head>
    <body>
        <nav class="navbar">
            <a href="/home">Home</a>
            <a href="/docs">Docs</a>
        </nav>
        <aside class="sidebar">
            <ul>
                <li>Section 1</li>
                <li>Section 2</li>
            </ul>
        </aside>
        <main>
            <h1>Main Documentation</h1>
            <p>This is the actual documentation content that should be extracted.</p>
            <p>It contains useful information for users.</p>
        </main>
        <footer>
            <p>Copyright 2025</p>
        </footer>
    </body>
    </html>
    """

    parser = HtmlParser()
    parsed = parser.parse(html, url="https://example.com/doc")

    # Verify navigation elements are excluded
    assert "navbar" not in parsed.main_content.lower()
    assert "Home" not in parsed.main_content
    assert "sidebar" not in parsed.main_content.lower()
    assert "Section 1" not in parsed.main_content
    assert "Copyright" not in parsed.main_content

    # Verify main content is included
    assert "Main Documentation" in parsed.main_content
    assert "actual documentation content" in parsed.main_content
    assert "useful information" in parsed.main_content


@pytest.mark.asyncio
async def test_parse_preserves_code_blocks():
    """Test that code blocks are properly preserved"""
    html = """
    <html>
    <head><title>Code Example</title></head>
    <body>
        <main>
            <h1>Installation Guide</h1>
            <p>To install, run:</p>
            <pre><code>
pip install package-name
pip install another-package
            </code></pre>
            <p>Then configure it:</p>
            <pre><code>
import package
package.configure(key="value")
            </code></pre>
        </main>
    </body>
    </html>
    """

    parser = HtmlParser()
    parsed = parser.parse(html, url="https://example.com/install")

    # Verify code blocks are extracted
    assert len(parsed.code_blocks) >= 2
    assert any("pip install" in block for block in parsed.code_blocks)
    assert any("package.configure" in block for block in parsed.code_blocks)

    # Verify code is also in main content
    assert "pip install" in parsed.main_content
    assert "configure" in parsed.main_content
