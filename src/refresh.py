"""CLI command for executing refresh operations"""

import logging
import sys
from datetime import datetime

from src.services.refresh_orchestrator import RefreshException, RefreshOrchestrator


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

        # Initialize and execute
        logger.info("Initializing RefreshOrchestrator")
        orchestrator = RefreshOrchestrator()

        logger.info("Executing refresh_once()")
        result = orchestrator.refresh_once()

        # Defensive check (should not happen, but good practice)
        if result is None:
            logger.error("Refresh returned None unexpectedly")
            return 1

        logger.info(f"Refresh completed successfully in {result.duration_seconds:.2f}s")
        return 0
    except RefreshException as e:
        logger.error(f"Refresh failed: {e}")
        return 1
    except FileNotFoundError as e:
        logger.error(f"Configuration file not found: {e}")
        return 1
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
