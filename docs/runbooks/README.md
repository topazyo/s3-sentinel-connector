# Operational Runbooks

This directory contains runbooks for common operational tasks and incident response procedures.

## Index

| Runbook | Description | When to Use |
|---------|-------------|-------------|
| [Credential Rotation](credential-rotation.md) | Rotate AWS and Azure credentials | Scheduled rotation or suspected compromise |
| [Failed Batch Recovery](failed-batch-recovery.md) | Recover and retry failed log batches | Sentinel ingestion failures |
| [Circuit Breaker Recovery](circuit-breaker-recovery.md) | Diagnose and recover from circuit breaker open state | Service unavailability alerts |
| [Performance Troubleshooting](performance-troubleshooting.md) | Diagnose performance issues | High latency or throughput degradation |

## Runbook Template

When creating a new runbook, use the following structure:

```markdown
# Runbook: [Title]

## Summary
[One-line description of what this runbook covers]

## When to Use
- [Scenario 1]
- [Scenario 2]

## Prerequisites
- [ ] Access to [system/tool]
- [ ] Permissions: [required permissions]

## Procedure

### Step 1: [Action]
[Detailed instructions]

```bash
# Commands if applicable
```

### Step 2: [Action]
[Detailed instructions]

## Verification
- [ ] [How to verify success]

## Rollback
[If applicable, how to undo changes]

## Escalation
- [Who to contact if runbook doesn't resolve issue]
```
