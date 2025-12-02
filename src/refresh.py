"""CLI command for executing refresh operations"""

import logging
import sys
from datetime import datetime

from src.services.refresh_orchestrator import RefreshOrchestrator
from src.utils.sources_loader import load_sources_config


def setup_logging() -> None:
    """Configure logging for CLI (stdout for K8s)"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def main() -> int:
    """
    Main entry point for refresh CLI command

    Returns:
        int: Exit code (0 for success, 1 for failure)
    """
    setup_logging()
    logger = logging.getLogger(__name__)

    try:
        logger.info("Starting refresh operation")
        logger.info(f"Timestamp: {datetime.now().isoformat()}")

        # Load configuration
        sources_config = load_sources_config()
        refresh_config = sources_config.refresh
        logger.info(f"Loaded config: interval={refresh_config.interval_hours}h")

        # Check if enabled (warn but don't fail)
        if not refresh_config.enabled:
            logger.warning("Refresh is disabled in configuration")
            logger.info("Exiting with success (NoOp due to disabled config)")
            return 0

        # Initialize and execute
        logger.info("Initializing RefreshOrchestrator")
        orchestrator = RefreshOrchestrator()

        logger.info("Executing refresh_once()")
        result = orchestrator.refresh_once()

        # Log results
        if result.success:
            logger.info(f"Refresh completed successfully in {result.duration_seconds:.2f}s")
            return 0
        else:
            logger.error(f"Refresh failed: {result.error}")
            return 1

    except FileNotFoundError as e:
        logger.error(f"Configuration file not found: {e}")
        return 1
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
