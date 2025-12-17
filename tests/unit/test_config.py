"""Unit tests for configuration"""

from src.config import AppConfig


def test_config_loading_with_website_settings(monkeypatch):
    """Test that configuration loads website cache settings correctly"""
    # Set environment variables
    monkeypatch.setenv("DOCS_WEBSITE_CACHE_PATH", "./test_cache")
    monkeypatch.setenv("DB_PATH", "./test_data/test.db")
    monkeypatch.setenv("EMBEDDING_BATCH_SIZE", "64")
    monkeypatch.setenv("CHUNK_SIZE_TOKENS", "256")

    # Load config
    config = AppConfig()

    # Verify settings
    assert config.docs_website_cache_path == "./test_cache"
    assert config.db_path == "./test_data/test.db"
    assert config.embedding_batch_size == 64
    assert config.chunk_size_tokens == 256


def test_config_defaults():
    """Test that configuration uses correct defaults"""
    # Create config without environment variables
    config = AppConfig()

    # Verify defaults
    assert config.docs_website_cache_path == "./.cache/website_cache"
    assert config.db_path == "./.cache/docs.db"
    assert config.embedding_model == "BAAI/bge-small-en-v1.5"
    assert config.embedding_batch_size == 32
    assert config.chunk_size_tokens == 512
    assert config.chunk_overlap_tokens == 100
    assert config.query_result_limit == 5


def test_environment_variable_precedence(monkeypatch):
    """Test that environment variables take precedence over defaults"""
    # Set only some environment variables
    monkeypatch.setenv("DOCS_WEBSITE_CACHE_PATH", "./custom_cache")
    monkeypatch.setenv("EMBEDDING_BATCH_SIZE", "128")

    # Load config
    config = AppConfig()

    # Verify overridden values
    assert config.docs_website_cache_path == "./custom_cache"
    assert config.embedding_batch_size == 128

    # Verify defaults for non-overridden values
    assert config.db_path == "./.cache/docs.db"
    assert config.chunk_size_tokens == 512
