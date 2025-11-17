"""Extract and parse documentation content from HTML"""

import html
import logging
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from pydantic import HttpUrl

from src.models.website_cache import ParsedContent

logger = logging.getLogger(__name__)


class ParseError(Exception):
    """Raised when HTML parsing fails"""

    def __init__(self, url: str, message: str):
        self.url = url
        self.message = message
        super().__init__(f"Failed to parse {url}: {message}")


class HtmlParser:
    """Extract and parse documentation content from HTML"""

    def __init__(self) -> None:
        """Initialize parser"""
        pass

    def parse(self, html_content: str, url: HttpUrl, *, validation: bool = True) -> ParsedContent:
        """
        Parse HTML and extract documentation content

        Args:
            html_content: HTML content to parse
            url: Source URL (for context and link resolution)
            validation: Whether to validate content quality (default: True)

        Returns:
            ParsedContent with extracted text and metadata

        Raises:
            ParseError: If HTML parsing fails
            ValidationError: If validation enabled and content is insufficient
        """
        url_str = str(url)

        if not html_content or not html_content.strip():
            raise ParseError(url_str, "HTML content is empty")

        # Parse HTML with BeautifulSoup
        soup = BeautifulSoup(html_content, "lxml")

        # Extract main content
        main_content, extraction_method = self.extract_main_content(soup)

        if not main_content or not main_content.strip():
            raise ParseError(url_str, "No main content found")

        # Clean text
        main_content = self.clean_text(main_content)

        # Extract title
        title = self._extract_title(soup)
        if not title:
            raise ParseError(url_str, "No title found")

        # Extract other elements
        headings = self._extract_headings(soup)
        code_blocks = self._extract_code_blocks(soup)
        links = self.extract_links(soup, url_str)
        metadata = self.extract_metadata(soup)

        # Calculate word count
        word_count = len(main_content.split())

        # Create ParsedContent
        parsed = ParsedContent(
            url=url,
            title=title,
            main_content=main_content,
            headings=headings,
            code_blocks=code_blocks,
            links=links,
            metadata=metadata,
            extraction_method=extraction_method,
            word_count=word_count,
        )

        if validation:
            self._validate_content(parsed)

        logger.info(f"Parsed {url_str} using '{extraction_method}' ({word_count} words)")
        return parsed

    def extract_main_content(self, soup: BeautifulSoup) -> tuple[str, str]:
        """
        Extract main content area from parsed HTML

        Args:
            soup: BeautifulSoup parsed HTML

        Returns:
            Tuple of (main_content_text, extraction_method)
            extraction_method is one of: 'main_tag', 'article_tag', 'content_div', 'fallback'

        Raises:
            ParseError: If no content can be extracted
        """
        # Strategy 1: Look for <main> tag
        main_tag = soup.find("main")
        if main_tag:
            return main_tag.get_text(separator="\n", strip=True), "main_tag"

        # Strategy 2: Look for <article> tag
        article_tag = soup.find("article")
        if article_tag:
            return article_tag.get_text(separator="\n", strip=True), "article_tag"

        # Strategy 3: Look for common content div classes
        content_classes = [
            "content",
            "main-content",
            "documentation",
            "article",
            "doc-content",
            "markdown-body",
        ]
        for class_name in content_classes:
            content_div = soup.find("div", class_=class_name)
            if content_div:
                return content_div.get_text(separator="\n", strip=True), "content_div"

        # Strategy 4: Fallback - extract body with aggressive filtering
        logger.warning("Using fallback extraction strategy - no semantic HTML tags found")
        body = soup.find("body")
        if not body:
            raise ParseError("unknown", "No <body> tag found")

        # Remove unwanted elements
        for tag in body.find_all(["nav", "header", "footer", "aside", "script", "style"]):
            tag.decompose()

        # Remove elements with navigation/sidebar classes
        unwanted_classes = [
            "navigation",
            "sidebar",
            "menu",
            "header",
            "footer",
            "breadcrumb",
            "toc",
        ]
        for class_name in unwanted_classes:
            for elem in body.find_all(class_=class_name):
                elem.decompose()

        content = body.get_text(separator="\n", strip=True)
        return content, "fallback"

    def extract_links(self, soup: BeautifulSoup, base_url: str) -> list[str]:
        """
        Extract all internal links from HTML

        Args:
            soup: BeautifulSoup parsed HTML
            base_url: Base URL for resolving relative links

        Returns:
            List of absolute URLs (deduplicated)
        """
        links = []
        base_parsed = urlparse(base_url)

        for link in soup.find_all("a", href=True):
            href = link["href"]

            try:
                # Resolve relative URLs
                absolute_url = urljoin(base_url, href)
                parsed = urlparse(absolute_url)

                # Remove fragment
                clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

                # Only keep same-domain links
                if parsed.netloc == base_parsed.netloc and clean_url not in links:
                    links.append(clean_url)

            except Exception as e:
                logger.warning(f"Failed to parse link {href}: {e}")
                continue

        return links

    def extract_metadata(self, soup: BeautifulSoup) -> dict[str, str]:
        """
        Extract metadata from HTML (meta tags, title, etc.)

        Args:
            soup: BeautifulSoup parsed HTML

        Returns:
            Dictionary of metadata key-value pairs
        """
        metadata: dict[str, str] = {}

        # Extract meta description
        desc_tag = soup.find("meta", attrs={"name": "description"}) or soup.find(
            "meta", attrs={"property": "og:description"}
        )
        if desc_tag and desc_tag.get("content"):
            metadata["description"] = desc_tag["content"]

        # Extract meta author
        author_tag = soup.find("meta", attrs={"name": "author"})
        if author_tag and author_tag.get("content"):
            metadata["author"] = author_tag["content"]

        # Extract meta keywords
        keywords_tag = soup.find("meta", attrs={"name": "keywords"})
        if keywords_tag and keywords_tag.get("content"):
            metadata["keywords"] = keywords_tag["content"]

        return metadata

    @staticmethod
    def clean_text(text: str) -> str:
        """
        Clean and normalize extracted text

        Args:
            text: Raw text extracted from HTML

        Returns:
            Cleaned text with normalized whitespace
        """
        # Decode HTML entities
        text = html.unescape(text)

        # Collapse multiple spaces to single space
        text = re.sub(r" +", " ", text)

        # Collapse 3+ newlines to 2 newlines (paragraph separation)
        text = re.sub(r"\n{3,}", "\n\n", text)

        # Strip leading/trailing whitespace
        text = text.strip()

        return text

    def _extract_title(self, soup: BeautifulSoup) -> str | None:
        """Extract page title from HTML"""
        # Try <title> tag first
        title_tag = soup.find("title")
        if title_tag and title_tag.string:
            return title_tag.string.strip()

        # Try first <h1> tag
        h1_tag = soup.find("h1")
        if h1_tag:
            return h1_tag.get_text(strip=True)

        # Try og:title meta tag
        og_title = soup.find("meta", attrs={"property": "og:title"})
        if og_title and og_title.get("content"):
            return og_title["content"]

        return None

    def _extract_headings(self, soup: BeautifulSoup) -> list[str]:
        """Extract all headings (h1-h6) in order"""
        headings = []
        for tag_name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
            for tag in soup.find_all(tag_name):
                text = tag.get_text(strip=True)
                if text:
                    headings.append(text)
        return headings

    def _extract_code_blocks(self, soup: BeautifulSoup) -> list[str]:
        """Extract all code block contents"""
        code_blocks = []

        # Extract <pre> blocks
        for pre in soup.find_all("pre"):
            code_text = pre.get_text(strip=True)
            if code_text:
                code_blocks.append(code_text)

        # Extract standalone <code> blocks (not inside <pre>)
        for code in soup.find_all("code"):
            if not code.find_parent("pre"):
                code_text = code.get_text(strip=True)
                if code_text and len(code_text) > 10:  # Only multi-line code
                    code_blocks.append(code_text)

        return code_blocks

    def _validate_content(self, parsed: ParsedContent) -> None:
        """Validate that parsed content meets quality criteria"""
        if parsed.word_count < 10:
            raise ValueError(
                f"Content too short ({parsed.word_count} words). "
                f"Possible extraction failure for {parsed.url}"
            )

        if not parsed.headings:
            logger.warning(f"No headings found in {parsed.url}")

        if not parsed.main_content.strip():
            raise ValueError(f"Main content is empty for {parsed.url}")
