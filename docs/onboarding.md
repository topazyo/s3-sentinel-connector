# New Developer Onboarding Guide

Welcome to the **S3 to Sentinel Log Connector** project. This guide will take you from a fresh clone to your first successful test run and help you understand how the system works.

---

## Table of Contents

1. [What This System Does](#what-this-system-does)
2. [Prerequisites](#prerequisites)
3. [Local Environment Setup](#local-environment-setup)
4. [Architecture Walkthrough](#architecture-walkthrough)
5. [Key ADR Callouts](#key-adr-callouts)
6. [Common Development Tasks](#common-development-tasks)
7. [First Contribution Workflow](#first-contribution-workflow)
8. [Operational Runbooks](#operational-runbooks)
9. [Project Governance](#project-governance)

---

## What This System Does

This pipeline continuously ingests structured log files from **AWS S3**, parses them into a schema-validated format, and delivers them to **Azure Sentinel** via the Data Collection Rules (DCR) API. Optional ML enrichment can annotate records before ingestion.

```
AWS S3 (log files)
    └─▶ S3Handler  (fetch + filter + batch)
            └─▶ LogParser  (parse + validate + normalise timestamps)
                    └─▶ [Optional: ML Enrichment]
                            └─▶ SentinelRouter  (batch POST to DCR endpoint)
                                    └─▶ Azure Sentinel (Log Analytics tables)

Cross-cutting:
  CredentialManager  ──  Key Vault-backed secrets (no hardcoded credentials)
  PipelineMonitor    ──  Prometheus metrics + structured health checks
  CircuitBreaker     ──  Fault isolation for flaky Sentinel endpoints
```

**Key design values:** security-first (all secrets from Azure Key Vault), resilient (retries with exponential back-off + circuit breakers), observable (structured metrics, not bare `print` statements).

---

## Prerequisites

### System

| Requirement | Minimum | Notes |
|-------------|---------|-------|
| Python | 3.9+ | 3.11 recommended |
| Git | Any recent | — |
| `make` | Any | Unix/macOS native; Windows: use WSL or Git Bash |

### Azure Resources

You need access to (or a sandbox copy of) the following:

| Resource | Purpose |
|----------|---------|
| Azure Key Vault | Stores all credentials; required even in dev |
| Azure Data Collection Endpoint (DCE) | Target for log ingestion |
| Azure Data Collection Rule (DCR) | Defines the ingestion table schema |
| Log Analytics Workspace | Storage backing for Azure Sentinel |
| Azure Entra ID service principal *or* Managed Identity | Auth to Key Vault + DCE |

> **Dev shortcut:** You can point `AZURE_KEYVAULT_URL` at a personal Key Vault with test secrets and use a non-production DCR/DCE pair. Ask a team member for the sandbox resource names.

### AWS Credentials

You need read access to the S3 bucket(s) containing the log files. Valid auth methods:

- Environment variables (`AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY`)
- AWS credential file (`~/.aws/credentials`)
- IAM instance role (EC2/ECS)

---

## Local Environment Setup

### 1. Clone and Bootstrap

```bash
git clone https://github.com/your-org/s3-sentinel-connector.git
cd s3-sentinel-connector

# Create venv, install runtime + dev dependencies
make install-dev
```

### 2. Activate the Virtual Environment

```bash
# Linux / macOS
source .venv/bin/activate

# Windows (PowerShell)
.\.venv\Scripts\Activate.ps1
```

### 3. Configure Environment Variables

Copy the example below, populate with your sandbox values, and paste into your shell profile or a local `.env` file (never commit `.env`):

```bash
# Azure Key Vault (required — all secrets load from here)
export AZURE_KEYVAULT_URL="https://<your-keyvault>.vault.azure.net/"

# Azure Sentinel ingestion targets
export APP_SENTINEL_DCE_ENDPOINT="https://<your-dce>.<region>.ingest.monitor.azure.com"
export APP_SENTINEL_DCR_ID="dcr-<guid>"
export APP_SENTINEL_TABLE_NAME="Custom_Logs_CL"
export APP_SENTINEL_WORKSPACE_ID="<log-analytics-workspace-id>"
export APP_AZURE_TENANT_ID="<tenant-id>"

# Service-principal auth (dev only; use Managed Identity in production)
export APP_AZURE_CLIENT_ID="<sp-client-id>"
export APP_AZURE_CLIENT_SECRET="<sp-client-secret>"

# AWS
export AWS_ACCESS_KEY_ID="<key>"
export AWS_SECRET_ACCESS_KEY="<secret>"
export APP_AWS_REGION="us-west-2"
export APP_AWS_PREFIX="logs/"
```

> Config overrides use the `APP_` prefix. See [ADR-006](adr/ADR-006-config-env-override-path-rules.md) for the full override path rules.

### 4. Verify Setup

```bash
# Run linting
make lint

# Run tests
make test

# Run with coverage (target ≥ 80%)
pytest --cov=src --cov-report=term-missing
```

All checks should pass on a clean clone. If tests fail, check your environment variables first — most failures on a fresh clone are due to missing Azure/AWS configuration.

---

## Architecture Walkthrough

### Source Modules

| Module | Path | Role |
|--------|------|------|
| `S3Handler` | `src/core/s3_handler.py` | Lists, filters, and batch-downloads S3 objects |
| `LogParser` | `src/core/log_parser.py` | Base parser; subclass to add new log types |
| `FirewallLogParser` | `src/core/log_parser.py` | Example subclass for firewall log format |
| `SentinelRouter` | `src/core/sentinel_router.py` | Batches records and POSTs to the DCR endpoint |
| `CredentialManager` | `src/security/credential_manager.py` | Loads all secrets from Azure Key Vault |
| `RotationManager` | `src/security/rotation_manager.py` | Enforces credential rotation policy |
| `ConfigValidator` | `src/security/config_validator.py` | Validates config at startup; fails fast on policy violations |
| `PipelineMonitor` | `src/monitoring/pipeline_monitor.py` | Records Prometheus metrics and component health |
| `CircuitBreaker` | `src/utils/circuit_breaker.py` | Isolates faults to prevent cascading failures |
| `ErrorHandler` | `src/utils/error_handling.py` | `retry_with_backoff` decorator + structured error logging |

### Configuration

Config is layered:

```
config/base.yaml          ← defaults (committed)
config/{dev,prod}.yaml    ← environment overrides (committed; no secrets)
APP_* env vars            ← runtime overrides (highest priority; never committed)
```

Secrets are **never** in YAML files. `CredentialManager` fetches them from Key Vault at runtime.

### Adding a New Log Parser

1. Subclass `LogParser` and implement `parse_record()`.
2. Declare `REQUIRED_FIELDS` and validate all fields are present.
3. Normalise timestamps to RFC 3339.
4. Add a `TableConfig` entry in `SentinelRouter._load_table_configs()`.
5. Write unit tests in `tests/unit/parsers/` (coverage ≥ 80%).

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the full workflow.

---

## Key ADR Callouts

These ADRs are most important to read before making your first change:

| ADR | Title | Why It Matters |
|-----|-------|---------------|
| [ADR-001](adr/ADR-001-rate-limiting-strategy.md) | Rate Limiting Strategy | All S3 and Sentinel calls respect rate limits; change any batch size here first |
| [ADR-002](adr/ADR-002-circuit-breaker-pattern.md) | Circuit Breaker Pattern | All `SentinelRouter` calls go through `CircuitBreaker`; understand before modifying routing logic |
| [ADR-003](adr/ADR-003-credential-management.md) | Credential Management | Why all secrets live in Key Vault; governs `CredentialManager` usage |
| [ADR-005](adr/ADR-005-pii-redaction-strategy.md) | PII Redaction Strategy | Required reading before touching any logging or log parsing code |
| [ADR-006](adr/ADR-006-config-env-override-path-rules.md) | Config Env Override Path Rules | How `APP_` vars map to YAML keys; required before changing config structure |
| [ADR-008](adr/ADR-008-bounded-async-batch-concurrency-sentinel.md) | Bounded Async Batch Concurrency | `max_concurrent_batches` cap rationale; change only with load test evidence |

Full ADR index: [docs/adr/README.md](adr/README.md)

---

## Common Development Tasks

### Run Linting + Formatting

```bash
make lint      # ruff + isort + black (check only — fails on violations)
make format    # auto-fix with black + isort
```

### Run Tests

```bash
make test                             # all tests, quiet
pytest tests/unit/ -v                 # unit tests with verbose output
pytest tests/integration/ -v          # integration tests
pytest --cov=src --cov-report=term-missing   # with coverage
```

### Type Checking

```bash
mypy src/
```

### Security Scan

```bash
bandit -r src/
```

### Add a Config Key

1. Add the key + default value to `config/base.yaml`.
2. If environment-specific, add overrides to `config/dev.yaml` and `config/prod.yaml`.
3. Add a typed accessor helper in `src/config/config_manager.py` (follow the existing `get_aws_config()` / `get_sentinel_config()` pattern).
4. Add validation in `ConfigurationValidator.validate_configuration()` if the key is security-sensitive.
5. Update the config table in `README.md`.

### Rotate a Secret (Local Dev)

```bash
# Manually trigger rotation check (dry-run)
python -c "
from src.config.config_manager import ConfigManager
from src.security.rotation_manager import RotationManager
config = ConfigManager()
rm = RotationManager(config, None)
print(rm.should_rotate('sentinel-api-key', max_age_days=90))
"
```

See the [Credential Rotation Runbook](runbooks/credential-rotation.md) for full details.

---

## First Contribution Workflow

```
1. Create a branch  →  git checkout -b feat/<scope>/<short-description>
2. Make your changes
3. Run checks       →  make lint && mypy src/ && make test && bandit -r src/
4. Commit           →  git commit -m "feat(scope): short summary"
5. Push + open PR   →  reference the issue; fill in the PR checklist
6. Reviewer checks  →  VIBE_QA_CHECKLIST_TEMPLATE.md gates
7. Merge on green
```

**Branch naming examples:**

```
feat/sentinel/add-dns-log-parser
fix/security/rotate-on-401
docs/runbooks/add-dns-flood-alert
test/s3/missing-coverage-filter
```

**Commit types:** `feat` | `fix` | `refactor` | `test` | `docs` | `chore` | `security` | `perf`

For the full PR checklist, see [CONTRIBUTING.md](../CONTRIBUTING.md#pr-checklist).

---

## Operational Runbooks

| Runbook | When to Use |
|---------|------------|
| [Performance Troubleshooting](runbooks/performance-troubleshooting.md) | High latency, slow ingestion, S3 throughput issues |
| [Circuit Breaker Recovery](runbooks/circuit-breaker-recovery.md) | Sentinel endpoint errors causing circuit open state |
| [Credential Rotation](runbooks/credential-rotation.md) | Manual or emergency credential rotation |
| [Failed Batch Recovery](runbooks/failed-batch-recovery.md) | Recovering from failed ingestion batches in `failed_batches/` |

Runbook index: [docs/runbooks/README.md](runbooks/README.md)

---

## Project Governance

This project follows a 10-phase VIBE code quality audit framework. The governance documents you may encounter:

| Document | Purpose |
|----------|---------|
| [`AGENTS.md`](../AGENTS.md) | Architecture map and agent operating rules |
| [`audit/VIBE_AUDIT_ROADMAP.md`](../audit/VIBE_AUDIT_ROADMAP.md) | Phases 1–10 audit findings (source of truth for what's being fixed) |
| [`VIBE_DEBT_INVENTORY_ACTIVE.md`](../VIBE_DEBT_INVENTORY_ACTIVE.md) | Live list of open debt items |
| [`VIBE_QA_CHECKLIST_TEMPLATE.md`](../VIBE_QA_CHECKLIST_TEMPLATE.md) | PR review checklist covering all 10 phases |
| [`docs/adr/`](adr/) | Architecture Decision Records |

You do not need to read all of these to make your first contribution — start with the ADRs listed above and `CONTRIBUTING.md`.

---

## Getting Help

- Search existing GitHub Issues and Discussions before opening a new one.
- For security vulnerabilities, follow the process in [SECURITY.md](../SECURITY.md).
- For operational incidents, follow the [runbooks](runbooks/README.md) first, then escalate.
