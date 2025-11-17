"""Markdown documentation parser"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from markdown_it import MarkdownIt
from mdit_py_plugins.front_matter import front_matter_plugin


@dataclass
class ParsedContent:
    """Structured content extracted from markdown"""

    text: str
    title: str | None = None
    sections: list[tuple[str, str]] = field(default_factory=list)  # [(heading, content), ...]
    metadata: dict[str, Any] = field(default_factory=dict)


class DocParser:
    """Parse markdown documentation and extract structured content"""

    def __init__(self):
        # Initialize markdown-it parser with plugins
        self.md = MarkdownIt("commonmark", {"breaks": True, "html": True})
        self.md.use(front_matter_plugin)
        self.md.enable("table")

    async def parse(self, file_path: Path | str) -> ParsedContent:
        """
        Parse markdown file and extract content with structure

        Args:
            file_path: Path to markdown file or markdown content as string

        Returns:
            ParsedContent: Structured content with text, sections, and metadata
        """
        # Read file content if Path provided, otherwise use string directly
        content = self._read_content(file_path)

        # Parse markdown to tokens
        tokens = self.md.parse(content)

        # Extract text and structure
        text_parts, sections, title = self._process_tokens(tokens)

        # Combine all text
        full_text = " ".join(text_parts)

        return ParsedContent(text=full_text, title=title, sections=sections, metadata={})

    def _read_content(self, file_path: Path | str) -> str:
        """Read content from file path or return string directly"""
        if isinstance(file_path, Path):
            return file_path.read_text(encoding="utf-8")
        return file_path

    def _process_tokens(self, tokens: list) -> tuple[list[str], list[tuple[str, str]], str | None]:
        """Process markdown tokens and extract text parts, sections, and title"""
        text_parts = []
        sections = []
        current_heading = None
        current_section_content = []
        title = None
        is_first_heading = True

        for token in tokens:
            if token.type == "heading_open":
                # Save previous section before starting new one
                self._save_current_section(sections, current_heading, current_section_content)
                current_section_content = []
                current_heading = None
            elif token.type == "inline" and token.content:
                text_parts.append(token.content)

                # Check if this is heading content (previous token was heading_open)
                if current_heading is None:
                    # This is a heading
                    if is_first_heading:
                        title = token.content
                        is_first_heading = False
                    current_heading = token.content
                    # Include the heading text itself in the section content
                    current_section_content.append(token.content)
                else:
                    # This is regular content under the current heading
                    current_section_content.append(token.content)
            elif token.type in ("code_block", "fence") and token.content:
                text_parts.append(token.content)
                current_section_content.append(token.content)

        # Save last section
        self._save_current_section(sections, current_heading, current_section_content)

        return text_parts, sections, title

    def _save_current_section(
        self, sections: list, heading: str | None, content: list[str]
    ) -> None:
        """Save current section if it has content"""
        if heading and content:
            sections.append((heading, " ".join(content)))

    def extract_headings(self, tokens: list) -> list[str]:
        """Extract all headings from parsed tokens"""
        headings = []
        in_heading = False

        for token in tokens:
            if token.type == "heading_open":
                in_heading = True
            elif token.type == "heading_close":
                in_heading = False
            elif in_heading and token.type == "inline":
                headings.append(token.content)

        return headings
