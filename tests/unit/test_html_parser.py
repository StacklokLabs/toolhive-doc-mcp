"""Unit tests for HTML parser"""

import pytest

from src.services.html_parser import HtmlParser, ParseError


def test_parse_with_main_tag():
    """Test content extraction from <main> tag"""
    html = """
    <html><body>
        <nav>Navigation</nav>
        <main>
            <h1>Title</h1>
            <p>Content here.</p>
        </main>
        <footer>Footer</footer>
    </body></html>
    """

    parser = HtmlParser()
    parsed = parser.parse(html, url="https://example.com/test", validation=False)

    assert parsed.title == "Title"
    assert "Content here" in parsed.main_content
    assert "Navigation" not in parsed.main_content
    assert "Footer" not in parsed.main_content
    assert parsed.extraction_method == "main_tag"


def test_parse_with_article_tag():
    """Test content extraction from <article> tag"""
    html = """
    <html><body>
        <header>Header</header>
        <article>
            <h1>Article Title</h1>
            <p>Article content goes here.</p>
        </article>
        <aside>Sidebar</aside>
    </body></html>
    """

    parser = HtmlParser()
    parsed = parser.parse(html, url="https://example.com/article", validation=False)

    assert parsed.title == "Article Title"
    assert "Article content" in parsed.main_content
    assert "Header" not in parsed.main_content
    assert "Sidebar" not in parsed.main_content
    assert parsed.extraction_method == "article_tag"


def test_parse_with_content_div():
    """Test content extraction from div.content"""
    html = """
    <html><body>
        <nav class="navigation">Nav</nav>
        <div class="content">
            <h1>Page Title</h1>
            <p>Main content text.</p>
        </div>
        <footer class="footer">Footer</footer>
    </body></html>
    """

    parser = HtmlParser()
    parsed = parser.parse(html, url="https://example.com/page", validation=False)

    assert parsed.title == "Page Title"
    assert "Main content text" in parsed.main_content
    assert "Nav" not in parsed.main_content
    assert "Footer" not in parsed.main_content
    assert parsed.extraction_method == "content_div"


def test_parse_fallback_strategy():
    """Test fallback extraction when no semantic tags present"""
    html = """
    <html><body>
        <nav>Should be removed</nav>
        <div>
            <h1>Fallback Title</h1>
            <p>This is the main content.</p>
        </div>
        <footer>Should also be removed</footer>
    </body></html>
    """

    parser = HtmlParser()
    parsed = parser.parse(html, url="https://example.com/fallback", validation=False)

    assert parsed.title == "Fallback Title"
    assert "main content" in parsed.main_content
    assert "Should be removed" not in parsed.main_content
    assert parsed.extraction_method == "fallback"


def test_extract_links_with_relative_urls():
    """Test link extraction with relative URLs"""
    html = """
    <html>
    <head><title>Links Test</title></head>
    <body>
        <main>
            <h1>Links</h1>
            <a href="/docs/guide">Guide</a>
            <a href="./page">Page</a>
            <a href="../other">Other</a>
            <a href="https://example.com/external">External</a>
        </main>
    </body></html>
    """

    parser = HtmlParser()
    parsed = parser.parse(html, url="https://example.com/docs/current", validation=False)

    # Should resolve relative URLs and filter same-domain links
    # The parser returns absolute URLs for same-domain links
    assert any("example.com/docs/guide" in link for link in parsed.links)
    # External links to different domains should be filtered out
    # Note: example.com is the same domain, so all links will be included except anchors
    assert len(parsed.links) > 0


def test_extract_code_blocks():
    """Test code block preservation"""
    html = """
    <html><body>
        <main>
            <h1>Code Example</h1>
            <pre><code>
def hello():
    print("world")
            </code></pre>
            <p>Text with inline <code>code</code></p>
        </main>
    </body></html>
    """

    parser = HtmlParser()
    parsed = parser.parse(html, url="https://example.com/code", validation=False)

    # Should extract code blocks
    assert len(parsed.code_blocks) > 0
    assert any("hello" in block for block in parsed.code_blocks)


def test_clean_text_whitespace():
    """Test text cleaning and whitespace normalization"""
    text = "Multiple    spaces\n\n\n\nToo many newlines\n\n  "

    parser = HtmlParser()
    cleaned = parser.clean_text(text)

    assert "    " not in cleaned  # Multiple spaces collapsed
    assert "\n\n\n" not in cleaned  # Multiple newlines collapsed
    assert cleaned.strip() == cleaned  # Leading/trailing whitespace removed


def test_clean_text_entities():
    """Test HTML entity decoding"""
    text = "&lt;div&gt; &amp; &quot;quotes&quot;"

    parser = HtmlParser()
    cleaned = parser.clean_text(text)

    assert "<div>" in cleaned
    assert "&" in cleaned
    assert '"quotes"' in cleaned


def test_validation_min_words():
    """Test validation rejects content with too few words"""
    html = """
    <html><body>
        <main>
            <h1>Title</h1>
            <p>Short</p>
        </main>
    </body></html>
    """

    parser = HtmlParser()

    with pytest.raises(ValueError, match="Content too short"):
        parser.parse(html, url="https://example.com/short", validation=True)


def test_parse_empty_html():
    """Test that empty HTML raises ParseError"""
    parser = HtmlParser()

    with pytest.raises(ParseError, match="HTML content is empty"):
        parser.parse("", url="https://example.com/empty")


def test_parse_no_title():
    """Test that missing title raises ParseError"""
    html = """
    <html><body>
        <main>
            <p>Content without title</p>
        </main>
    </body></html>
    """

    parser = HtmlParser()

    with pytest.raises(ParseError, match="No title found"):
        parser.parse(html, url="https://example.com/notitle")


def test_parse_no_main_content():
    """Test that missing main content raises ParseError"""
    html = """
    <html><body>
        <nav>Only navigation</nav>
        <footer>Only footer</footer>
    </body></html>
    """

    parser = HtmlParser()

    with pytest.raises(ParseError, match="No main content"):
        parser.parse(html, url="https://example.com/nocontent")
