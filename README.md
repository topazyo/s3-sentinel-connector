# S3 to Sentinel Log Connector

A connector that ingests logs from AWS S3 and routes them into Microsoft Sentinel / Azure Log Analytics, with schema-validated parsing, Key Vault-backed secrets, circuit-breaker resilience, and Prometheus metrics.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python: 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](pyproject.toml)

## Key Features

- **Batch S3 ingestion** — filtered, parallel file processing with token-bucket rate limiting ([src/core/s3_handler.py](src/core/s3_handler.py))
- **Schema-validated parsing** — firewall and JSON log parsers with RFC 3339 timestamp normalisation ([src/core/log_parser.py](src/core/log_parser.py))
- **Azure Sentinel routing** — bounded-concurrency async ingestion via Data Collection Rules API ([src/core/sentinel_router.py](src/core/sentinel_router.py), [ADR-008](docs/adr/ADR-008-bounded-async-batch-concurrency-sentinel.md))
- **Key Vault-backed secrets** — no hardcoded credentials; automated rotation via `RotationManager` ([src/security/credential_manager.py](src/security/credential_manager.py), [ADR-003](docs/adr/ADR-003-credential-management.md))
- **Circuit breaker resilience** — protects S3, Sentinel, and Key Vault calls from cascading failures ([src/utils/circuit_breaker.py](src/utils/circuit_breaker.py), [ADR-002](docs/adr/ADR-002-circuit-breaker-pattern.md))
- **Prometheus metrics** — structured health, alert, and performance telemetry ([src/monitoring/pipeline_monitor.py](src/monitoring/pipeline_monitor.py))

## Architecture

```
AWS S3 Bucket
    |  (batch + rate-limited listing & download)
    v
S3Handler  [src/core/s3_handler.py]
    |  (bytes -> parsed dict; schema-validated)
    v
LogParser  [src/core/log_parser.py]
    |  (firewall / JSON parsers; RFC 3339 timestamps)
    v
SentinelRouter  [src/core/sentinel_router.py]
    |  (bounded async batches; PII redaction; failed-batch storage)
    v
Azure Sentinel / Log Analytics  ------------------------------------------------+
                                                                                 |
CredentialManager  (Key Vault)  ----- all secrets --------------------------------+
PipelineMonitor    (Prometheus) ----- health & metrics
```

Configuration is layered: `config/base.yaml` -> `config/{dev,prod}.yaml` -> `APP_*` environment variable overrides.
See [ADR-006](docs/adr/ADR-006-config-env-override-path-rules.md) for override path semantics.

## Quickstart

These steps produce a local development environment and run tests.
PowerShell equivalents are noted where shell syntax differs.

**1. Clone**

```bash
git clone https://github.com/topazyo/s3-sentinel-connector.git
cd s3-sentinel-connector
```

**2. Create a virtual environment and install runtime dependencies**

```bash
python -m venv .venv
# macOS / Linux:
source .venv/bin/activate
# Windows PowerShell:
# .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**3. Install developer tools** (linters, test runner)

```bash
pip install -r requirements-dev.txt
```

**4. Copy the example environment file**

```bash
cp .env.example .env        # macOS / Linux
# Windows: Copy-Item .env.example .env
```

Edit `.env` with your AWS and Azure values. **Never commit `.env`.**

**5. Run tests**

```bash
pytest -q
# or: make test
```

**6. Run linters**

```bash
black --check .
isort --check-only .
ruff check .
# or: make lint
```

The `Makefile` exposes `make install`, `make install-dev`, `make test`, `make lint`, and `make format`.
On Windows, run the underlying commands directly (the Makefile targets use a Unix shell).

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.9+ | Configured in `pyproject.toml` |
| pip | For dependency installation |
| Azure Key Vault | Required for production secrets; see [credential-rotation runbook](docs/runbooks/credential-rotation.md) |
| Azure Sentinel workspace | DCR endpoint + rule ID needed at runtime |
| AWS IAM credentials | S3 read access on the target bucket |
| Docker / Terraform / kubectl | Optional — only for deployment artifacts under `deployment/` |

## Configuration

Runtime configuration is read from YAML files in `config/` and from `APP_*`-prefixed environment variables.
See [ADR-006](docs/adr/ADR-006-config-env-override-path-rules.md) for the exact override rules.

Key environment variables (defined in `.env.example`):

| Variable | Description |
|---|---|
| `AWS_REGION` | AWS region (e.g., `us-west-2`) |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | AWS credentials — **local dev only**; use IAM roles / managed identity in production |
| `S3_BUCKET_NAME` | S3 bucket to ingest from |
| `KEY_VAULT_URL` | Azure Key Vault URL — all production secrets are retrieved from here |
| `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET` | Azure service principal — **local dev only**; use Managed Identity in production |
| `SENTINEL_WORKSPACE_ID` | Log Analytics workspace ID |
| `POLLING_INTERVAL_MINUTES`, `BATCH_SIZE` | Runtime tuning parameters |

**Production auth:** `CredentialManager` chains `ManagedIdentityCredential` before `DefaultAzureCredential`.
Managed Identity is the recommended auth path in production; service-principal env vars are for local development only.

## Project Layout

```
src/
  core/         S3 handler, log parsers, Sentinel router
  config/       ConfigManager with env overrides and hot-reload
  security/     CredentialManager, RotationManager, AccessControl, EncryptionManager
  monitoring/   PipelineMonitor (Prometheus), ComponentMetrics
  ml/           Optional anomaly-detection enrichment
  utils/        CircuitBreaker, ErrorHandler, RateLimiter, transformations, validation
config/         YAML config files (base, dev, prod, tables)
tests/          Unit and integration tests
deployment/     Terraform, Kubernetes manifests, deployment scripts
docs/
  adr/          Architecture Decision Records (ADR-001 thru ADR-010)
  runbooks/     Operational runbooks (credential rotation, failed-batch recovery, etc.)
  api.md        API quick-reference
  API_CONTRACTS.md  Authoritative contract definitions
```

## Documentation

| Topic | Link |
|---|---|
| API quick-reference | [docs/api.md](docs/api.md) |
| API contracts | [docs/API_CONTRACTS.md](docs/API_CONTRACTS.md) |
| Architecture overview | [docs/architecture.md](docs/architecture.md) |
| ADR index | [docs/adr/README.md](docs/adr/README.md) |
| Credential rotation runbook | [docs/runbooks/credential-rotation.md](docs/runbooks/credential-rotation.md) |
| Failed-batch recovery runbook | [docs/runbooks/failed-batch-recovery.md](docs/runbooks/failed-batch-recovery.md) |
| Performance troubleshooting | [docs/runbooks/performance-troubleshooting.md](docs/runbooks/performance-troubleshooting.md) |
| Circuit-breaker recovery | [docs/runbooks/circuit-breaker-recovery.md](docs/runbooks/circuit-breaker-recovery.md) |

## CI/CD

- GitHub Actions CI runs tests and linters on `push`/`pull_request` to `main` — see [.github/workflows/ci.yml](.github/workflows/ci.yml).
- Additional deployment workflows live under `deployment/.github/workflows/`.

## Terraform Tasks (VS Code)

The workspace includes standardized Terraform tasks in [.vscode/tasks.json](.vscode/tasks.json):

- `terraform fmt recursive` — applies `terraform fmt -recursive` via [deployment/scripts/terraform_fmt_recursive.ps1](deployment/scripts/terraform_fmt_recursive.ps1)
- `terraform fmt check recursive` — non-mutating format check
- `terraform validate all` — runs `init -backend=false` + `validate` for:
  - `deployment/terraform/environments`
  - `deployment/terraform/environments/dev`
  - `deployment/terraform/environments/prod`
- `terraform validate all (upgrade providers)` — same validation with `init -upgrade`
- `terraform quality gate` — sequential `fmt check` + `validate all`

You can also run validation directly:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File deployment/scripts/terraform_validate_all.ps1
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Before submitting a PR, ensure:

```bash
pytest -q               # all tests pass
black --check .         # formatting
isort --check-only .    # import order
ruff check .            # linting
```

CI enforces these checks automatically.

## Security

Do not commit secrets. Report security vulnerabilities privately via the repository owners.
See [SECURITY.md](SECURITY.md) for the full disclosure policy.

## License

MIT — see [LICENSE](LICENSE).
