"""Markdown documentation parser"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
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
                self._process_code_block(
                    token, current_heading, text_parts, current_section_content
                )

        # Save last section
        self._save_current_section(sections, current_heading, current_section_content)

        return text_parts, sections, title

    def _process_code_block(
        self,
        token,
        current_heading: str | None,
        text_parts: list[str],
        current_section_content: list[str],
    ) -> None:
        """Process a code block token, parsing YAML/JSON if applicable"""
        # Check if this is a YAML or JSON code block
        if token.type == "fence":
            code_lang = getattr(token, "info", "").strip().lower()
        else:
            code_lang = ""
        code_content = token.content

        # Try to parse YAML/JSON code blocks for better structure
        if code_lang in ("yaml", "yml"):
            parsed_yaml = self._parse_yaml_code_block(code_content, current_heading)
            if parsed_yaml:
                text_parts.append(parsed_yaml)
                current_section_content.append(parsed_yaml)
            else:
                # Fallback to raw content if parsing fails
                text_parts.append(code_content)
                current_section_content.append(code_content)
        elif code_lang == "json":
            parsed_json = self._parse_json_code_block(code_content, current_heading)
            if parsed_json:
                text_parts.append(parsed_json)
                current_section_content.append(parsed_json)
            else:
                # Fallback to raw content if parsing fails
                text_parts.append(code_content)
                current_section_content.append(code_content)
        else:
            # Regular code block - include as-is
            text_parts.append(code_content)
            current_section_content.append(code_content)

    def _parse_yaml_code_block(self, content: str, context_heading: str | None) -> str | None:
        """Parse YAML code block and return enhanced text representation"""
        try:
            data = yaml.safe_load(content)
            if data is None:
                return None

            # Format YAML nicely
            formatted_yaml = yaml.dump(data, default_flow_style=False, sort_keys=False)

            # Create enhanced representation
            parts = ["YAML code block"]
            if context_heading:
                parts.append(f"Context: {context_heading}")
            parts.append(f"Content:\n{content}")

            # Add structured representation if different
            if formatted_yaml != content:
                parts.append(f"Structured format:\n{formatted_yaml}")

            # Add top-level keys if it's a dict
            if isinstance(data, dict):
                keys = list(data.keys())
                if keys:
                    parts.append(f"Top-level keys: {', '.join(str(k) for k in keys)}")

            return "\n\n".join(parts)
        except yaml.YAMLError:
            return None

    def _parse_json_code_block(self, content: str, context_heading: str | None) -> str | None:
        """Parse JSON code block and return enhanced text representation"""
        try:
            data = json.loads(content)

            # Format JSON nicely
            formatted_json = json.dumps(data, indent=2, sort_keys=False)

            # Create enhanced representation
            parts = ["JSON code block"]
            if context_heading:
                parts.append(f"Context: {context_heading}")
            parts.append(f"Content:\n{formatted_json}")

            # Add top-level keys if it's a dict
            if isinstance(data, dict):
                keys = list(data.keys())
                if keys:
                    parts.append(f"Top-level keys: {', '.join(str(k) for k in keys)}")

            return "\n\n".join(parts)
        except json.JSONDecodeError:
            return None

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
