# S3 to Sentinel Log Connector

A high-performance, secure connector for transferring logs from AWS S3 to Microsoft Sentinel.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python: 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](pyproject.toml)

## Features
- Real-time log transfer from S3 to Sentinel
- Multi-format log parsing support
- Secure credential management
- Comprehensive monitoring and alerting
- Production-grade error handling

## Installation

```bash
# Clone the repository
git clone https://github.com/topazyo/s3-sentinel-connector.git
cd s3-sentinel-connector
```

## Quick Start (5-minute)
Run these commands from the repository root. They use existing scripts and files included in the project.

```bash
# Create virtualenv and install runtime deps
python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows PowerShell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# (Optional) install dev tools
pip install -r requirements-dev.txt

# Run tests
pytest -q

# Run lint checks
black --check .
isort --check-only .
ruff check .
```

## Prerequisites
- Python 3.9+ (project configured for `py39` in `pyproject.toml`).
- pip (to install `requirements.txt`).
- (Optional) Docker, Terraform, Azure CLI (`az`), and `kubectl` for deployments.

## Configuration
Config is primarily stored in YAML files under the `config/` directory and supplemented by environment variables for secrets and runtime overrides.

Create a local `.env` for development by copying the provided template:

```bash
cp .env.example .env
# PowerShell: Copy-Item .env.example .env
```

Important environment variables (examples):

- `AWS_REGION` — AWS region (e.g., `us-west-2`)
- `S3_BUCKET_NAME` — S3 bucket to ingest from
- `KEY_VAULT_URL` — Azure Key Vault URL (e.g., `https://<kv-name>.vault.azure.net`)
- `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET` — Azure credentials for Key Vault access (use managed identity in production if possible)
- `SENTINEL_WORKSPACE_ID` — Log Analytics workspace ID for ingestion
- `POLLING_INTERVAL_MINUTES`, `BATCH_SIZE` — runtime tuning parameters

## Files of interest
- `config/base.yaml` — default configuration values
- `src/config/config_manager.py` — typed access & validation for config
- `src/core/s3_handler.py` — S3 listing and batch processing
- `src/core/log_parser.py` — parser contract and normalization
- `src/core/sentinel_router.py` — routing and batching logic for Sentinel
- `src/security/credential_manager.py` — Key Vault-backed secret access
- `src/monitoring/pipeline_monitor.py` — metrics and alert helpers
- `deployment/` — Terraform modules, Kubernetes manifests, and deployment scripts
- `Solutions/S3SentinelConnector/Verification/Simulate_Ingest.py` — local ingestion simulator for verification

## Development workflow
- Install dev dependencies: `pip install -r requirements-dev.txt` or `make install-dev`.
- Formatting: `black .` and `isort .` (or use `make format`).
- Linting: `ruff check .` and `isort --check-only .` and `black --check .` (or use `make lint`).
- Run tests: `pytest -q` (or `make test`).

## Project structure (high level)
- `src/` — application source code
    - `src/core/` — ingestion, parsing, routing components
    - `src/config/` — configuration manager
    - `src/security/` — credential and rotation helpers
    - `src/utils/` — retry, backoff, and resilience utilities
    - `src/monitoring/` — metrics and alerting helpers
- `tests/` — unit and integration tests
- `deployment/` — infra modules and deployment scripts
- `Solutions/` — solution packaging and verification artifacts

## Contributing
See `CONTRIBUTING.md` for contribution guidelines. Quick points:

- Run tests and linters before opening a PR.
- Keep changes small and well documented.
- Add unit tests for new functionality.

## Maintenance notes
- The repository includes `pyproject.toml`, `.env.example`, `requirements-dev.txt`, a GitHub Actions CI workflow (`.github/workflows/ci.yml`), and a `Makefile` to standardize development tasks.
- Consider consolidating overlapping docs under `Solutions/` and `docs/` into a single canonical `docs/` area.

## Discrepancies found
- No CI badges were present previously; CI workflow is now added but you must enable Actions to get a badge URL.
- The old README referenced `yourusername` and example snippets that were generic — replaced with accurate repo owner and commands.
- There was no `.env.example` originally; one is now added to help onboarding.

## License
This project is licensed under the MIT License — see the `LICENSE` file.