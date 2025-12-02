"""Database manager for atomic database swapping during refreshes"""

import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from src.config import config

logger = logging.getLogger(__name__)


class IntegrityCheckError(Exception):
    """Raised when database integrity check fails"""

    pass


class DatabaseManager:
    """Manages database file operations and atomic swaps"""

    def __init__(self):
        self.config = config

    def _check_db_integrity(self, db_path: str) -> bool:
        """
        Synchronous integrity check

        Raises:
            Exception: If integrity check fails or tables are missing
        """
        if not os.path.exists(db_path):
            error_msg = f"Database file does not exist: {db_path}"
            logger.error(error_msg)
            raise IntegrityCheckError(error_msg)

        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()

            # Run PRAGMA integrity_check
            cursor.execute("PRAGMA integrity_check")
            result = cursor.fetchone()

            if result and result[0] == "ok":
                # Verify critical tables exist
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name IN ('chunks', 'vec_chunks', 'metadata')"
                )
                tables = {row[0] for row in cursor.fetchall()}

                required_tables = {"chunks", "vec_chunks", "metadata"}
                if not required_tables.issubset(tables):
                    missing = required_tables - tables
                    error_msg = f"Missing required tables: {missing}"
                    logger.error(error_msg)
                    raise IntegrityCheckError(error_msg)

                logger.info(f"Database integrity check passed: {db_path}")
                return True
            else:
                error_msg = f"Database integrity check failed: {result}"
                logger.error(error_msg)
                raise IntegrityCheckError(error_msg)

    def swap_databases(self, temp_path: str, active_path: str) -> None:
        """
        Atomically swap temp database with active database

        Process:
        1. Verify temp DB is valid
        2. Create timestamped backup of active DB
        3. Atomic rename: temp → active
        4. On success: keep backup for recovery
        5. On failure: restore from backup and raise exception

        Args:
            temp_path: Path to temporary (new) database
            active_path: Path to active (current) database

        Raises:
            Exception: If swap fails (after attempting rollback)
        """
        logger.info(f"Starting database swap: {temp_path} -> {active_path}")

        # Step 1: Verify temp database (will raise if invalid)
        self._check_db_integrity(temp_path)

        # Step 2: Create backup
        backup_path = f"{active_path}.backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        try:
            # Check if active database exists
            if os.path.exists(active_path):
                logger.info(f"Creating backup: {active_path} -> {backup_path}")
                # Use rename for atomic operation
                os.rename(active_path, backup_path)
            else:
                logger.warning(f"Active database does not exist: {active_path}")
                backup_path = None

            # Step 3: Atomic rename (this is atomic on Unix and Windows)
            logger.info(f"Swapping databases: {temp_path} -> {active_path}")
            os.rename(temp_path, active_path)

            logger.info("Database swap completed successfully")

            # Step 4: Cleanup old backups (keep most recent)
            if backup_path and os.path.exists(backup_path):
                self._cleanup_old_backups(active_path, keep_count=1)

        except Exception as e:
            logger.error(f"Database swap failed: {e}")

            # Step 5: Rollback - restore from backup
            if backup_path and os.path.exists(backup_path):
                try:
                    logger.info("Rolling back to backup database")
                    if os.path.exists(active_path):
                        os.remove(active_path)
                    os.rename(backup_path, active_path)
                    logger.info("Rollback completed")
                except Exception as rollback_error:
                    logger.error(f"Rollback failed: {rollback_error}")
                    # Re-raise with rollback context
                    raise Exception(
                        f"Database swap failed and rollback also failed: {e}"
                    ) from rollback_error

            # Re-raise original exception after rollback
            raise Exception(f"Database swap failed: {e}") from e

    def _cleanup_old_backups(self, db_path: str, keep_count: int = 1) -> None:
        """
        Clean up old backup files, keeping only the most recent ones

        Args:
            db_path: Base database path
            keep_count: Number of recent backups to keep
        """
        try:
            db_dir = Path(db_path).parent
            db_name = Path(db_path).name

            # Find all backup files
            backup_pattern = f"{db_name}.backup-*"
            backups = sorted(db_dir.glob(backup_pattern), key=os.path.getmtime, reverse=True)

            # Remove old backups (keep only keep_count most recent)
            for backup in backups[keep_count:]:
                logger.info(f"Removing old backup: {backup}")
                backup.unlink()

        except Exception as e:
            logger.error(f"Error cleaning up old backups: {e}")

    def cleanup_stale_databases(self) -> None:
        """Clean up any stale temporary databases from previous runs"""
        try:
            temp_path = self.config.db_temp_path
            if os.path.exists(temp_path):
                logger.info(f"Removing stale temp database: {temp_path}")
                os.remove(temp_path)
        except Exception as e:
            logger.error(f"Error cleaning up stale databases: {e}")
