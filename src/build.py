"""Build orchestration: sync, parse, chunk, embed, and persist documentation"""

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.config import config
from src.models.source import DocumentationSource
from src.services.chunker import Chunker
from src.services.doc_parser import DocParser
from src.services.doc_sync import DocSync
from src.services.embedder import Embedder
from src.services.github_fetcher import GitHubFetcher
from src.services.vector_store import VectorStore
from src.utils.sources_loader import load_sources_config


async def _initialize_services():
    """Initialize all required services"""
    doc_parser = DocParser()
    chunker = Chunker()

    # Initialize embedder (downloads model if not cached)
    print(f"  Loading embedding model: {config.embedding_model}")
    print(f"  Cache directory: {config.fastembed_cache_dir}")
    embedder = Embedder()
    embedder.download_model()  # Ensure model is cached
    print(f"✓ Embedding model ready (dimension: {config.embedding_dimension})")

    vector_store = VectorStore()

    try:
        await vector_store.initialize()
        print(f"✓ Database initialized: {config.db_path}")
    except Exception as e:
        print(f"✗ Failed to initialize database: {e}")
        raise

    return doc_parser, chunker, embedder, vector_store


async def _sync_website(website_source, fetching_config):
    """Sync documentation from a website source"""
    print(f"\n  Fetching from website: {website_source.name}")
    print(f"  URL: {website_source.url}")

    try:
        # Create a DocSync instance for this specific website source
        doc_sync = DocSync(
            base_url=website_source.url,
            path_prefix=website_source.path_prefix,
            fetching_config=fetching_config,
        )

        force_refresh = False
        page_count, sync_id = await doc_sync.sync_docs(
            force_refresh=force_refresh, incremental=True
        )

        print(f"  ✓ Synced {page_count} pages from {website_source.name}")
        return page_count, sync_id
    except Exception as e:
        print(f"  ✗ Failed to sync {website_source.name}: {e}")
        raise


async def _sync_github_repo(github_fetcher, chunker, github_source):
    """Sync documentation from a GitHub repository"""
    print(f"\n  Fetching from GitHub: {github_source.name}")
    print(f"  Repo: {github_source.repo_owner}/{github_source.repo_name}")

    try:
        # Fetch files from GitHub
        results, cache_base_path = await github_fetcher.fetch_repo_files(github_source)

        # Create cache directory
        cache_dir = Path(cache_base_path)
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Save markdown files to cache
        successful_results = [r for r in results if r.success]

        for result in successful_results:
            # Save to cache
            file_path = cache_dir / result.path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(result.content, encoding="utf-8")

        print(
            f"  ✓ Fetched {len(successful_results)}/{len(results)} files from {github_source.name}"
        )
        return successful_results, cache_base_path

    except Exception as e:
        print(f"  ✗ Failed to sync {github_source.name}: {e}")
        raise


async def _sync_all_sources(sources_config):
    """Sync documentation from all enabled sources"""
    print("\n[3/8] Fetching documentation from all sources...")

    github_fetcher = GitHubFetcher(sources_config.github)
    chunker = Chunker()

    all_sources_data = []

    try:
        # Sync all enabled websites
        enabled_websites = sources_config.get_enabled_websites()
        print(f"\nProcessing {len(enabled_websites)} website source(s)...")

        for website in enabled_websites:
            page_count, sync_id = await _sync_website(website, sources_config.fetching)
            all_sources_data.append(
                {
                    "type": "website",
                    "name": website.name,
                    "url": str(website.url),
                    "page_count": page_count,
                    "sync_id": sync_id,
                }
            )

        # Sync all enabled GitHub repos
        enabled_repos = sources_config.get_enabled_github_repos()
        print(f"\nProcessing {len(enabled_repos)} GitHub repository source(s)...")

        for repo in enabled_repos:
            results, cache_path = await _sync_github_repo(github_fetcher, chunker, repo)
            all_sources_data.append(
                {
                    "type": "github",
                    "name": repo.name,
                    "repo": f"{repo.repo_owner}/{repo.repo_name}",
                    "file_count": len(results),
                    "cache_path": cache_path,
                }
            )

        print(f"\n✓ Synced {len(all_sources_data)} sources total")
        return all_sources_data

    finally:
        await github_fetcher.close()


async def _parse_and_chunk_all_sources(chunker, sources_config):
    """Parse and chunk all content from all sources"""
    print("\n[4/8] Parsing and chunking content from all sources...")

    all_chunks = []
    total_files = 0

    # Process website HTML files
    enabled_websites = sources_config.get_enabled_websites()
    if enabled_websites:
        print(f"\nProcessing HTML from {len(enabled_websites)} website source(s)...")
        website_chunks, website_files = await _parse_and_chunk_websites(chunker)
        all_chunks.extend(website_chunks)
        total_files += website_files
        print(f"  ✓ Created {len(website_chunks)} chunks from {website_files} HTML pages")

    # Process GitHub markdown, YAML, and JSON files
    enabled_repos = sources_config.get_enabled_github_repos()
    if enabled_repos:
        print(f"\nProcessing files from {len(enabled_repos)} GitHub source(s)...")
        github_chunks, github_files = await _parse_and_chunk_github(chunker, enabled_repos)
        all_chunks.extend(github_chunks)
        total_files += github_files
        print(f"  ✓ Created {len(github_chunks)} chunks from {github_files} files")

    print(f"\n✓ Total: {len(all_chunks)} chunks from {total_files} files")
    return all_chunks, total_files


async def _parse_and_chunk_websites(chunker):
    """Parse and chunk all HTML pages from website cache"""
    cache_path = Path(config.docs_website_cache_path)
    pages_path = cache_path / "pages"
    html_files = list(pages_path.glob("*.html")) if pages_path.exists() else []

    if not html_files:
        return [], 0

    # Load cache metadata to get URL mappings
    url_to_hash = _load_url_mappings(cache_path)

    # Initialize HTML parser
    from src.services.html_parser import HtmlParser

    html_parser = HtmlParser()

    all_chunks = []
    for i, html_file in enumerate(html_files, start=1):
        try:
            chunks = await _process_html_file(html_file, url_to_hash, html_parser, chunker)
            all_chunks.extend(chunks)

            # Progress update
            if i % 10 == 0 or i == len(html_files):
                print(f"    Processed {i}/{len(html_files)} HTML pages...")

        except Exception as e:
            print(f"    ⚠ Warning: Failed to process {html_file.name}: {e}")
            continue

    return all_chunks, len(html_files)


async def _parse_and_chunk_github(chunker, github_sources):
    """Parse and chunk markdown, YAML, and JSON files from GitHub repositories"""
    from src.services.doc_parser import DocParser
    from src.services.example_parser import ExampleParser

    doc_parser = DocParser()
    example_parser = ExampleParser()
    all_chunks = []
    total_files = 0

    for source in github_sources:
        cache_base_path = (
            f"{config.docs_website_cache_path}/github/{source.repo_owner}/{source.repo_name}"
        )
        cache_dir = Path(cache_base_path)

        if not cache_dir.exists():
            continue

        # Find all markdown files
        md_files = list(cache_dir.glob("**/*.md"))
        # Find all YAML files (including .example files)
        yaml_files = (
            list(cache_dir.glob("**/*.yaml"))
            + list(cache_dir.glob("**/*.yml"))
            + list(cache_dir.glob("**/*.yaml.example"))
            + list(cache_dir.glob("**/*.yml.example"))
        )
        # Find all JSON files (including .example files)
        json_files = list(cache_dir.glob("**/*.json")) + list(cache_dir.glob("**/*.json.example"))

        all_files = md_files + yaml_files + json_files
        total_files += len(all_files)

        for i, file_path in enumerate(all_files, start=1):
            try:
                # Read file content
                file_content = file_path.read_text(encoding="utf-8")

                # Determine parser based on file extension
                # Handle .example suffix files (e.g., config.yaml.example)
                ext = file_path.suffix.lower()
                if ext == ".example":
                    # Get the previous extension (e.g., .yaml from config.yaml.example)
                    ext = Path(file_path.stem).suffix.lower()

                if ext == ".md":
                    # Parse markdown
                    parsed = await doc_parser.parse(file_content)
                elif ext in (".yaml", ".yml", ".json"):
                    # Parse YAML or JSON
                    parsed = await example_parser.parse(file_path, file_content)
                else:
                    # Skip unknown file types
                    continue

                # Create source URL (GitHub file URL)
                relative_path = file_path.relative_to(cache_dir)
                source_url = (
                    f"https://github.com/{source.repo_owner}/{source.repo_name}/"
                    f"blob/{source.branch or 'main'}/{relative_path}"
                )

                # Chunk the parsed content
                chunks = await chunker.chunk(parsed, source_url)
                all_chunks.extend(chunks)

                # Progress update
                if i % 10 == 0 or i == len(all_files):
                    print(f"    Processed {i}/{len(all_files)} files from {source.name}...")

            except Exception as e:
                print(f"    ⚠ Warning: Failed to process {file_path.name}: {e}")
                continue

    return all_chunks, total_files


def _load_url_mappings(cache_path):
    """Load URL to hash mappings from cache metadata"""
    metadata_file = cache_path / "metadata.json"
    url_to_hash = {}

    if metadata_file.exists():
        import json

        metadata_json = json.loads(metadata_file.read_text(encoding="utf-8"))
        for url, page_data in metadata_json.get("pages", {}).items():
            url_hash = page_data.get("url_hash")
            if url_hash:
                url_to_hash[url_hash] = url

    return url_to_hash


async def _process_html_file(html_file, url_to_hash, html_parser, chunker):
    """Process a single HTML file and return chunks"""
    html_content = html_file.read_text(encoding="utf-8")
    url_hash = html_file.stem
    source_url = url_to_hash.get(url_hash, f"https://unknown.local/{url_hash}")

    # Parse HTML content
    parsed_html = html_parser.parse(html_content, source_url, validation=False)

    # Convert to format expected by Chunker
    from src.services.doc_parser import ParsedContent as MarkdownParsedContent

    # Don't create sections to avoid duplicate chunks
    # Previously, this created one section per heading with the same content,
    # resulting in N duplicate chunks for N headings
    # Now we pass empty sections and let the chunker handle the full content once
    markdown_parsed = MarkdownParsedContent(
        text=parsed_html.main_content,
        title=parsed_html.title,
        sections=[],  # Empty - let chunker handle the full content
        metadata=parsed_html.metadata,
    )

    return await chunker.chunk(markdown_parsed, source_url)


async def _generate_embeddings(embedder, all_chunks):
    """Generate embeddings for all chunks"""
    print("\n[5/8] Generating embeddings...")
    print(f"Model: {config.embedding_model} (local, no API key required)")
    print(f"Batch size: {config.embedding_batch_size}")
    print(f"Embedding dimension: {config.embedding_dimension}")

    try:
        embeddings = await embedder.embed_batch(
            [chunk.content for chunk in all_chunks],
            batch_size=config.embedding_batch_size,
        )
        print(f"✓ Generated {len(embeddings)} embeddings")
        return embeddings
    except Exception as e:
        print(f"✗ Failed to generate embeddings: {e}")
        print(f"  Error details: {str(e)}")
        await embedder.close()
        raise


async def _persist_to_database(vector_store, all_chunks, embeddings):
    """Persist chunks and embeddings to database"""
    print("\n[6/8] Persisting to database...")

    try:
        for i, (chunk, embedding) in enumerate(zip(all_chunks, embeddings, strict=True), start=1):
            await vector_store.insert_chunk(chunk, embedding)

            if i % 100 == 0 or i == len(all_chunks):
                print(f"  Inserted {i}/{len(all_chunks)} chunks")

        print(f"✓ Persisted {len(all_chunks)} chunks to database")
    except Exception as e:
        print(f"✗ Failed to persist chunks: {e}")
        raise


def _update_metadata(vector_store, total_files_count, all_chunks_count, all_sources_data):
    """Update metadata in database"""
    print("\n[7/8] Updating metadata...")

    try:
        # Store summary of all sources in metadata
        sources_summary = "\n".join(
            [f"{data['type']}: {data['name']}" for data in all_sources_data]
        )

        metadata = DocumentationSource(
            sources_summary=sources_summary,
            local_path=config.docs_website_cache_path,
            total_files=total_files_count,
            total_chunks=all_chunks_count,
        )

        vector_store.conn.execute(
            """
            INSERT OR REPLACE INTO metadata (
                id, sources_summary, local_path, last_sync, total_files, total_chunks
            ) VALUES (1, ?, ?, datetime('now'), ?, ?)
        """,
            (
                metadata.sources_summary,
                metadata.local_path,
                metadata.total_files,
                metadata.total_chunks,
            ),
        )
        vector_store.conn.commit()
        print("✓ Metadata updated")
    except Exception as e:
        print(f"⚠ Warning: Failed to update metadata: {e}")


def _verify_model_cache():
    """Verify model cache and display information"""
    print("\n[8/8] Verifying model cache...")
    cache_path = Path(config.fastembed_cache_dir)
    if cache_path.exists():
        cache_size = sum(f.stat().st_size for f in cache_path.rglob("*") if f.is_file())
        cache_size_mb = cache_size / (1024 * 1024)
        print(f"✓ Model cached: {cache_size_mb:.1f} MB in {config.fastembed_cache_dir}")
    else:
        print("⚠ Model cache directory not found")


def _print_build_summary(total_files_count, all_chunks_count, all_sources_data):
    """Print build completion summary"""
    print("\n" + "=" * 80)
    print("Build Complete!")
    print("=" * 80)
    print(f"Total files processed: {total_files_count}")
    print(f"Total chunks created: {all_chunks_count}")
    print(f"Database path: {config.db_path}")
    print(f"Embedding model: {config.embedding_model} (cached locally)")
    print(f"\nDocumentation sources processed ({len(all_sources_data)}):")
    for source_data in all_sources_data:
        if source_data["type"] == "website":
            print(
                f"  • {source_data['name']}: {source_data['page_count']} pages"
                f" from {source_data['url']}"
            )
        elif source_data["type"] == "github":
            print(
                f"  • {source_data['name']}: {source_data['file_count']} files"
                f" from {source_data['repo']}"
            )
    print(f"\nCache directory: {config.docs_website_cache_path}")
    print("\nYou can now start the MCP server with:")
    print("  uv run python src/mcp_server.py")
    print(f"\nNote: The embedding model is cached at {config.fastembed_cache_dir}")
    print("      and will not be re-downloaded on subsequent runs.")
    print("=" * 80)


async def build(sources_config_path: str = "sources.yaml"):
    """
    Complete build process: sync → parse → chunk → embed → persist

    This orchestrates the entire documentation indexing pipeline.

    Args:
        sources_config_path: Path to sources configuration YAML file
    """
    # Load .env file first (won't override existing env vars)
    if Path(".env").exists():
        load_dotenv()
        print("✓ Loaded environment variables from .env file")

    print("=" * 80)
    print("Documentation Build Process Starting")
    print("=" * 80)

    try:
        # Load sources configuration
        print("\n[1/8] Loading sources configuration...")
        sources_config = load_sources_config(sources_config_path)
        print(f"✓ Loaded configuration from {sources_config_path}")

        # Initialize services
        print("\n[2/8] Initializing services...")
        doc_parser, chunker, embedder, vector_store = await _initialize_services()

        # Sync documentation from all sources
        all_sources_data = await _sync_all_sources(sources_config)

        # Parse and chunk pages from all sources
        all_chunks, total_files_count = await _parse_and_chunk_all_sources(chunker, sources_config)

        # Generate embeddings
        embeddings = await _generate_embeddings(embedder, all_chunks)

        # Persist to database
        await _persist_to_database(vector_store, all_chunks, embeddings)

        # Update metadata
        _update_metadata(vector_store, total_files_count, len(all_chunks), all_sources_data)

        # Verify model cache
        _verify_model_cache()

        # Print summary
        _print_build_summary(total_files_count, len(all_chunks), all_sources_data)

        return 0

    except Exception as e:
        print(f"\n✗ Build failed: {e}")
        return 1
    finally:
        # Cleanup
        if "embedder" in locals():
            await embedder.close()
        if "vector_store" in locals():
            vector_store.close()


def main():
    """Main entry point"""
    # Run full build
    exit_code = asyncio.run(build())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
