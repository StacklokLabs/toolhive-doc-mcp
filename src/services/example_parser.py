"""Parser for YAML and JSON example files"""

import json
from pathlib import Path
from typing import Any

import yaml

from src.services.doc_parser import ParsedContent


class ExampleParser:
    """Parse YAML and JSON example files and extract structured content"""

    async def parse(self, file_path: Path | str, file_content: str | None = None) -> ParsedContent:
        """
        Parse YAML or JSON file and extract content with structure

        Args:
            file_path: Path to file (used to determine type and name)
            file_content: Optional file content (if None, will read from file_path)

        Returns:
            ParsedContent: Structured content with text, sections, and metadata
        """
        # Read file content if not provided
        if file_content is None:
            if isinstance(file_path, Path):
                content = file_path.read_text(encoding="utf-8")
                file_name = file_path.name
            else:
                # If file_path is a string, treat it as content
                content = file_path
                file_name = "example"
        else:
            content = file_content
            if isinstance(file_path, Path):
                file_name = file_path.name
            else:
                file_name = str(file_path)

        # Determine file type from extension
        if isinstance(file_path, Path):
            ext = file_path.suffix.lower()
        else:
            # Try to infer from content or default to yaml
            ext = ".yaml"

        # Parse based on file type
        if ext in (".yaml", ".yml"):
            return self._parse_yaml(content, file_name)
        elif ext == ".json":
            return self._parse_json(content, file_name)
        else:
            # Default: treat as plain text
            return ParsedContent(
                text=content,
                title=file_name,
                sections=[],
                metadata={"file_type": ext[1:] if ext else "unknown"},
            )

    def _parse_yaml(self, content: str, file_name: str) -> ParsedContent:
        """Parse YAML content and create structured representation"""
        try:
            # Parse YAML to get structure
            data = yaml.safe_load(content)
            if data is None:
                # Empty or comment-only YAML
                return ParsedContent(
                    text=content,
                    title=file_name,
                    sections=[],
                    metadata={"file_type": "yaml", "parsed": False},
                )

            # Format YAML nicely for embedding
            formatted_yaml = yaml.dump(data, default_flow_style=False, sort_keys=False)

            # Extract top-level keys as sections
            sections = []
            if isinstance(data, dict):
                for key, value in data.items():
                    # Format the value as YAML
                    value_yaml = yaml.dump({key: value}, default_flow_style=False, sort_keys=False)
                    sections.append((str(key), value_yaml))

            # Combine original content (with comments) and formatted version
            # Include both to preserve comments and formatting
            text_parts = [
                f"YAML file: {file_name}",
                f"Content:\n{content}",
            ]

            # Add formatted version for better searchability
            if formatted_yaml != content:
                text_parts.append(f"Formatted structure:\n{formatted_yaml}")

            full_text = "\n\n".join(text_parts)

            return ParsedContent(
                text=full_text,
                title=file_name,
                sections=sections,
                metadata={"file_type": "yaml", "parsed": True, "top_level_keys": list(data.keys()) if isinstance(data, dict) else []},
            )

        except yaml.YAMLError as e:
            # If YAML parsing fails, return raw content
            return ParsedContent(
                text=f"YAML file: {file_name}\n\nContent:\n{content}",
                title=file_name,
                sections=[],
                metadata={"file_type": "yaml", "parse_error": str(e)},
            )

    def _parse_json(self, content: str, file_name: str) -> ParsedContent:
        """Parse JSON content and create structured representation"""
        try:
            # Parse JSON to get structure
            data = json.loads(content)

            # Format JSON nicely for embedding
            formatted_json = json.dumps(data, indent=2, sort_keys=False)

            # Extract top-level keys as sections
            sections = []
            if isinstance(data, dict):
                for key, value in data.items():
                    # Format the value as JSON
                    value_json = json.dumps({key: value}, indent=2, sort_keys=False)
                    sections.append((str(key), value_json))

            # Combine original and formatted version
            text_parts = [
                f"JSON file: {file_name}",
                f"Content:\n{formatted_json}",
            ]

            full_text = "\n\n".join(text_parts)

            return ParsedContent(
                text=full_text,
                title=file_name,
                sections=sections,
                metadata={"file_type": "json", "parsed": True, "top_level_keys": list(data.keys()) if isinstance(data, dict) else []},
            )

        except json.JSONDecodeError as e:
            # If JSON parsing fails, return raw content
            return ParsedContent(
                text=f"JSON file: {file_name}\n\nContent:\n{content}",
                title=file_name,
                sections=[],
                metadata={"file_type": "json", "parse_error": str(e)},
            )

