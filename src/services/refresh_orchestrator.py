"""Orchestrates background refresh of documentation database"""

import asyncio
import logging
import threading
from datetime import datetime

from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.build import build
from src.config import config
from src.models.refresh_config import RefreshResult
from src.services.db_manager import DatabaseManager

logger = logging.getLogger(__name__)


class RefreshOrchestrator:
    """Orchestrates background refresh of documentation database"""

    def __init__(self, db_swap_lock: threading.Lock | None = None):
        """
        Initialize refresh orchestrator

        Args:
            db_swap_lock: Optional lock to coordinate database swaps with service init
        """
        self.config = config
        self.db_manager = DatabaseManager()
        self.scheduler: BackgroundScheduler | None = None
        self.db_swap_lock = db_swap_lock

    def configure_scheduler_sync(
        self,
        scheduler: BackgroundScheduler,
        interval_hours: int,
        max_concurrent_jobs: int = 1,
    ) -> None:
        """
        Configure scheduler with intervals (synchronous version for BackgroundScheduler)

        Args:
            scheduler: Initialized BackgroundScheduler instance
            interval_hours: Refresh interval in hours
            max_concurrent_jobs: Maximum concurrent refresh jobs
        """
        self.scheduler = scheduler

        # Create trigger based on interval
        trigger = IntervalTrigger(
            hours=interval_hours,
            start_date=datetime.now(),
        )

        # Add job to scheduler
        self.scheduler.add_job(
            self.refresh_once,
            trigger=trigger,
            id="doc_refresh",
            name="Documentation Database Refresh",
            max_instances=max_concurrent_jobs,
            replace_existing=True,
        )

        logger.info(f"Scheduled refresh every {interval_hours} hours")

    def stop_scheduler_sync(self) -> None:
        """Gracefully stop scheduler (synchronous version)"""
        if self.scheduler:
            try:
                self.scheduler.remove_job("doc_refresh")
                logger.info("Stopped refresh scheduler")
            except JobLookupError:
                logger.warning("Refresh job not found during shutdown")

    def refresh_once(self) -> RefreshResult:
        """
        Execute single refresh cycle

        Process:
        1. Remove stale temp DBs
        2. Create temp database at docs.db.new
        3. Run build process into temp DB
        4. Verify integrity
        5. Swap atomically
        6. Clean up old backups

        Note: This is synchronous because BackgroundScheduler runs in threads.
        We use asyncio.run() to bridge to async build operations.

        Returns:
            RefreshResult: Result of refresh operation
        """
        start_time = datetime.now()

        try:
            logger.info("Starting database refresh")

            # Step 1: Cleanup stale databases
            self.db_manager.cleanup_stale_databases()

            # Step 2: Run rebuild process (async wrapped in sync)
            asyncio.run(
                build(
                    sources_config_path="sources.yaml",
                    db_path=self.config.db_temp_path,
                )
            )

            logger.info("Build completed, proceeding to swap databases")

            # Step 3: Atomic swap (includes integrity check)
            # Pass lock to coordinate with service initialization in MCP server
            self.db_manager.swap_databases(
                temp_path=self.config.db_temp_path,
                active_path=self.config.db_path,
                lock=self.db_swap_lock,
            )

            # Update result timing
            end_time = datetime.now()
            duration_seconds = (end_time - start_time).total_seconds()

            logger.info(f"Refresh completed successfully in {duration_seconds:.2f}s")

            return RefreshResult(
                success=True,
                start_time=start_time,
                end_time=end_time,
                duration_seconds=duration_seconds,
                error=None,
            )

        except Exception as e:
            logger.error(f"Refresh failed with exception: {e}", exc_info=True)
            end_time = datetime.now()
            result = RefreshResult(
                success=False,
                start_time=start_time,
                end_time=end_time,
                duration_seconds=(end_time - start_time).total_seconds(),
                error=str(e),
            )
            return result
