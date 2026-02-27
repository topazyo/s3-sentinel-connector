# API Documentation

This document provides a quick-reference API surface for the core modules.
For detailed contract definitions (input/output/failure behavior), see `docs/API_CONTRACTS.md`.

## Core Components

### S3Handler (`src/core/s3_handler.py`)

```python
class S3Handler:
    def list_objects(
        self,
        bucket: str,
        prefix: str = "",
        last_processed_time: Optional[datetime] = None,
        max_keys: int = 1000,
    ) -> List[Dict[str, Any]]

    async def list_objects_async(
        self,
        bucket: str,
        prefix: str = "",
        last_processed_time: Optional[datetime] = None,
        max_keys: int = 1000,
    ) -> List[Dict[str, Any]]

    def process_files_batch(
        self,
        bucket: str,
        objects: List[Dict[str, Any]],
        parser: Optional[LogParser] = None,
        callback: Optional[callable] = None,
        log_type: Optional[str] = None,
        batch_size: Optional[int] = None,
    ) -> Dict[str, Any]

    async def process_files_batch_async(
        self,
        bucket: str,
        objects: List[Dict[str, Any]],
        parser: Optional[LogParser] = None,
        callback: Optional[callable] = None,
        log_type: Optional[str] = None,
        batch_size: Optional[int] = None,
    ) -> Dict[str, Any]
```

**Behavior summary**
- `list_objects` is synchronous; `list_objects_async` is the async wrapper.
- Batch processors return per-file success/failure aggregates and metrics.
- Content validation and parser validation are enforced before callback dispatch.

### LogParser (`src/core/log_parser.py`)

```python
class LogParser(ABC):
    def parse(self, log_data: bytes) -> Dict[str, Any]
    def validate(self, parsed_data: Dict[str, Any]) -> bool
```

**Implementations**
- `FirewallLogParser`
- `JsonLogParser`

**Behavior summary**
- `parse` transforms raw bytes into normalized dictionaries.
- `validate` returns boolean validity and is expected to be called before routing.
- Parser-specific exceptions use `LogParserException` semantics.

### SentinelRouter (`src/core/sentinel_router.py`)

```python
class SentinelRouter:
    async def route_logs(
        self,
        log_type: str,
        logs: List[Dict[str, Any]],
        data_classification: str = "standard",
    ) -> Dict[str, Any]

    def get_failed_batch_metrics(self) -> Dict[str, Any]
    def get_health_status(self) -> Dict[str, Any]
```

**Behavior summary**
- `route_logs` batches and ingests records by table config.
- Unsupported `log_type` raises `ValueError`.
- Empty input returns a skip response (`{"status": "skip", "message": "No logs to process"}`).
- Failures are categorized and tracked for observability (`failure_reasons`, failure rate, recommendations).

## Security Components

### CredentialManager (`src/security/credential_manager.py`)

```python
class CredentialManager:
    async def get_credential(
        self,
        credential_name: str,
        force_refresh: bool = False,
    ) -> str
```

**Behavior summary**
- Reads from encrypted cache first when valid, unless `force_refresh=True`.
- Uses circuit-breaker-protected Key Vault access for resilience.
- Can raise `CircuitBreakerOpenError` or `RetryableError` in transient/failure states.

## Configuration Components

### ConfigManager (`src/config/config_manager.py`)

```python
class ConfigManager:
    @classmethod
    async def create(
        cls,
        config_path: Optional[str] = None,
        environment: str = "dev",
        vault_url: Optional[str] = None,
        enable_hot_reload: bool = True,
    ) -> "ConfigManager"

    def get_config(self, component: str) -> Dict[str, Any]
```

**Behavior summary**
- `create` performs async initialization and optional Key Vault setup.
- `get_config` returns merged/validated component configuration.

## Monitoring Components

### PipelineMonitor (`src/monitoring/pipeline_monitor.py`)

```python
class PipelineMonitor:
    async def start(self) -> None

    async def record_metric(
        self,
        metric_name: str,
        value: float,
        labels: Optional[Dict[str, str]] = None,
    ) -> None

    async def update_component_health(
        self,
        component: str,
        status: bool,
        details: Optional[Dict[str, Any]] = None,
    ) -> None
```

**Behavior summary**
- `start` launches background health/alert/export loops.
- Metric recording is async and non-blocking toward pipeline flow.
- Component health updates are reflected in metric stream and internal state.

## Error Types

Common operational error classes used across modules include:
- `RetryableError`
- `NonRetryableError`
- `CircuitBreakerOpenError`
- `LogParserException`

Refer to module-specific contracts in `docs/API_CONTRACTS.md` for precise failure conditions.

## Minimal Usage Example

```python
# S3 list + route example
objects = s3_handler.list_objects(bucket="my-bucket", prefix="firewall/")

# Convert object payloads through your parser flow, then route
result = await sentinel_router.route_logs(
    log_type="firewall",
    logs=prepared_logs,
    data_classification="standard",
)

await monitor.record_metric("logs_processed", float(result.get("processed", 0)))
```