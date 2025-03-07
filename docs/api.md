# API Documentation

## Core Components

### S3Handler

```python
class S3Handler:
    async def list_objects(
        bucket: str,
        prefix: str = "",
        last_processed_time: Optional[datetime] = None
    ) -> List[Dict]:
        """
        List objects in S3 bucket
        
        Args:
            bucket: S3 bucket name
            prefix: Object prefix
            last_processed_time: Only list objects after this time
            
        Returns:
            List of object metadata
        """
```

### SentinelRouter

```python
class SentinelRouter:
    async def route_logs(
        log_type: str,
        logs: List[Dict[str, Any]],
        data_classification: str = 'standard'
    ) -> Dict[str, Any]:
        """
        Route logs to Sentinel
        
        Args:
            log_type: Type of logs
            logs: Log data
            data_classification: Data classification level
            
        Returns:
            Routing results
        """
```

## ML Components

### MLEnhancedConnector

```python
class MLEnhancedConnector:
    async def process_logs(
        logs: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Process logs with ML enhancements
        
        Args:
            logs: Raw log data
            
        Returns:
            Enhanced logs with ML insights
        """
```

## Security Components

### CredentialManager

```python
class CredentialManager:
    async def get_credential(
        credential_name: str,
        force_refresh: bool = False
    ) -> str:
        """
        Get credential from vault or cache
        
        Args:
            credential_name: Name of credential
            force_refresh: Force refresh from vault
            
        Returns:
            Credential value
        """
```

## Monitoring Components

### PipelineMonitor

```python
class PipelineMonitor:
    async def record_metric(
        metric_name: str,
        value: float,
        labels: Optional[Dict[str, str]] = None
    ) -> None:
        """
        Record metric
        
        Args:
            metric_name: Name of metric
            value: Metric value
            labels: Metric labels
        """
```

## Error Handling

### Common Errors

```python
class RetryableError(Exception):
    """Error that should trigger retry"""
    pass

class NonRetryableError(Exception):
    """Error that should not be retried"""
    pass
```

## Configuration

### Example Configuration

```yaml
azure:
  key_vault_url: str
  tenant_id: str
  
aws:
  region: str
  bucket_name: str
  
sentinel:
  workspace_id: str
  dcr_endpoint: str
```

## Usage Examples

### Basic Usage

```python
# Initialize components
s3_handler = S3Handler(...)
sentinel_router = SentinelRouter(...)
ml_connector = MLEnhancedConnector(...)

# Process logs
logs = await s3_handler.list_objects(bucket, prefix)
enhanced_logs = await ml_connector.process_logs(logs)
result = await sentinel_router.route_logs('firewall', enhanced_logs)
```

### Error Handling

```python
try:
    result = await process_logs(logs)
except RetryableError as e:
    # Implement retry logic
    pass
except NonRetryableError as e:
    # Log error and continue
    pass
```

### Monitoring

```python
# Record metrics
await monitor.record_metric(
    'logs_processed',
    len(logs),
    {'source': 's3', 'type': 'firewall'}
)

# Check health
health = await monitor.get_component_health('s3_handler')
```