# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Code Quality Requirements

### Linting and Code Checks

**IMPORTANT**: All pull requests MUST pass linting checks before being merged.

Before committing code or creating a PR:

1. **Run linting checks**:
   ```bash
   uv run ruff check src/
   ```

2. **Auto-fix linting issues** (when possible):
   ```bash
   uv run ruff check src/ --fix
   ```

3. **Verify all checks pass**:
   ```bash
   uv run ruff check src/
   ```

The linter enforces:
- Line length (max 100 characters)
- Code complexity (max complexity score of 10)
- Unused imports
- Code style (PEP 8 via pycodestyle)
- Code quality (flake8, bugbear)

**Never commit code that fails linting checks.** Always fix linting issues before creating or updating a PR.

## Project Overview

toolhive-doc-mcp is an MCP server for semantic search over Stacklok documentation using vector embeddings.

## Build and Development Commands

### Essential Commands

```bash
# Install dependencies
uv sync

# Run linting
uv run ruff check src/

# Fix linting issues automatically
uv run ruff check src/ --fix

# Run tests
uv run pytest

# Build documentation database
uv run python src/build.py

# Run MCP server
uv run python src/mcp_server.py
```

## Testing

Run tests with:
```bash
uv run pytest
```

## Configuration

Documentation sources are configured in `sources.yaml`. See `sources.yaml.example` for reference.

Key configuration options:
- `sources.websites`: Website sources to crawl
- `sources.github_repos`: GitHub repositories to fetch files from
- `fetching`: HTTP fetching configuration
- `github`: GitHub API configuration

