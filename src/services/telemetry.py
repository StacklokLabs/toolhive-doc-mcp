"""OpenTelemetry logging service for query and response telemetry"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource

from src.config import config

logger = logging.getLogger(__name__)


class TelemetryService:
    """Handle OpenTelemetry logging for queries and responses"""

    def __init__(self):
        self.enabled = config.otel_enabled
        self.logger_provider = None
        self.otel_logger = None

        if self.enabled:
            try:
                self._initialize_otel()
            except Exception as e:
                logger.warning(f"Failed to initialize OpenTelemetry: {e}. Telemetry disabled.")
                self.enabled = False

    def _initialize_otel(self) -> None:
        """Initialize OpenTelemetry with OTLP log exporter"""
        # Create resource with service information
        resource = Resource(
            attributes={
                SERVICE_NAME: config.otel_service_name,
                SERVICE_VERSION: config.otel_service_version,
            }
        )

        # Create logger provider
        self.logger_provider = LoggerProvider(resource=resource)

        # Create OTLP exporter (HTTP/protobuf)
        # The endpoint should point to the logs endpoint
        endpoint = config.otel_endpoint
        if not endpoint.endswith("/v1/logs"):
            endpoint = f"{endpoint.rstrip('/')}/v1/logs"

        otlp_exporter = OTLPLogExporter(endpoint=endpoint)

        # Add batch log record processor
        self.logger_provider.add_log_record_processor(BatchLogRecordProcessor(otlp_exporter))

        # Set the global logger provider
        set_logger_provider(self.logger_provider)

        # Get logger
        self.otel_logger = self.logger_provider.get_logger(__name__)

        logger.info(f"OpenTelemetry logging initialized with endpoint: {endpoint}")

    def log_query(  # noqa: C901
        self,
        tool_name: str,
        query: str | None,
        parameters: dict[str, Any],
        response: dict[str, Any] | None = None,
        error: Exception | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Log a query and its response to OpenTelemetry

        Args:
            tool_name: Name of the MCP tool being called
            query: The query text (for query_docs) or None
            parameters: All parameters passed to the tool
            response: The response data (if successful)
            error: The error (if failed)
            metadata: Additional metadata (query time, result count, etc.)
        """
        if not self.enabled or not self.otel_logger:
            return

        try:
            # Build structured attributes (LOW CARDINALITY ONLY)
            attributes: dict[str, str | int | float | bool] = {
                "mcp.tool.name": tool_name,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            # Add low-cardinality parameters only
            if "limit" in parameters and parameters["limit"] is not None:
                attributes["query.param.limit"] = int(parameters["limit"])

            if "query_type" in parameters and parameters["query_type"] is not None:
                attributes["query.param.query_type"] = str(parameters["query_type"])

            if "min_score" in parameters and parameters["min_score"] is not None:
                attributes["query.param.min_score"] = float(parameters["min_score"])

            # Add response metrics (low cardinality)
            success = error is None
            attributes["response.success"] = success

            if response:
                # Add response size
                response_json = json.dumps(response, default=str)
                attributes["response.size_bytes"] = len(response_json)

                # Add specific response metrics based on tool
                if tool_name == "query_docs" and "results" in response:
                    results = response.get("results", [])
                    attributes["response.result_count"] = len(results)

                    # Add top result score if available
                    if results and len(results) > 0:
                        top_score = results[0].get("score")
                        if top_score is not None:
                            attributes["response.top_score"] = float(top_score)

                    # Add query info if available
                    query_info = response.get("query_info", {})
                    if "query_time_ms" in query_info:
                        attributes["response.query_time_ms"] = float(query_info["query_time_ms"])
                    if "total_results" in query_info:
                        attributes["response.total_results"] = int(query_info["total_results"])

                elif tool_name == "get_chunk" and "id" in response:
                    attributes["response.chunk_retrieved"] = True
                    if "content" in response:
                        attributes["response.content_length"] = len(response["content"])

            # Add error information (error types are low cardinality)
            if error:
                attributes["error.type"] = type(error).__name__
                # Error message can have some cardinality, but typically bounded
                # Truncate if very long
                error_message = str(error)
                if len(error_message) > 500:
                    error_message = error_message[:500] + "..."
                attributes["error.message"] = error_message

            # Build log message (HIGH CARDINALITY DATA GOES HERE)
            log_body_parts = [f"[{tool_name}]"]

            if success:
                log_body_parts.append("SUCCESS")
            else:
                log_body_parts.append("FAILED")

            # Include the actual query text in the log body (not as attribute)
            if query:
                # Truncate very long queries for log body
                truncated_query = query if len(query) <= 200 else query[:200] + "..."
                log_body_parts.append(f'query="{truncated_query}"')

            # Add chunk_id if present (bounded UUID)
            if "chunk_id" in parameters:
                log_body_parts.append(f'chunk_id={parameters["chunk_id"]}')

            # Add summary stats
            if response and tool_name == "query_docs":
                result_count = len(response.get("results", []))
                query_info = response.get("query_info", {})
                query_time = query_info.get("query_time_ms", 0)
                log_body_parts.append(f"results={result_count} time={query_time:.1f}ms")

            if error:
                log_body_parts.append(f"error={type(error).__name__}")

            log_body = " ".join(log_body_parts)

            # Emit log record
            # Severity: INFO for success, ERROR for failures
            severity = logging.ERROR if error else logging.INFO

            self.otel_logger.emit(
                self._create_log_record(
                    body=log_body,
                    severity_number=self._severity_to_number(severity),
                    attributes=attributes,
                )
            )

        except Exception as e:
            # Don't let telemetry errors break the application
            logger.warning(f"Failed to log telemetry: {e}")

    def _create_log_record(
        self, body: str, severity_number: int, attributes: dict[str, str | int | float | bool]
    ) -> Any:
        """Create a log record with the given parameters"""
        from opentelemetry.sdk._logs import LogRecord

        # Convert severity_number to SeverityNumber enum
        from opentelemetry._logs import SeverityNumber

        return LogRecord(
            timestamp=int(datetime.now(timezone.utc).timestamp() * 1e9),  # nanoseconds
            severity_number=SeverityNumber(severity_number),
            body=body,
            attributes=attributes,
        )

    def _severity_to_number(self, level: int) -> int:
        """Convert Python logging level to OpenTelemetry severity number"""
        # OpenTelemetry severity numbers: https://opentelemetry.io/docs/specs/otel/logs/data-model/#severity-fields
        if level >= logging.CRITICAL:
            return 21  # FATAL
        elif level >= logging.ERROR:
            return 17  # ERROR
        elif level >= logging.WARNING:
            return 13  # WARN
        elif level >= logging.INFO:
            return 9  # INFO
        else:
            return 5  # DEBUG


# Global telemetry service instance
_telemetry_service: TelemetryService | None = None


def get_telemetry_service() -> TelemetryService:
    """Get or create the global telemetry service instance"""
    global _telemetry_service
    if _telemetry_service is None:
        _telemetry_service = TelemetryService()
    return _telemetry_service
