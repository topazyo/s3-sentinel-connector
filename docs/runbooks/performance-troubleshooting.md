# Runbook: Performance Troubleshooting

## Summary
Diagnose and resolve performance issues in the S3 to Sentinel Connector.

## When to Use
- Alert: "Processing latency exceeded threshold"
- Throughput degradation observed
- Memory or CPU usage spikes
- User-reported slow log ingestion

## Prerequisites
- [ ] Access to monitoring dashboards (Prometheus/Grafana)
- [ ] Access to connector logs
- [ ] Access to Azure Monitor metrics
- [ ] Understanding of pipeline architecture

## Key Performance Metrics

| Metric | Normal Range | Alert Threshold |
|--------|--------------|-----------------|
| Batch processing time | <5s | >30s |
| S3 download latency | <500ms | >2s |
| Sentinel ingestion latency | <1s | >5s |
| Memory usage | <500MB | >1GB |
| CPU usage | <50% | >80% |
| Rate limit wait time | 0ms | >1s |

## Procedure

### Step 1: Identify the Bottleneck

```bash
# Check Prometheus metrics
curl localhost:9090/api/v1/query?query=log_processing_duration_seconds

# Check connector logs for timing
kubectl logs -l app=s3-sentinel-connector --tail=500 | grep -E "duration|latency|timeout"
```

**Decision tree:**

```
Slow processing?
├── S3 download slow? → Check S3 throttling
├── Parsing slow? → Check log complexity
├── Sentinel slow? → Check Sentinel health
└── Memory high? → Check batch sizes
```

### Step 2: S3 Performance Issues

#### Symptoms
- High `rate_limited` metric count
- "SlowDown" errors in logs
- Long download times

#### Diagnosis
```bash
# Check rate limiter stats
kubectl logs -l app=s3-sentinel-connector | grep "rate_limited"

# Check S3 throttling
aws cloudwatch get-metric-statistics \
  --namespace AWS/S3 \
  --metric-name 5xxErrors \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 300 \
  --statistics Sum
```

#### Resolution
1. **Reduce rate limit:** Lower `rate_limit` in config
2. **Increase batch size:** Process more per request
3. **Add prefix partitioning:** Spread load across S3 prefixes

### Step 3: Parsing Performance Issues

#### Symptoms
- High CPU usage during parsing
- Long processing time for specific log types

#### Diagnosis
```bash
# Profile parser performance
python -c "
import cProfile
from src.core.log_parser import FirewallLogParser

parser = FirewallLogParser()
cProfile.run('parser.parse(b\"test|192.168.1.1|10.0.0.1|allow|rule1|tcp|443|80|1000\")')
"
```

#### Resolution
1. **Check log size limits:** Ensure `max_size_bytes` is appropriate
2. **Simplify regex patterns:** If custom patterns are slow
3. **Enable compression:** Reduce I/O overhead

### Step 4: Sentinel Ingestion Performance

#### Symptoms
- High Sentinel latency in metrics
- Timeouts during ingestion
- Circuit breaker opening frequently

#### Diagnosis
```bash
# Check Sentinel metrics
az monitor metrics list \
  --resource <sentinel-workspace-id> \
  --metric "Ingestion Latency" \
  --interval PT1H

# Check batch sizes
kubectl logs -l app=s3-sentinel-connector | grep "batch_size"
```

#### Resolution
1. **Reduce batch size:** If batches are too large (lower `sentinel.batch_size` in config)
2. **Increase parallelism:** Raise `max_concurrent_batches` in `SentinelRouter` constructor (default: 4, see ADR-008)
3. **Check Sentinel quotas:** May need to request limit increase

### Step 5: Memory Issues

#### Symptoms
- OOMKilled pods
- High memory usage
- Slow garbage collection

#### Diagnosis
```bash
# Check memory usage
kubectl top pods -l app=s3-sentinel-connector

# Check for memory leaks
kubectl logs -l app=s3-sentinel-connector | grep -i "memory"
```

#### Resolution
1. **Reduce batch size:** Smaller in-memory batches
2. **Increase memory limits:** If legitimately needed
3. **Enable streaming:** For very large files

### Step 6: Apply Fixes

After identifying the issue, update configuration:

```yaml
# Example: Reduce load for throttling issues
aws:
  batch_size: 500    # Reduced from 1000
  rate_limit: 5.0    # Reduced from 10.0

sentinel:
  batch_size: 500    # Reduced from 1000
  # Note: batch_timeout is a SentinelRouter constructor param (default: 30s),
  # NOT a yaml config key. To change it, modify the SentinelRouter instantiation
  # in src/core/__init__.py: SentinelRouter(..., batch_timeout=60)
  #
  # To increase Sentinel parallelism, set max_concurrent_batches (default: 4,
  # see ADR-008): SentinelRouter(..., max_concurrent_batches=8)
```

## Verification
- [ ] Latency returned to normal range
- [ ] No new errors or throttling
- [ ] Memory/CPU usage stable
- [ ] Throughput meets SLA

## Performance Tuning Reference

| Scenario | Tune | Effect |
|----------|------|--------|
| High latency | Increase parallelism | More concurrent operations |
| Throttling | Decrease rate limit | Slower but stable |
| Memory pressure | Decrease batch size | Less memory per batch |
| Low throughput | Increase batch size | More efficient I/O |

## Escalation

If performance doesn't improve:
1. Capture detailed profiling data
2. Check for upstream service issues (S3, Sentinel)
3. Consider horizontal scaling (more replicas)
4. Engage Azure/AWS support for quota increases

## Related ADRs
- [ADR-001: Rate Limiting Strategy](../adr/ADR-001-rate-limiting-strategy.md)
- [ADR-002: Circuit Breaker Pattern](../adr/ADR-002-circuit-breaker-pattern.md)
- [ADR-008: Bounded Async Batch Concurrency](../adr/ADR-008-bounded-async-batch-concurrency-sentinel.md)
