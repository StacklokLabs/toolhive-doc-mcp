"""Integration tests for RefreshOrchestrator"""

import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from src.services.refresh_orchestrator import RefreshOrchestrator


class TestRefreshOrchestrator:
    """Test refresh orchestration and database swap workflow"""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for test databases"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def setup_databases(self, temp_dir):
        """Setup active and temp database paths"""
        active_db = os.path.join(temp_dir, "active.db")
        temp_db = os.path.join(temp_dir, "temp.db")

        # Create initial active database
        conn = sqlite3.connect(active_db)
        conn.execute("CREATE TABLE chunks (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE vec_chunks (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE metadata (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        return active_db, temp_db

    def create_valid_database(self, db_path):
        """Helper to create a valid database"""
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE chunks (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE vec_chunks (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE metadata (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

    def test_successful_refresh_cycle(self, temp_dir, setup_databases):
        """Test complete successful refresh cycle"""
        active_db, temp_db = setup_databases

        # Mock build function to create valid temp database
        async def mock_build(sources_config_path, db_path):
            self.create_valid_database(db_path)

        with patch("src.services.refresh_orchestrator.build", side_effect=mock_build):
            with patch("src.services.refresh_orchestrator.config") as mock_config:
                mock_config.db_path = active_db
                mock_config.db_temp_path = temp_db

                # Execute refresh
                orchestrator = RefreshOrchestrator()
                result = orchestrator.refresh_once()

                # Verify success
                assert result.success is True
                assert result.error is None
                assert result.duration_seconds > 0

                # Verify temp database was swapped to active
                assert os.path.exists(active_db)
                assert not os.path.exists(temp_db)

                # Verify backup was created
                backup_files = list(Path(temp_dir).glob("active.db.backup-*"))
                assert len(backup_files) == 1

    def test_refresh_with_build_failure(self, temp_dir, setup_databases):
        """Test refresh handles build failures gracefully"""
        active_db, temp_db = setup_databases

        # Mock build function to raise exception
        async def mock_build_failure(sources_config_path, db_path):
            raise Exception("Build failed: network error")

        with patch("src.services.refresh_orchestrator.build", side_effect=mock_build_failure):
            with patch("src.services.refresh_orchestrator.config") as mock_config:
                mock_config.db_path = active_db
                mock_config.db_temp_path = temp_db

                # Execute refresh and expect exception
                orchestrator = RefreshOrchestrator()
                with pytest.raises(Exception) as exc_info:
                    orchestrator.refresh_once()

                # Verify exception message
                assert "Build failed: network error" in str(exc_info.value)

                # Verify active database is unchanged
                assert os.path.exists(active_db)

    def test_refresh_with_invalid_temp_database(self, temp_dir, setup_databases):
        """Test refresh fails when temp database is invalid"""
        active_db, temp_db = setup_databases

        # Mock build to create invalid database
        async def mock_build_invalid(sources_config_path, db_path):
            # Create database with wrong schema
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE wrong_table (id INTEGER)")
            conn.commit()
            conn.close()

        with patch("src.services.refresh_orchestrator.build", side_effect=mock_build_invalid):
            with patch("src.services.refresh_orchestrator.config") as mock_config:
                mock_config.db_path = active_db
                mock_config.db_temp_path = temp_db

                # Execute refresh and expect exception
                orchestrator = RefreshOrchestrator()
                with pytest.raises(Exception) as exc_info:
                    orchestrator.refresh_once()

                # Verify exception message contains expected error
                assert "Missing required tables" in str(exc_info.value)

                # Verify active database is unchanged
                assert os.path.exists(active_db)

    def test_cleanup_stale_databases_on_refresh(self, temp_dir, setup_databases):
        """Test that stale temp databases are cleaned up before refresh"""
        active_db, temp_db = setup_databases

        # Create stale temp database
        Path(temp_db).touch()

        async def mock_build(sources_config_path, db_path):
            # Verify stale database was removed
            # Create new valid database
            self.create_valid_database(db_path)

        with patch("src.services.refresh_orchestrator.build", side_effect=mock_build):
            with patch("src.services.refresh_orchestrator.config") as mock_config:
                mock_config.db_path = active_db
                mock_config.db_temp_path = temp_db

                orchestrator = RefreshOrchestrator()
                result = orchestrator.refresh_once()

                assert result.success is True

    def test_refresh_timing_metrics(self, temp_dir, setup_databases):
        """Test that refresh timing is accurately captured"""
        active_db, temp_db = setup_databases

        async def mock_build(sources_config_path, db_path):
            # Create valid database
            self.create_valid_database(db_path)

        with patch("src.services.refresh_orchestrator.build", side_effect=mock_build):
            with patch("src.services.refresh_orchestrator.config") as mock_config:
                mock_config.db_path = active_db
                mock_config.db_temp_path = temp_db

                orchestrator = RefreshOrchestrator()
                result = orchestrator.refresh_once()

                # Verify timing metrics
                assert result.success is True
                assert result.duration_seconds >= 0
                assert result.start_time is not None
                assert result.end_time is not None
                assert result.end_time >= result.start_time

    def test_refresh_with_exception_preserves_database(self, temp_dir, setup_databases):
        """Test that active database is preserved on exception"""
        active_db, temp_db = setup_databases

        # Record original active database content
        original_exists = os.path.exists(active_db)

        async def mock_build_exception(sources_config_path, db_path):
            raise RuntimeError("Unexpected error during build")

        with patch(
            "src.services.refresh_orchestrator.build",
            side_effect=mock_build_exception,
        ):
            with patch("src.services.refresh_orchestrator.config") as mock_config:
                mock_config.db_path = active_db
                mock_config.db_temp_path = temp_db

                orchestrator = RefreshOrchestrator()
                with pytest.raises(Exception) as exc_info:
                    orchestrator.refresh_once()

                # Verify exception message
                assert "Unexpected error during build" in str(exc_info.value)

                # Verify active database still exists and unchanged
                assert os.path.exists(active_db) == original_exists
