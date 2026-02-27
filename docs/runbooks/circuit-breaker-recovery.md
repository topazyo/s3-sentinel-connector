# Runbook: Circuit Breaker Recovery

## Summary
Diagnose and recover from circuit breaker open state for external services.

## When to Use
- Alert: "Circuit breaker OPEN for [service-name]"
- Logs show `CircuitBreakerOpenError`
- Service unavailable errors in monitoring

## Prerequisites
- [ ] Access to connector logs
- [ ] Access to monitoring dashboards
- [ ] Understanding of circuit breaker states

## Circuit Breaker States

```
CLOSED (normal) → OPEN (failing) → HALF_OPEN (testing) → CLOSED (recovered)
```

| State | Description | Action |
|-------|-------------|--------|
| CLOSED | Normal operation | None required |
| OPEN | Service failing; requests rejected | Investigate service |
| HALF_OPEN | Testing recovery; limited requests | Monitor closely |

## Procedure

### Step 1: Identify Which Circuit Is Open

```bash
# Check connector logs for circuit breaker state
kubectl logs -l app=s3-sentinel-connector --tail=500 | grep -i "circuit"

# Expected output:
# "Circuit breaker OPEN for 'azure-sentinel'"
# "Circuit breaker OPEN for 'azure-key-vault'"
```

### Step 2: Check Service Health

#### For Azure Sentinel
```bash
# Check Azure Service Health
az monitor activity-log list \
  --resource-group <rg> \
  --status "Failed" \
  --offset 1h

# Check Sentinel endpoint directly
curl -I https://<dcr-endpoint>.ingest.monitor.azure.com/health
```

#### For Azure Key Vault
```bash
# Check Key Vault health
az keyvault show --name <vault-name> --query "properties.provisioningState"

# Try manual secret retrieval
az keyvault secret show --vault-name <vault-name> --name test-secret
```

#### For AWS S3
```bash
# Check S3 bucket access
aws s3 ls s3://<bucket-name>/ --max-items 1

# Check AWS Service Health
aws health describe-events --filter "services=S3"
```

### Step 3: Wait for Automatic Recovery

Circuit breakers automatically recover:
1. **Failure threshold:** 5 failures to open circuit (default)
2. **Min calls before open:** 10 calls evaluated before the circuit can trip (default)
3. **Recovery timeout:** 60 seconds (default)
4. **Half-open test:** 3 requests allowed (`half_open_max_calls`)
5. **Success threshold:** 2 successes to close

**Monitor for recovery:**
```bash
# Watch for state transitions
kubectl logs -l app=s3-sentinel-connector -f | grep -i "circuit"

# Look for:
# "Circuit breaker transitioning to HALF_OPEN"
# "Circuit breaker transitioning to CLOSED"
```

### Step 4: Manual Recovery (If Needed)

If circuit doesn't recover after service is healthy:

#### Option A: Restart the Service
```bash
# Restart resets circuit breaker state
kubectl rollout restart deployment/s3-sentinel-connector
```

#### Option B: Adjust Circuit Breaker Config (Temporary)

Circuit breaker config is set at instantiation in code (not a YAML config key).
To temporarily relax thresholds, modify the `CircuitBreakerConfig` in
`src/utils/circuit_breaker.py` or pass a custom config at construction time:

```python
from src.utils.circuit_breaker import CircuitBreaker, CircuitBreakerConfig

custom_config = CircuitBreakerConfig(
    recovery_timeout=300,    # 5 minutes instead of default 60s
    failure_threshold=10,    # More lenient than default 5
)
breaker = CircuitBreaker("azure-sentinel", config=custom_config)
```

> **Note:** Restart the service to apply changes if modifying code defaults.

### Step 5: Investigate Root Cause

Once recovered, investigate why the service failed:

| Service | Common Causes | Resolution |
|---------|---------------|------------|
| Sentinel | Rate limiting (429) | Reduce batch rate |
| Sentinel | Auth failure (401/403) | Rotate credentials |
| Key Vault | Rate limiting | Increase cache duration |
| Key Vault | Network issues | Check VNet/firewall rules |
| S3 | Throttling (503) | Reduce request rate |
| S3 | Permission denied | Check IAM policies |

## Verification
- [ ] Circuit breaker returned to CLOSED state
- [ ] Service requests succeeding (check logs)
- [ ] Failed batches being processed (if any queued)
- [ ] Monitoring alerts cleared

## When Circuit Won't Close

If circuit remains open after service recovery:

1. **Check failure threshold:** May have accumulated during outage
2. **Check success threshold:** Half-open requests may still be failing
3. **Check timeouts:** Service may be slow, causing timeout failures

**Force reset by restart:**
```bash
kubectl rollout restart deployment/s3-sentinel-connector
```

## Escalation

If circuit keeps reopening:
1. Service may have intermittent issues
2. Engage service owner (Azure support, AWS support)
3. Consider temporary workaround (increase thresholds, enable fallback)

## Related ADRs
- [ADR-002: Circuit Breaker Pattern](../adr/ADR-002-circuit-breaker-pattern.md)
- [ADR-008: Bounded Async Batch Concurrency](../adr/ADR-008-bounded-async-batch-concurrency-sentinel.md)
