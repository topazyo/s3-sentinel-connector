# API Contracts Reference

This document defines the contracts for the core public APIs in the S3 Sentinel Connector.

## Overview

All public APIs follow these conventions:
- Input validation at entry points
- Typed parameters and return values (via dataclasses and type hints)
- Structured error handling with specific exception types
- Async operations for I/O-bound work

---

## Core Module Contracts

### LogParser (Abstract Base Class)

**Location:** `src/core/log_parser.py`

```python
class LogParser(ABC):
    @abstractmethod
    def parse(self, log_data: bytes) -> Dict[str, Any]:
        """Parse raw log data into structured format.
        
        Input Contract:
            - log_data: bytes - Raw log data, encoding determined by parser
            
        Output Contract:
            - Returns Dict with at minimum:
                - TimeGenerated: datetime - Timestamp of log event
                - LogSource: str - Source identifier
            - Additional fields depend on log type
            
        Failure Contract:
            - Raises LogParserException on parse failure
            - Preserves original error as __cause__
        """
        
    @abstractmethod
    def validate(self, parsed_data: Dict[str, Any]) -> bool:
        """Validate parsed log data.
        
        Input Contract:
            - parsed_data: Dict from parse() method
            
        Output Contract:
            - Returns True if all required fields present and valid
            - Returns False with logged reason on validation failure
        """
```

### SentinelRouter

**Location:** `src/core/sentinel_router.py`

```python
class SentinelRouter:
    async def route_logs(
        self,
        log_type: str,
        logs: List[Dict[str, Any]],
        data_classification: str = "standard",
    ) -> Dict[str, Any]:
        """Route logs to Azure Sentinel with batching and error handling.
        
        Input Contract:
            - log_type: str - Must match a configured table (firewall, vpn, etc.)
            - logs: List[Dict] - Each dict must have TimeGenerated key
            - data_classification: str - One of: standard, confidential, restricted
            
        Output Contract:
            - Returns Dict with:
                - processed: int - Count of successfully ingested logs
                - failed: int - Count of failed logs
                - batch_count: int - Number of batches sent
                - start_time: datetime - Processing start time
                - dropped: int - Count of dropped logs (e.g., duplicates)
                
        Failure Contract:
            - Raises ValueError for unsupported log_type
            - Failed batches are stored for recovery (see failed_batches/)
            - Circuit breaker may open after repeated failures
        """
```

### S3Handler

**Location:** `src/core/s3_handler.py`

```python
class S3Handler:
    def process_files_batch(
        self,
        bucket: str,
        objects: List[Dict[str, Any]],
        parser: Optional[LogParser] = None,
        callback: Optional[callable] = None,
        log_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Process a batch of S3 objects.
        
        Input Contract:
            - bucket: str - S3 bucket name
            - objects: List[Dict] - Each dict must have 'Key' and 'Size' keys
            - parser: Optional LogParser instance for parsing content
            - callback: Optional function(key, content) for processing
            - log_type: Optional str for parser selection
            
        Output Contract:
            - Returns Dict with:
                - successful: List[str] - Keys of successfully processed files
                - failed: List[str] - Keys of failed files
                - metrics: Dict with total_files, total_bytes, timing info
                
        Failure Contract:
            - Rate limiting applied (10 req/sec default)
            - Individual file failures logged but don't abort batch
            - Returns partial results on batch failure
        """
```

---

## Configuration Contracts

### ConfigManager

**Location:** `src/config/config_manager.py`

```python
class ConfigManager:
    @classmethod
    async def create(
        cls,
        config_path: Optional[str] = None,
        environment: str = "dev",
        vault_url: Optional[str] = None,
        enable_hot_reload: bool = True,
    ) -> "ConfigManager":
        """Factory method for async initialization with Key Vault.
        
        Input Contract:
            - config_path: str or None - Path to config directory
            - environment: str - One of: dev, staging, prod
            - vault_url: str or None - Azure Key Vault URL
            - enable_hot_reload: bool - Enable file watching for config changes
            
        Output Contract:
            - Returns fully initialized ConfigManager
            - Secret client initialized if vault_url provided
            
        Failure Contract:
            - Raises ConfigurationError on invalid config
            - Raises RuntimeError on Key Vault connection failure
        """
```

### Config Dataclasses

All configuration dataclasses follow this contract:

```python
@dataclass
class SomeConfig:
    """Configuration for [component].
    
    Attributes:
        required_field: type - Description (no default = required)
        optional_field: type = default - Description
    """
```

Required fields must be provided; optional fields have sensible defaults.

---

## Security Contracts

### CredentialManager

**Location:** `src/security/credential_manager.py`

```python
class CredentialManager:
    async def get_credential(
        self, credential_name: str, force_refresh: bool = False
    ) -> str:
        """Retrieve credential from Key Vault with caching.
        
        Input Contract:
            - credential_name: str - Key Vault secret name
            - force_refresh: bool - Bypass cache if True
            
        Output Contract:
            - Returns credential value as string
            
        Failure Contract:
            - Raises RetryableError on timeout (safe to retry)
            - Raises CircuitBreakerOpenError if circuit open
            - Uses encrypted cache as fallback when circuit open
        """
        
    async def rotate_credential(
        self, credential_name: str, new_value: Optional[str] = None
    ) -> str:
        """Rotate credential in Key Vault.
        
        Input Contract:
            - credential_name: str - Secret to rotate
            - new_value: str or None - Explicit value or auto-generate
            
        Output Contract:
            - Returns new credential value
            - Invalidates cache entry
            
        Failure Contract:
            - Raises RetryableError on timeout
            - Raises CircuitBreakerOpenError if circuit open
            - Old credential remains valid if rotation fails
        """
```

---

## Monitoring Contracts

### PipelineMonitor

**Location:** `src/monitoring/pipeline_monitor.py`

```python
class PipelineMonitor:
    def record_metric(
        self,
        metric_name: str,
        value: float,
        labels: Optional[Dict[str, str]] = None,
    ) -> None:
        """Record a metric value.
        
        Input Contract:
            - metric_name: str - Metric identifier (alphanumeric + underscore)
            - value: float - Metric value
            - labels: Dict or None - Key-value labels for dimensions
            
        Output Contract:
            - Metric recorded in internal buffer
            - Prometheus metrics updated if enabled
            
        Failure Contract:
            - Invalid metric names logged and skipped
            - No exceptions raised (fire-and-forget)
        """
        
    def update_component_health(
        self,
        component: str,
        healthy: bool,
        message: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Update health status for a component.
        
        Input Contract:
            - component: str - Component identifier
            - healthy: bool - Health status
            - message: str - Status message
            - metadata: Dict or None - Additional context
            
        Output Contract:
            - Health status updated in registry
            - Alerts triggered if unhealthy threshold crossed
        """
```

---

## Error Handling Contracts

### Exception Hierarchy

```
Exception
├── LogParserException          # Log parsing failures
├── ConfigurationError          # Configuration validation failures
├── CircuitBreakerOpenError     # Circuit breaker protection active
├── RetryableError              # Transient failure, safe to retry
└── ValidationError             # Input validation failure
```

### Retry Decorator Contract

```python
@retry_with_backoff(
    max_retries: int = 3,
    initial_delay_seconds: float = 1.0,
    max_delay_seconds: float = 30.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
)
def some_function():
    """Function with automatic retry on failure.
    
    Retry Contract:
        - Retries on any Exception (configurable)
        - Exponential backoff with jitter
        - Final failure re-raises original exception
        - Total wait time: sum of delays between attempts
    """
```

---

## Data Model Contracts

### Log Entry Schema

All parsed logs must conform to this base schema:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| TimeGenerated | datetime | Yes | Event timestamp (UTC) |
| LogSource | str | Yes | Source system identifier |
| CorrelationId | str | No | Request correlation ID |

Additional fields depend on log type (firewall, vpn, dns, etc.).

### Failed Batch Schema

Failed batches stored in `failed_batches/` follow this schema:

```json
{
  "batch_id": "uuid",
  "table_name": "string",
  "timestamp": "ISO8601",
  "error": "string",
  "error_category": "string",
  "retry_count": 0,
  "data": [...],  // PII redacted
  "correlation_id": "string"
}
```

---

## Version Compatibility

| API Version | Python | Azure SDK | Breaking Changes |
|-------------|--------|-----------|------------------|
| 1.0.0 | 3.9+ | 2024.x | Initial release |

---

## See Also

- [ADR-001: Rate Limiting Strategy](adr/ADR-001-rate-limiting-strategy.md)
- [ADR-002: Circuit Breaker Pattern](adr/ADR-002-circuit-breaker-pattern.md)
- [ADR-003: Credential Management](adr/ADR-003-credential-management.md)
- [Runbook: Failed Batch Recovery](runbooks/failed-batch-recovery.md)
