# Stacklok Documentation Search MCP Server

MCP server for semantic search over Stacklok documentation using vector embeddings.

## Features

- **Multiple documentation sources**: Supports both websites and GitHub repositories
  - Website crawling with automatic page discovery
  - GitHub repository markdown file fetching with glob pattern matching
  - Configurable via YAML configuration file
- **Robust HTML parsing**: Multi-strategy content extraction with fallback handling
- **Markdown processing**: Native support for markdown files from GitHub repos
- **Error-resilient**: Handles timeouts, 404s, and network errors gracefully with exponential backoff
- **Rate limiting**: Configurable concurrent requests and delays to be respectful of documentation servers
- **Semantic search**: Vector-based similarity search using local embeddings
- **Incremental sync**: Efficient caching to avoid re-fetching unchanged pages
- **GitHub authentication**: Optional token support for higher API rate limits (5000/hour vs 60/hour)

## Quick Start

### 1. Prerequisites

- Python 3.13+
- uv package manager

### 2. Install Dependencies

```bash
uv sync
```

### 3. Configuration

#### Environment Configuration

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Key environment configuration options are available in `.env`, but most settings are now in `sources.yaml`.

#### Sources Configuration

Copy `sources.yaml.example` to `sources.yaml` and customize your documentation sources:

```bash
cp sources.yaml.example sources.yaml
```

The `sources.yaml` file allows you to configure multiple documentation sources:

```yaml
sources:
  # Website sources - crawl and extract documentation from websites
  websites:
    - name: "Stacklok Toolhive Docs"
      url: "https://docs.stacklok.com/toolhive"
      path_prefix: "/toolhive"
      enabled: true

  # GitHub repository sources - fetch markdown files from specific repos
  github_repos:
    - name: "Stacklok Toolhive Docs"
      repo_owner: "stacklok"
      repo_name: "toolhive"
      branch: "main"
      paths:
        - "docs/**/*.md"
        - "README.md"
      enabled: true

# Fetching configuration
fetching:
  timeout: 30
  max_retries: 3
  concurrent_limit: 5
  delay_ms: 100
  max_depth: 5

# GitHub API configuration (optional)
github:
  token: null  # Or set GITHUB_TOKEN env var for higher rate limits
```

### 4. Build Documentation Index

Run the build process to fetch, parse, chunk, embed, and index all documentation:

```bash
uv run python src/build.py
```

This will:
1. Load your sources configuration from `sources.yaml`
2. Fetch documentation from all enabled website sources
3. Fetch markdown files from all enabled GitHub repository sources
4. Parse and chunk all content
5. Generate embeddings using the local model (downloaded automatically on first run)
6. Persist everything to the SQLite vector database

The process displays detailed progress and a summary at the end.

### 5. Start the MCP Server

```bash
uv run python src/mcp_server.py
```

Server will be available at: `http://localhost:8080`

### 6. Query the Server

```bash
curl -X POST http://localhost:8080/sse \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "query_docs",
      "arguments": {
        "query": "What is toolhive?",
        "limit": 5
      }
    }
  }'
```

## Development

### Run Tests

```bash
task test
```

### Code Quality

```bash
task format  # Format code
task lint    # Lint code
task typecheck  # Type check
```

## Architecture

### Component Overview

- **Website Fetching**: httpx async client with retry logic and rate limiting
- **GitHub Integration**: GitHub API client with concurrent fetching and authentication support
- **HTML Parsing**: BeautifulSoup4 + lxml with multi-strategy content extraction
- **Embeddings**: Local fastembed model (BAAI/bge-small-en-v1.5) - no API keys required
- **Vector Store**: SQLite + sqlite_vec for vector similarity search
- **MCP Server**: FastMCP with HTTP/SSE protocol
- **Caching**: Filesystem-based HTML cache with JSON metadata
- **Configuration**: YAML-based with Pydantic validation

### Build Process Flow

```
1. Load sources configuration (sources.yaml)
   ↓
2. Initialize services (embedder, vector store, etc.)
   ↓
3. Fetch from all sources
   ├─ Sync website sources (parallel)
   │  └─ Fetch HTML pages with crawling
   └─ Sync GitHub sources (parallel)
      └─ Fetch markdown files via API
   ↓
4. Parse and chunk all content
   ├─ Parse HTML from websites
   └─ Parse markdown from GitHub
   ↓
5. Generate embeddings (local model)
   ↓
6. Persist to vector database
   ↓
7. Update metadata
   ↓
8. Verify and display summary
```

### Module Structure

```
sources.yaml (config)
     ↓
src/utils/sources_loader.py (validation)
     ↓
src/build.py (orchestration)
     ├─ src/services/doc_sync.py (websites)
     │   └─ src/services/website_fetcher.py
     │       └─ src/services/html_parser.py
     └─ src/services/github_fetcher.py (GitHub)
         ↓
     src/services/chunker.py
         ↓
     src/services/embedder.py
         ↓
     src/services/vector_store.py
```

### Key Files

**Configuration:**
- `sources.yaml` - Main configuration file for defining documentation sources
- `sources.yaml.example` - Example configuration with multiple sources
- `src/models/sources_config.py` - Pydantic models for configuration validation
- `src/utils/sources_loader.py` - Utility to load and validate configuration

**Services:**
- `src/services/github_fetcher.py` - Service for fetching files from GitHub repositories
- `src/services/doc_sync.py` - Website documentation synchronization
- `src/services/website_fetcher.py` - HTTP client with retry logic
- `src/services/html_parser.py` - Multi-strategy HTML content extraction
- `src/services/chunker.py` - Document chunking
- `src/services/embedder.py` - Local embedding generation
- `src/services/vector_store.py` - SQLite vector database management

**Build:**
- `src/build.py` - Main build orchestration supporting multiple sources
- `src/mcp_server.py` - MCP server implementation

## Adding New Documentation Sources

### Adding a Website Source

Add a new entry to the `websites` section in `sources.yaml`:

```yaml
sources:
  websites:
    - name: "Your Documentation Site"
      url: "https://docs.example.com"
      path_prefix: "/"  # Or specific path like "/docs"
      enabled: true
```

### Adding a GitHub Repository Source

Add a new entry to the `github_repos` section in `sources.yaml`:

```yaml
sources:
  github_repos:
    - name: "Your Project Docs"
      repo_owner: "your-org"
      repo_name: "your-repo"
      branch: "main"  # Optional
      paths:
        - "docs/**/*.md"
        - "*.md"
      enabled: true
```

After updating `sources.yaml`, run the build process again to index the new sources.

### GitHub Rate Limits

For public repositories, the GitHub API allows 60 requests per hour without authentication. If you need higher limits:

1. Create a personal access token at https://github.com/settings/tokens
2. Set it in `sources.yaml` or as an environment variable:
   ```bash
   export GITHUB_TOKEN=your_token_here
   ```

This increases your limit to 5,000 requests per hour.

## Implementation Details

### GitHub Integration Features

- Fetches files using GitHub API with authentication support
- Supports glob patterns for file matching (e.g., `docs/**/*.md`)
- Concurrent file fetching with configurable rate limiting
- Proper error handling and retry logic for network failures
- Respects GitHub API rate limits

### Configuration Validation

The configuration system uses Pydantic models to validate:
- Required fields for each source type
- Valid URLs and repository identifiers
- Numeric ranges for fetching parameters
- Proper glob patterns for file matching

### Testing

Run the tests to validate the implementation:

```bash
uv run pytest tests
```

Alternately, use task:

```bash
task test
```

## Dependencies

Key dependencies:
- `httpx` - HTTP client with retry support
- `BeautifulSoup4` + `lxml` - HTML parsing
- `aiohttp` - Async HTTP operations
- `fastembed` - Local embeddings (no API required)
- `sqlite-vec` - Vector similarity search
- `pydantic` - Configuration validation
- `pyyaml` - YAML configuration parsing

## Future Enhancements

Possible improvements:
- Support for other source types (GitLab, Bitbucket, etc.)
- Selective re-indexing of specific sources
- Source-specific search filtering
- Automatic source discovery
- Webhook-based incremental updates
- Source-level metadata and tagging