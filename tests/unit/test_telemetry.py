"""Unit tests for telemetry service"""

from unittest.mock import MagicMock, patch

from src.services.telemetry import TelemetryService


class TestTelemetryService:
    """Test telemetry service initialization and logging"""

    @patch("src.services.telemetry.config")
    def test_telemetry_service_disabled(self, mock_config):
        """Test that telemetry can be disabled"""
        mock_config.otel_enabled = False

        service = TelemetryService()

        assert service.enabled is False
        assert service.otel_logger is None

    @patch("src.services.telemetry.config")
    @patch("src.services.telemetry.set_logger_provider")
    def test_telemetry_service_enabled(self, mock_set_logger_provider, mock_config):
        """Test that telemetry initializes when enabled"""
        mock_config.otel_enabled = True
        mock_config.otel_endpoint = "http://localhost:4318"
        mock_config.otel_service_name = "test-service"
        mock_config.otel_service_version = "1.0.0"

        service = TelemetryService()

        assert service.enabled is True
        assert service.logger_provider is not None

    @patch("src.services.telemetry.config")
    def test_log_query_when_disabled(self, mock_config):
        """Test that logging does nothing when disabled"""
        mock_config.otel_enabled = False

        service = TelemetryService()
        # Should not raise any errors
        service.log_query(
            tool_name="query_docs",
            query="test query",
            parameters={"limit": 5},
            response={"results": []},
        )

    @patch("src.services.telemetry.config")
    @patch("src.services.telemetry.set_logger_provider")
    def test_log_query_with_response(self, mock_set_logger_provider, mock_config):
        """Test logging a successful query with response"""
        mock_config.otel_enabled = True
        mock_config.otel_endpoint = "http://localhost:4318"
        mock_config.otel_service_name = "test-service"
        mock_config.otel_service_version = "1.0.0"

        # Setup mock logger
        mock_otel_logger = MagicMock()

        service = TelemetryService()
        service.otel_logger = mock_otel_logger

        # Log a query
        service.log_query(
            tool_name="query_docs",
            query="test query",
            parameters={"limit": 5, "query_type": "semantic"},
            response={
                "results": [{"chunk": {"id": "123"}, "score": 0.95}],
                "query_info": {"query_time_ms": 42.5, "total_results": 1},
            },
        )

        # Verify log was emitted
        assert mock_otel_logger.emit.called
        call_args = mock_otel_logger.emit.call_args[0][0]

        # Verify log body contains query text
        assert "test query" in call_args.body
        assert "SUCCESS" in call_args.body

        # Verify attributes contain low-cardinality data only
        attrs = call_args.attributes
        assert attrs["mcp.tool.name"] == "query_docs"
        assert attrs["query.param.limit"] == 5
        assert attrs["query.param.query_type"] == "semantic"
        assert attrs["response.success"] is True
        assert attrs["response.result_count"] == 1
        assert attrs["response.top_score"] == 0.95

        # Verify high-cardinality query text is NOT in attributes
        assert "query.text" not in attrs
        assert "query.length" not in attrs

    @patch("src.services.telemetry.config")
    @patch("src.services.telemetry.set_logger_provider")
    def test_log_query_with_error(self, mock_set_logger_provider, mock_config):
        """Test logging a failed query with error"""
        mock_config.otel_enabled = True
        mock_config.otel_endpoint = "http://localhost:4318"
        mock_config.otel_service_name = "test-service"
        mock_config.otel_service_version = "1.0.0"

        # Setup mock logger
        mock_otel_logger = MagicMock()

        service = TelemetryService()
        service.otel_logger = mock_otel_logger

        # Log a query with error
        error = ValueError("Test error")
        service.log_query(
            tool_name="query_docs",
            query="test query",
            parameters={"limit": 5},
            response=None,
            error=error,
        )

        # Verify log was emitted
        assert mock_otel_logger.emit.called
        call_args = mock_otel_logger.emit.call_args[0][0]

        # Verify log body contains failure indicator
        assert "FAILED" in call_args.body
        assert "ValueError" in call_args.body

        # Verify error attributes
        attrs = call_args.attributes
        assert attrs["response.success"] is False
        assert attrs["error.type"] == "ValueError"
        assert "Test error" in attrs["error.message"]

    @patch("src.services.telemetry.config")
    @patch("src.services.telemetry.set_logger_provider")
    def test_log_query_truncates_long_query(self, mock_set_logger_provider, mock_config):
        """Test that very long queries are truncated in log body"""
        mock_config.otel_enabled = True
        mock_config.otel_endpoint = "http://localhost:4318"
        mock_config.otel_service_name = "test-service"
        mock_config.otel_service_version = "1.0.0"

        # Setup mock logger
        mock_otel_logger = MagicMock()

        service = TelemetryService()
        service.otel_logger = mock_otel_logger

        # Create a very long query
        long_query = "a" * 300

        service.log_query(
            tool_name="query_docs",
            query=long_query,
            parameters={"limit": 5},
            response={"results": []},
        )

        # Verify log was emitted and query was truncated
        assert mock_otel_logger.emit.called
        call_args = mock_otel_logger.emit.call_args[0][0]

        # Body should contain truncated query
        assert "..." in call_args.body
        assert len(call_args.body) < len(long_query)

    @patch("src.services.telemetry.config")
    @patch("src.services.telemetry.set_logger_provider")
    def test_get_chunk_logging(self, mock_set_logger_provider, mock_config):
        """Test logging for get_chunk tool"""
        mock_config.otel_enabled = True
        mock_config.otel_endpoint = "http://localhost:4318"
        mock_config.otel_service_name = "test-service"
        mock_config.otel_service_version = "1.0.0"

        # Setup mock logger
        mock_otel_logger = MagicMock()

        service = TelemetryService()
        service.otel_logger = mock_otel_logger

        # Log a get_chunk call
        service.log_query(
            tool_name="get_chunk",
            query=None,
            parameters={"chunk_id": "test-uuid-123"},
            response={"id": "test-uuid-123", "content": "Test content"},
        )

        # Verify log was emitted
        assert mock_otel_logger.emit.called
        call_args = mock_otel_logger.emit.call_args[0][0]

        # Verify log body
        assert "get_chunk" in call_args.body
        assert "test-uuid-123" in call_args.body

        # Verify attributes
        attrs = call_args.attributes
        assert attrs["mcp.tool.name"] == "get_chunk"
        assert attrs["response.chunk_retrieved"] is True
        assert attrs["response.content_length"] == len("Test content")
