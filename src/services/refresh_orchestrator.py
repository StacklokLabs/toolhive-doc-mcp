"""Orchestrates background refresh of documentation database"""

import logging
import time
from datetime import datetime

from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.models.refresh_config import RefreshResult

logger = logging.getLogger(__name__)


class RefreshOrchestrator:
    """Orchestrates background refresh of documentation database"""

    def __init__(self):
        """
        Initialize refresh orchestrator

        Args:
            enabled: Whether background refresh is enabled
        """
        self.scheduler: BackgroundScheduler | None = None
        self.is_refreshing = False

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
        Execute single refresh cycle (NoOp implementation)

        This is a placeholder implementation that simulates a refresh
        without actually performing any database operations.

        Note: This is synchronous because BackgroundScheduler runs in threads.

        Returns:
            RefreshResult: Result of refresh operation
        """
        if self.is_refreshing:
            logger.warning("Refresh already in progress, skipping")
            return RefreshResult(
                success=False,
                start_time=datetime.now(),
                end_time=datetime.now(),
                duration_seconds=0.0,
                error="Refresh already in progress",
            )

        self.is_refreshing = True
        start_time = datetime.now()

        try:
            logger.info("Starting NoOp refresh (placeholder implementation)")

            time.sleep(1)

            logger.info("NoOp refresh completed successfully")

            # Create successful result
            end_time = datetime.now()
            result = RefreshResult(
                success=True,
                start_time=start_time,
                end_time=end_time,
                duration_seconds=(end_time - start_time).total_seconds(),
                error=None,
            )
            logger.info(f"NoOp refresh completed successfully in {result.duration_seconds:.2f}s")
            return result

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
            logger.info(
                f"NoOp refresh failed after {result.duration_seconds:.2f}s "
                f"with error: {result.error}"
            )
            return result

        finally:
            self.is_refreshing = False
