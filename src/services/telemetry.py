"""OpenTelemetry logging and tracing service for query and response telemetry"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

from opentelemetry import trace
from opentelemetry._logs import SeverityNumber, set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from src.config import config

logger = logging.getLogger(__name__)


class TelemetryService:
    """Handle OpenTelemetry logging and tracing for queries and responses"""

    def __init__(self):
        self.logging_enabled = config.otel_logging_enabled
        self.tracing_enabled = config.otel_tracing_enabled
        self.logger_provider = None
        self.tracer_provider = None
        self.otel_logger = None

        # Initialize logging if enabled
        if self.logging_enabled:
            try:
                self._initialize_logging()
            except Exception as e:
                logger.warning(
                    f"Failed to initialize OTel logging: {e}. Logging disabled."
                )
                self.logging_enabled = False

        # Initialize tracing if enabled
        if self.tracing_enabled:
            try:
                self._initialize_tracing()
            except Exception as e:
                logger.warning(
                    f"Failed to initialize OTel tracing: {e}. Tracing disabled."
                )
                self.tracing_enabled = False

    def _initialize_logging(self) -> None:
        """Initialize OpenTelemetry logging with OTLP log exporter"""
        # Create resource with service information
        resource = Resource(
            attributes={
                SERVICE_NAME: config.otel_service_name,
                SERVICE_VERSION: config.otel_service_version,
            }
        )

        # Initialize logging
        self.logger_provider = LoggerProvider(resource=resource)

        # Create OTLP exporter (HTTP/protobuf)
        # The endpoint should point to the logs endpoint
        log_endpoint = config.otel_endpoint
        if not log_endpoint.endswith("/v1/logs"):
            log_endpoint = f"{log_endpoint.rstrip('/')}/v1/logs"

        log_exporter = OTLPLogExporter(endpoint=log_endpoint)

        # Add batch log record processor
        self.logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(log_exporter)
        )

        # Set the global logger provider
        set_logger_provider(self.logger_provider)

        # Get logger
        self.otel_logger = self.logger_provider.get_logger(__name__)

        logger.info(
            f"OpenTelemetry logging initialized with endpoint: {log_endpoint}"
        )

    def _initialize_tracing(self) -> None:
        """Initialize OpenTelemetry tracing with OTLP trace exporter"""
        # Create resource with service information
        resource = Resource(
            attributes={
                SERVICE_NAME: config.otel_service_name,
                SERVICE_VERSION: config.otel_service_version,
            }
        )

        # Initialize tracing
        self.tracer_provider = TracerProvider(resource=resource)

        # Create trace exporter (HTTP/protobuf)
        # The endpoint should point to the traces endpoint
        trace_endpoint = config.otel_endpoint
        if not trace_endpoint.endswith("/v1/traces"):
            # Append /v1/traces if not present
            trace_endpoint = f"{trace_endpoint.rstrip('/')}/v1/traces"

        trace_exporter = OTLPSpanExporter(endpoint=trace_endpoint)

        # Add batch span processor
        self.tracer_provider.add_span_processor(BatchSpanProcessor(trace_exporter))

        # Set the global tracer provider
        trace.set_tracer_provider(self.tracer_provider)

        # httpx instrumentation is initialized separately via
        # _ensure_instrumentation_initialized() to ensure it happens early,
        # before HTTP clients are created

        logger.info(
            f"OpenTelemetry tracing initialized with endpoint: {trace_endpoint}"
        )

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
        if not self.logging_enabled or not self.otel_logger:
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
                        attributes["response.query_time_ms"] = float(
                            query_info["query_time_ms"]
                        )
                    if "total_results" in query_info:
                        attributes["response.total_results"] = int(query_info["total_results"])

                elif tool_name == "get_chunk" and "id" in response:
                    attributes["response.chunk_retrieved"] = True
                    if "content" in response:
                        attributes["response.content_length"] = len(response["content"])

                        # Store full chunk for analytics (if enabled)
                        if config.otel_log_full_results:
                            attributes["response.chunk_json"] = json.dumps(response, default=str)

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

                # Store full query text for analytics (if enabled)
                if config.otel_log_full_results:
                    attributes["query.full_text"] = query

            # Add chunk_id if present (bounded UUID)
            if "chunk_id" in parameters:
                log_body_parts.append(f"chunk_id={parameters['chunk_id']}")

            # Add summary stats
            if response and tool_name == "query_docs":
                result_count = len(response.get("results", []))
                query_info = response.get("query_info", {})
                query_time = query_info.get("query_time_ms", 0)
                log_body_parts.append(f"results={result_count} time={query_time:.1f}ms")

                # Add full results for analytics (if enabled)
                if config.otel_log_full_results:
                    results = response.get("results", [])
                    # Store full results as JSON in attributes for analytics
                    attributes["response.results_json"] = json.dumps(results, default=str)

            if error:
                log_body_parts.append(f"error={type(error).__name__}")

            log_body = " ".join(log_body_parts)

            # Emit log record
            # Severity: INFO for success, ERROR for failures
            severity = logging.ERROR if error else logging.INFO

            self.otel_logger.emit(
                body=log_body,
                severity_number=SeverityNumber(self._severity_to_number(severity)),
                attributes=attributes,
                timestamp=int(datetime.now(timezone.utc).timestamp() * 1e9),
            )

        except Exception as e:
            # Don't let telemetry errors break the application
            logger.warning(f"Failed to log telemetry: {e}")

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
# Track if instrumentation has been initialized
_instrumentation_initialized = False


def _ensure_instrumentation_initialized() -> None:
    """Ensure httpx instrumentation is initialized early"""
    global _instrumentation_initialized
    if not _instrumentation_initialized and config.otel_tracing_enabled:
        try:
            # Initialize httpx instrumentation early so all HTTP clients are traced
            httpx_instrumentor = HTTPXClientInstrumentor()
            httpx_instrumentor.instrument()
            _instrumentation_initialized = True
            logger.info("HTTP request tracing instrumentation initialized")
        except Exception as e:
            logger.warning(
                f"Failed to initialize HTTP tracing instrumentation: {e}"
            )


def get_telemetry_service() -> TelemetryService:
    """Get or create the global telemetry service instance"""
    global _telemetry_service
    # Ensure instrumentation is initialized before creating service
    _ensure_instrumentation_initialized()
    if _telemetry_service is None:
        _telemetry_service = TelemetryService()
    return _telemetry_service
