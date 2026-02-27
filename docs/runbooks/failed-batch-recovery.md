# Runbook: Failed Batch Recovery

## Summary
Recover and retry log batches that failed to ingest into Azure Sentinel.

## When to Use
- Sentinel ingestion failures detected in monitoring
- Circuit breaker triggered for Sentinel
- Alert: "Failed batch count exceeded threshold"
- Manual inspection during incident response

## Prerequisites
- [ ] Access to Azure Blob Storage (or local failed_batches/ directory)
- [ ] Access to connector logs
- [ ] Understanding of Sentinel ingestion errors

## Procedure

### Step 1: Identify Failed Batches

#### From Azure Blob Storage
```bash
# List failed batches
az storage blob list \
  --container-name sentinel-failed-batches \
  --account-name <storage-account> \
  --query "[].name" \
  --output tsv
```

#### From Local Storage (Fallback)
```bash
# List local failed batches
ls -la failed_batches/
# Files named: failed-batch-<hash>-<timestamp>.json
```

### Step 2: Analyze Failure Reasons

```bash
# Download and inspect a failed batch
az storage blob download \
  --container-name sentinel-failed-batches \
  --account-name <storage-account> \
  --name "failed-batch-abc123-2026-01-30T10-15-30.json" \
  --file /tmp/failed-batch.json

# Check error category
cat /tmp/failed-batch.json | jq '.error_category, .error'
```

Common failure categories:
- `circuit_breaker_open`: Sentinel was unavailable
- `azure_error`: Azure API error (check specific error)
- `timeout`: Request timed out
- `auth_error`: Authentication failed

### Step 3: Resolve Root Cause

| Error Category | Resolution |
|----------------|------------|
| `circuit_breaker_open` | Wait for circuit to close (see [Circuit Breaker Recovery](circuit-breaker-recovery.md)) |
| `azure_error:403` | Check Sentinel permissions |
| `azure_error:429` | Reduce batch rate; wait for rate limit reset |
| `timeout` | Check Sentinel endpoint health |
| `auth_error` | Rotate credentials (see [Credential Rotation](credential-rotation.md)) |

### Step 4: Retry Failed Batches

#### Option A: Automatic Retry (Recommended)

The connector automatically retries failed batches. To trigger:
```bash
# Restart the connector to reprocess failed_batches/
kubectl rollout restart deployment/s3-sentinel-connector
```

#### Option B: Manual Retry Script

```python
import json
import asyncio
from src.core.sentinel_router import SentinelRouter

async def retry_batch(batch_file: str):
    with open(batch_file) as f:
        batch_info = json.load(f)
    
    router = SentinelRouter(
        dcr_endpoint="<endpoint>",
        rule_id="<rule-id>",
        stream_name="<stream>",
        max_concurrent_batches=4,  # Default; see ADR-008 for bounded concurrency policy
    )
    
    # Note: PII was redacted; may need to re-ingest from source
    result = await router.route_logs("firewall", batch_info["data"])
    print(f"Retry result: {result}")

asyncio.run(retry_batch("/tmp/failed-batch.json"))
```

### Step 5: Clean Up Processed Batches

After successful retry, remove processed batch files:

```bash
# Azure Blob Storage
az storage blob delete \
  --container-name sentinel-failed-batches \
  --account-name <storage-account> \
  --name "failed-batch-abc123-2026-01-30T10-15-30.json"

# Local storage
rm failed_batches/failed-batch-abc123-*.json
```

## Verification
- [ ] Root cause identified and resolved
- [ ] Failed batches successfully retried (check Sentinel for data)
- [ ] Failed batch files cleaned up
- [ ] Monitoring shows zero failed batches

## Important Notes

1. **PII Redaction:** Failed batches have PII redacted. If you need full data, re-ingest from S3 source.

2. **Idempotency:** Sentinel handles duplicate logs. Safe to retry batches even if partial success occurred.

3. **Batch Age:** Batches older than retention period may be rejected. Check `batch_timeout` configuration.

## Escalation

If unable to recover batches:
1. Identify time window of data loss
2. Consider re-ingesting from S3 source for that window
3. Create incident report with data loss assessment

## Related ADRs
- [ADR-002: Circuit Breaker Pattern](../adr/ADR-002-circuit-breaker-pattern.md)
- [ADR-005: PII Redaction](../adr/ADR-005-pii-redaction-strategy.md)
- [ADR-008: Bounded Async Batch Concurrency](../adr/ADR-008-bounded-async-batch-concurrency-sentinel.md)
