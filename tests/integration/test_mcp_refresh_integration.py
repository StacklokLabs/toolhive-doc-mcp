"""Integration tests for MCP server refresh orchestrator integration"""

from unittest.mock import MagicMock, patch

import pytest

from src.mcp_server import _shutdown_sync, _startup_sync


class TestMCPRefreshIntegration:
    """Test MCP server integration with refresh orchestrator"""

    @pytest.fixture
    def mock_sources_config(self):
        """Mock sources configuration with refresh enabled"""
        config = MagicMock()
        config.refresh.enabled = True
        config.refresh.interval_hours = 24
        config.refresh.max_concurrent_jobs = 1
        return config

    @pytest.fixture
    def mock_sources_config_disabled(self):
        """Mock sources configuration with refresh disabled"""
        config = MagicMock()
        config.refresh.enabled = False
        return config

    def test_startup_initializes_refresh_when_enabled(self, mock_sources_config):
        """Test that refresh orchestrator is initialized on server startup"""
        with patch(
            "src.mcp_server.load_sources_config", return_value=mock_sources_config
        ):
            with patch("src.mcp_server.BackgroundScheduler") as mock_scheduler_class:
                with patch(
                    "src.mcp_server.RefreshOrchestrator"
                ) as mock_orchestrator_class:
                    mock_scheduler = MagicMock()
                    mock_scheduler_class.return_value = mock_scheduler

                    mock_orchestrator = MagicMock()
                    mock_orchestrator_class.return_value = mock_orchestrator

                    # Execute startup
                    _startup_sync()

                    # Verify orchestrator was created and configured
                    mock_orchestrator_class.assert_called_once()
                    mock_orchestrator.configure_scheduler_sync.assert_called_once_with(
                        scheduler=mock_scheduler,
                        interval_hours=24,
                        max_concurrent_jobs=1,
                    )

                    # Verify scheduler was started
                    mock_scheduler.start.assert_called_once()

    def test_startup_skips_refresh_when_disabled(
        self, mock_sources_config_disabled
    ):
        """Test that refresh is not initialized when disabled in config"""
        with patch(
            "src.mcp_server.load_sources_config",
            return_value=mock_sources_config_disabled,
        ):
            with patch("src.mcp_server.BackgroundScheduler") as mock_scheduler_class:
                with patch(
                    "src.mcp_server.RefreshOrchestrator"
                ) as mock_orchestrator_class:
                    # Execute startup
                    _startup_sync()

                    # Verify orchestrator was NOT created
                    mock_orchestrator_class.assert_not_called()
                    mock_scheduler_class.assert_not_called()

    def test_startup_handles_initialization_errors_gracefully(self):
        """Test that server startup continues even if refresh init fails"""
        with patch(
            "src.mcp_server.load_sources_config",
            side_effect=Exception("Config load failed"),
        ):
            # Should not raise exception
            try:
                _startup_sync()
            except Exception:
                pytest.fail("Startup should not raise exception on refresh init failure")

    def test_shutdown_stops_refresh_orchestrator(self):
        """Test that refresh orchestrator is properly stopped on shutdown"""
        mock_orchestrator_instance = MagicMock()
        mock_scheduler_instance = MagicMock()

        # Simulate globals being set
        import src.mcp_server

        src.mcp_server._refresh_orchestrator = mock_orchestrator_instance
        src.mcp_server._scheduler = mock_scheduler_instance

        # Execute shutdown
        _shutdown_sync()

        # Verify orchestrator stop was called
        mock_orchestrator_instance.stop_scheduler_sync.assert_called_once()

        # Verify scheduler shutdown was called
        mock_scheduler_instance.shutdown.assert_called_once_with(wait=False)

        # Reset globals
        src.mcp_server._refresh_orchestrator = None
        src.mcp_server._scheduler = None

    def test_shutdown_handles_stop_errors_gracefully(self):
        """Test that shutdown continues even if refresh stop fails"""
        mock_orchestrator = MagicMock()
        mock_orchestrator.stop_scheduler_sync.side_effect = Exception("Stop failed")

        mock_scheduler = MagicMock()

        import src.mcp_server

        src.mcp_server._refresh_orchestrator = mock_orchestrator
        src.mcp_server._scheduler = mock_scheduler

        # Should not raise exception
        try:
            _shutdown_sync()
        except Exception:
            pytest.fail("Shutdown should not raise exception on orchestrator stop failure")

        # Reset globals
        src.mcp_server._refresh_orchestrator = None
        src.mcp_server._scheduler = None

    def test_shutdown_handles_scheduler_errors_gracefully(self):
        """Test that shutdown continues even if scheduler shutdown fails"""
        mock_orchestrator = MagicMock()
        mock_scheduler = MagicMock()
        mock_scheduler.shutdown.side_effect = Exception("Scheduler shutdown failed")

        import src.mcp_server

        src.mcp_server._refresh_orchestrator = mock_orchestrator
        src.mcp_server._scheduler = mock_scheduler

        # Should not raise exception
        try:
            _shutdown_sync()
        except Exception:
            pytest.fail("Shutdown should not raise exception on scheduler shutdown failure")

        # Reset globals
        src.mcp_server._refresh_orchestrator = None
        src.mcp_server._scheduler = None

    def test_shutdown_with_no_orchestrator(self):
        """Test shutdown works when no orchestrator was initialized"""
        import src.mcp_server

        # Ensure globals are None
        src.mcp_server._refresh_orchestrator = None
        src.mcp_server._scheduler = None

        # Should not raise exception
        try:
            _shutdown_sync()
        except Exception:
            pytest.fail("Shutdown should handle None orchestrator gracefully")
