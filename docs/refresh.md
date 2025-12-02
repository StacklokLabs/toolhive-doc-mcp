# Background Refresh Configuration

The MCP server includes a background refresh mechanism that automatically rebuilds the documentation database at regular intervals to keep the search index up-to-date with the latest documentation sources.

## How It Works

When the MCP server starts, it initializes the background refresh system based on the configuration in `sources.yaml`. The refresh process:

1. Starts automatically when the MCP server launches (if enabled)
2. Runs at intervals defined by `interval_hours`
3. Fetches the latest documentation from all configured sources
4. Rebuilds the vector database with updated content
5. Repeats the cycle at the configured interval

The refresh runs in the background without interrupting active queries or server operations.

## Configuration

The refresh configuration is defined in the `sources.yaml` file under the `refresh` section:

```yaml
refresh:
  enabled: true              # Enable/disable background refresh
  interval_hours: 24         # Refresh every 24 hours
  max_concurrent_jobs: 1     # Prevent overlapping refreshes
```

### Configuration Options

#### `enabled`
- **Type:** boolean
- **Default:** `true`
- **Description:** Enable or disable the background refresh mechanism. When disabled, the database will only be updated manually using the build script.

#### `interval_hours`
- **Type:** integer
- **Range:** 1-168 (1 hour to 7 days)
- **Default:** `24`
- **Description:** The time interval in hours between refresh operations. The first refresh starts when the MCP server launches, and subsequent refreshes occur at this interval.

**Examples:**
- `1` - Refresh every hour
- `6` - Refresh every 6 hours
- `24` - Refresh daily
- `168` - Refresh weekly

#### `max_concurrent_jobs`
- **Type:** integer
- **Range:** >= 1
- **Default:** `1`
- **Description:** Maximum number of concurrent refresh jobs allowed. Setting this to `1` prevents overlapping refresh operations, ensuring that a new refresh won't start if the previous one is still running.
