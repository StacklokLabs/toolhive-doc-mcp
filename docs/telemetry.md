# OpenTelemetry Logging Implementation

This document describes the OpenTelemetry logging implementation in the toolhive-doc-mcp service.

## Overview

The service uses **OpenTelemetry Logs** (not traces or metrics) to capture query and response data for all MCP tool calls. This enables monitoring, analytics, and debugging while avoiding cardinality issues.

## Why Logs (Not Traces)?

### Cardinality Considerations

Query text is **high-cardinality data** - each query can be unique and unbounded. Storing this in trace spans or metrics would cause:

- **Cardinality explosion** in time-series databases (Prometheus, etc.)
- **High storage costs** in trace backends (Jaeger, Tempo, etc.)
- **Performance degradation** due to index bloat
- **Query performance issues** in observability systems

### Log-Based Architecture

We use **OpenTelemetry Logs** which are designed for high-cardinality data:

- **High-cardinality data** (query text, chunk IDs) → Stored in **log body/message**
- **Low-cardinality data** (query_type, success/failure, error types) → Stored in **structured attributes**

This allows:
- Full-text search on query content in log aggregation systems (Loki, Elasticsearch, etc.)
- Efficient filtering and aggregation on structured attributes
- No cardinality explosion in databases

## Architecture

### Components

1. **TelemetryService** (`src/services/telemetry.py`)
   - Singleton service that manages OpenTelemetry logging initialization
   - Provides `log_query()` method for logging queries and responses
   - Handles errors gracefully (telemetry failures don't break the service)

2. **Configuration** (`src/config.py`)
   - `OTEL_ENABLED`: Enable/disable telemetry (default: `true`)
   - `OTEL_ENDPOINT`: Collector endpoint (default: `http://otel-collector.otel.svc.cluster.local:4318`)
   - `OTEL_SERVICE_NAME`: Service name (default: `toolhive-doc-mcp`)
   - `OTEL_SERVICE_VERSION`: Service version (default: `1.0.0`)

3. **Integration** (`src/mcp_server.py`)
   - Both `query_docs` and `get_chunk` tools log telemetry
   - Logging happens in `finally` blocks to ensure it runs even on errors
   - Captures both successful responses and errors

## Data Structure

### Log Record Structure

Each query generates an OpenTelemetry log record with:

**Log Body** (high-cardinality, full-text searchable):
- Tool name and success/failure indicator
- Full query text (truncated if > 200 chars)
- Chunk IDs
- Summary statistics

**Structured Attributes** (low-cardinality, filterable):
- Tool and timestamp metadata
- Query parameters (limit, query_type, min_score)
- Response metrics (result count, scores, timing)
- Error information (error type and message)

### Example Log Records

#### Successful Query

```
Log Body:
[query_docs] SUCCESS query="How do I use toolhive?" results=5 time=42.5ms

Attributes:
- mcp.tool.name: "query_docs"
- timestamp: "2025-11-25T10:30:45.123456Z"
- query.param.limit: 5
- query.param.query_type: "semantic"
- response.success: true
- response.size_bytes: 2847
- response.result_count: 5
- response.top_score: 0.8745
- response.query_time_ms: 42.5
- response.total_results: 5
```

#### Failed Query

```
Log Body:
[query_docs] FAILED query="test query" error=ValueError

Attributes:
- mcp.tool.name: "query_docs"
- timestamp: "2025-11-25T10:31:40.000000Z"
- query.param.limit: 5
- query.param.query_type: "invalid_type"
- response.success: false
- error.type: "ValueError"
- error.message: "'invalid_type' is not a valid QueryType"
```

#### get_chunk Call

```
Log Body:
[get_chunk] SUCCESS chunk_id=a1b2c3d4-5678-90ab-cdef-1234567890ab

Attributes:
- mcp.tool.name: "get_chunk"
- timestamp: "2025-11-25T10:32:15.000000Z"
- response.success: true
- response.chunk_retrieved: true
- response.content_length: 1245
```

## Captured Data Details

### Low-Cardinality Attributes (Always Indexed)

These are stored as structured attributes for efficient filtering:

- `mcp.tool.name`: Tool being called (bounded: query_docs, get_chunk)
- `timestamp`: ISO 8601 timestamp
- `query.param.limit`: Result limit (bounded: 1-50)
- `query.param.query_type`: Search type (bounded: semantic, keyword, hybrid)
- `query.param.min_score`: Minimum score threshold (numeric)
- `response.success`: Boolean success/failure
- `response.size_bytes`: Response size in bytes
- `response.result_count`: Number of results
- `response.top_score`: Score of top result (numeric)
- `response.query_time_ms`: Query execution time
- `response.total_results`: Total results count
- `response.chunk_retrieved`: Boolean for get_chunk
- `response.content_length`: Length of retrieved content
- `error.type`: Exception class name (bounded set of error types)
- `error.message`: Error message (truncated to 500 chars)

### High-Cardinality Data (In Log Body)

These are stored in the log body for full-text search:

- **Query text**: The actual search query (unbounded, can be anything)
- **Chunk IDs**: UUID identifiers for specific chunks
- **Summary statistics**: Human-readable summaries

## Protocol

- **Export Protocol**: OTLP/HTTP with Protocol Buffers
- **Endpoint**: `/v1/logs` is automatically appended to the base endpoint
- **Batching**: Log records are batched using `BatchLogRecordProcessor` for efficiency
- **Resource Attributes**: Includes service name and version
- **Severity Levels**: INFO for success, ERROR for failures

## Configuration Examples

### Default Configuration (Kubernetes)

```bash
# Uses default collector endpoint for Kubernetes
OTEL_ENABLED=true
OTEL_ENDPOINT=http://otel-collector.otel.svc.cluster.local:4318
```

### Local Development

```bash
# Point to local collector (e.g., running in Docker)
OTEL_ENABLED=true
OTEL_ENDPOINT=http://localhost:4318
```

### Disable Telemetry

```bash
# Completely disable telemetry
OTEL_ENABLED=false
```

### Custom Service Identification

```bash
OTEL_SERVICE_NAME=my-custom-doc-search
OTEL_SERVICE_VERSION=2.0.0
```

## Testing

Comprehensive unit tests are provided in `tests/unit/test_telemetry.py`:

- Test telemetry initialization (enabled/disabled)
- Test logging with successful responses
- Test logging with errors
- Test query truncation for long queries
- Test get_chunk logging

Run tests:
```bash
uv run pytest tests/unit/test_telemetry.py -v
```

## Error Handling

The telemetry implementation is designed to be non-intrusive:

1. **Initialization Errors**: If OpenTelemetry fails to initialize, telemetry is automatically disabled and a warning is logged
2. **Logging Errors**: Errors during telemetry logging are caught and logged as warnings
3. **Service Continuity**: Telemetry failures never affect the main service functionality

## Dependencies

Added OpenTelemetry packages:
- `opentelemetry-api>=1.20.0`
- `opentelemetry-sdk>=1.20.0`
- `opentelemetry-exporter-otlp-proto-http>=1.20.0`
- `opentelemetry-exporter-otlp-proto-grpc>=1.20.0`

## Integration with Log Aggregation Systems

The telemetry data should be consumed by log aggregation systems, NOT metrics/trace backends:

### Recommended Backends

1. **Grafana Loki**: Time-series log aggregation
   - Efficient label-based indexing
   - Full-text search on log bodies
   - Low storage costs for high-cardinality data

2. **Elasticsearch**: Full-text search and analytics
   - Powerful query capabilities
   - Rich visualizations via Kibana
   - Text analysis and aggregations

3. **Splunk**: Enterprise log management
   - Advanced search and analytics
   - Real-time monitoring and alerting

4. **CloudWatch Logs / Stackdriver**: Cloud-native logging
   - Integration with cloud services
   - Scalable log ingestion

### Example Collector Configuration

```yaml
receivers:
  otlp:
    protocols:
      http:
        endpoint: 0.0.0.0:4318

processors:
  batch:
    timeout: 10s
    send_batch_size: 1024

exporters:
  loki:
    endpoint: http://loki:3100/loki/api/v1/push
    labels:
      resource:
        service.name: "service_name"
      attributes:
        mcp.tool.name: "tool_name"
        response.success: "success"
  
  elasticsearch:
    endpoints: [http://elasticsearch:9200]
    logs_index: otel-logs

service:
  pipelines:
    logs:
      receivers: [otlp]
      processors: [batch]
      exporters: [loki, elasticsearch]
```

## Querying Telemetry Data

### Loki Query Examples (LogQL)

```logql
# All queries in the last hour
{service_name="toolhive-doc-mcp"} | json

# Failed queries only
{service_name="toolhive-doc-mcp"} | json | response_success="false"

# Slow queries (>100ms)
{service_name="toolhive-doc-mcp"} | json | response_query_time_ms > 100

# Search for specific query text
{service_name="toolhive-doc-mcp"} |= "toolhive installation"

# Error rate by error type
rate({service_name="toolhive-doc-mcp"} | json | response_success="false" [5m]) by (error_type)

# Query latency percentiles
quantile_over_time(0.95, 
  {service_name="toolhive-doc-mcp"} 
  | json 
  | unwrap response_query_time_ms [5m]
) by (query_param_query_type)
```

### Elasticsearch Query Examples

```json
// Successful queries with high scores
{
  "query": {
    "bool": {
      "must": [
        {"term": {"attributes.response.success": true}},
        {"range": {"attributes.response.top_score": {"gte": 0.8}}}
      ]
    }
  }
}

// Most common error types
{
  "aggs": {
    "error_types": {
      "terms": {"field": "attributes.error.type"}
    }
  }
}

// Search query text (full-text)
{
  "query": {
    "match": {
      "body": "How do I install"
    }
  }
}
```

## Metrics Derivation

While we avoid storing high-cardinality data in metrics systems, you can derive **low-cardinality metrics** from logs:

### In Loki (Recording Rules)

```yaml
# Query rate by type
- record: mcp:query_rate:5m
  expr: |
    sum by (query_param_query_type) (
      rate({service_name="toolhive-doc-mcp"} | json [5m])
    )

# Error rate
- record: mcp:error_rate:5m
  expr: |
    sum(rate({service_name="toolhive-doc-mcp"} | json | response_success="false" [5m]))
    /
    sum(rate({service_name="toolhive-doc-mcp"} | json [5m]))

# P95 latency
- record: mcp:query_latency:p95
  expr: |
    quantile_over_time(0.95,
      {service_name="toolhive-doc-mcp"} | json | unwrap response_query_time_ms [5m]
    )
```

## Dashboard Examples

### Key Metrics to Monitor

1. **Query Volume**: Queries per second by type
2. **Success Rate**: Percentage of successful queries
3. **Latency**: P50, P95, P99 query times
4. **Error Rate**: Errors per second by error type
5. **Search Quality**: Average top result scores
6. **Response Sizes**: Distribution of response sizes

### Grafana Dashboard Panels

- **Query Rate**: Time series showing query volume
- **Error Rate**: Time series showing error percentage
- **Latency Distribution**: Histogram of query times
- **Top Errors**: Bar chart of error types
- **Search Quality**: Gauge showing average scores
- **Slow Queries**: Table of queries >100ms with full query text

## Best Practices

1. **Don't add query text to metrics**: Keep it in logs for full-text search
2. **Use structured attributes for filtering**: Filter by tool, query_type, success, error_type
3. **Aggregate in your log backend**: Derive metrics from logs, don't store in Prometheus
4. **Set up alerts on aggregates**: Alert on error rate, P99 latency, etc. (not individual queries)
5. **Use full-text search wisely**: Search logs for debugging specific queries
6. **Retention policies**: Shorter retention for logs (days/weeks) vs metrics (months/years)

## Future Enhancements

Potential improvements:

1. Add sampling for very high-volume environments
2. Add correlation IDs for multi-request workflows
3. Add user/session identification (if applicable)
4. Add custom log processors for PII redaction
5. Add resource usage metrics (CPU, memory) as separate metric streams
