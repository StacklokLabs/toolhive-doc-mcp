"""Utility to load sources configuration from YAML file"""

import logging
import os
from pathlib import Path

import yaml

from src.models.sources_config import SourcesConfig

logger = logging.getLogger(__name__)


def load_sources_config(config_path: str | Path = "sources.yaml") -> SourcesConfig:
    """
    Load sources configuration from YAML file

    Args:
        config_path: Path to sources.yaml file (default: sources.yaml in project root)

    Returns:
        SourcesConfig object

    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config is invalid
    """
    config_path = Path(config_path)

    if not config_path.exists():
        raise FileNotFoundError(
            f"Sources configuration file not found: {config_path}\n"
            f"Please create a sources.yaml file. See sources.yaml.example for reference."
        )

    try:
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data:
            raise ValueError("Sources configuration file is empty")

        sources_config = SourcesConfig(**data)

        # Allow environment variable to override refresh.enabled
        refresh_enabled_env = os.getenv("REFRESH_ENABLED")
        if refresh_enabled_env is not None:
            refresh_enabled = refresh_enabled_env.lower() in ("true", "1", "yes")
            if sources_config.refresh.enabled != refresh_enabled:
                logger.info(
                    f"Overriding refresh.enabled from env: {refresh_enabled} "
                    f"(was: {sources_config.refresh.enabled})"
                )
                sources_config.refresh.enabled = refresh_enabled

        logger.info(f"Loaded sources configuration from {config_path}")
        logger.info(f"  Enabled websites: {len(sources_config.get_enabled_websites())}")
        logger.info(f"  Enabled GitHub repos: {len(sources_config.get_enabled_github_repos())}")
        logger.info(f"  Background refresh enabled: {sources_config.refresh.enabled}")

        return sources_config

    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in sources configuration: {e}") from e
    except Exception as e:
        raise ValueError(f"Failed to load sources configuration: {e}") from e
