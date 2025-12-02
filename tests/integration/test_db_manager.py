"""Integration tests for DatabaseManager"""

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.services.db_manager import DatabaseManager
from src.services.vector_store import VectorStore


class TestDatabaseManager:
    """Test database management and atomic swap operations"""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for test databases"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    async def valid_database(self, temp_dir):
        """Create a valid test database with required tables"""
        db_path = os.path.join(temp_dir, "test.db")
        vector_store = VectorStore(db_path=db_path)
        await vector_store.initialize()
        vector_store.close()
        return db_path

    @pytest.mark.asyncio
    async def test_database_integrity_check_valid_database(self, valid_database):
        """Test integrity check passes for valid database"""
        manager = DatabaseManager()

        # Should not raise exception for valid database
        result = manager._check_db_integrity(valid_database)

        assert result is True

    @pytest.mark.asyncio
    async def test_database_integrity_check_missing_database(self, temp_dir):
        """Test integrity check fails for non-existent database"""
        manager = DatabaseManager()
        missing_db = os.path.join(temp_dir, "missing.db")

        # Should raise FileNotFoundError
        with pytest.raises(FileNotFoundError, match="does not exist"):
            manager._check_db_integrity(missing_db)

    @pytest.mark.asyncio
    async def test_database_integrity_check_missing_tables(self, temp_dir):
        """Test integrity check fails for database with missing tables"""
        manager = DatabaseManager()
        db_path = os.path.join(temp_dir, "incomplete.db")

        # Create database with incomplete schema
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE chunks (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        # Should raise exception for missing tables
        with pytest.raises(Exception, match="Missing required tables"):
            manager._check_db_integrity(db_path)

    @pytest.mark.asyncio
    async def test_successful_database_swap(self, temp_dir, valid_database):
        """Test successful database swap with backup creation"""
        manager = DatabaseManager()

        # Create active database
        active_path = os.path.join(temp_dir, "active.db")
        vector_store = VectorStore(db_path=active_path)
        await vector_store.initialize()
        vector_store.close()

        # Perform swap
        manager.swap_databases(temp_path=valid_database, active_path=active_path)

        # Verify swap succeeded
        assert os.path.exists(active_path)
        assert not os.path.exists(valid_database)  # Temp should be moved

        # Verify backup was created
        backup_files = list(Path(temp_dir).glob("active.db.backup-*"))
        assert len(backup_files) == 1

    @pytest.mark.asyncio
    async def test_database_swap_with_invalid_temp(self, temp_dir):
        """Test swap fails when temp database is invalid"""
        manager = DatabaseManager()

        active_path = os.path.join(temp_dir, "active.db")
        invalid_temp = os.path.join(temp_dir, "invalid.db")

        # Create invalid temp database (missing tables)
        conn = sqlite3.connect(invalid_temp)
        conn.execute("CREATE TABLE wrong_table (id INTEGER)")
        conn.commit()
        conn.close()

        # Swap should raise exception
        with pytest.raises(Exception, match="Missing required tables"):
            manager.swap_databases(temp_path=invalid_temp, active_path=active_path)

    @pytest.mark.asyncio
    async def test_database_swap_first_time_no_active(self, temp_dir, valid_database):
        """Test swap succeeds when no active database exists (first run)"""
        manager = DatabaseManager()

        active_path = os.path.join(temp_dir, "active.db")

        # Perform swap (no active database exists)
        manager.swap_databases(temp_path=valid_database, active_path=active_path)

        # Verify swap succeeded
        assert os.path.exists(active_path)
        assert not os.path.exists(valid_database)

        # Verify no backup was created (nothing to back up)
        backup_files = list(Path(temp_dir).glob("active.db.backup-*"))
        assert len(backup_files) == 0

    @pytest.mark.asyncio
    async def test_cleanup_old_backups(self, temp_dir):
        """Test cleanup of old backup files"""
        manager = DatabaseManager()

        active_path = os.path.join(temp_dir, "active.db")

        # Create multiple backup files
        for i in range(5):
            backup_file = Path(temp_dir) / f"active.db.backup-2024120{i}-120000"
            backup_file.touch()

        # Cleanup keeping only 2 most recent
        manager._cleanup_old_backups(active_path, keep_count=2)

        # Verify only 2 backups remain
        backup_files = list(Path(temp_dir).glob("active.db.backup-*"))
        assert len(backup_files) == 2

    @pytest.mark.asyncio
    async def test_cleanup_stale_databases(self, temp_dir):
        """Test cleanup of stale temporary databases"""
        # Create manager with custom config
        manager = DatabaseManager()
        stale_temp = os.path.join(temp_dir, "docs.db.new")

        # Override config for test
        original_temp_path = manager.config.db_temp_path
        manager.config.db_temp_path = stale_temp

        # Create stale temp database
        Path(stale_temp).touch()

        # Cleanup should remove it
        manager.cleanup_stale_databases()

        assert not os.path.exists(stale_temp)

        # Restore original config
        manager.config.db_temp_path = original_temp_path
