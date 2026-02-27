# Table Of Contents — Developer Docs

This file is a compact, curated table of contents for contributors and reviewers.
Use it as the central entry point for repository documentation.
Keep this file small and update it when you add or move top-level docs.

## Purpose

- Quick navigation for new contributors.
- Authoritative list of canonical docs to avoid duplication.

## Getting Started

| Document | Purpose |
|----------|---------|
| [`README.md`](../README.md) | Repository overview, architecture diagram, quick start |
| [`docs/onboarding.md`](onboarding.md) | Step-by-step guide for new developers |
| [`CONTRIBUTING.md`](../CONTRIBUTING.md) | PR process, coding standards, commit conventions |
| [`SECURITY.md`](../SECURITY.md) | Security vulnerability disclosure process |

## Reference Docs

| Document | Purpose |
|----------|---------|
| [`docs/api.md`](api.md) | Python API reference for core modules |
| [`docs/API_CONTRACTS.md`](API_CONTRACTS.md) | Behavioural contracts (inputs, outputs, error semantics) |
| [`docs/architecture.md`](architecture.md) | Detailed architecture and design decisions |
| [`docs/deployment.md`](deployment.md) | Deployment guide (Kubernetes, Terraform) |
| [`docs/monitoring.md`](monitoring.md) | Observability, Prometheus metrics, alerting |
| [`docs/ml_features.md`](ml_features.md) | ML enrichment pipeline documentation |

## Architecture Decision Records

All ADRs live in [`docs/adr/`](adr/) and are indexed in [`docs/adr/README.md`](adr/README.md).

Key ADRs for new contributors:

| ADR | Title |
|-----|-------|
| [ADR-001](adr/ADR-001-rate-limiting-strategy.md) | Rate Limiting Strategy |
| [ADR-002](adr/ADR-002-circuit-breaker-pattern.md) | Circuit Breaker Pattern |
| [ADR-003](adr/ADR-003-credential-management.md) | Credential Management |
| [ADR-005](adr/ADR-005-pii-redaction-strategy.md) | PII Redaction Strategy |
| [ADR-006](adr/ADR-006-config-env-override-path-rules.md) | Config Env Override Path Rules |
| [ADR-008](adr/ADR-008-bounded-async-batch-concurrency-sentinel.md) | Bounded Async Batch Concurrency |

## Operational Runbooks

All runbooks live in [`docs/runbooks/`](runbooks/) and are indexed in [`docs/runbooks/README.md`](runbooks/README.md).

| Runbook | Purpose |
|---------|---------|
| [performance-troubleshooting.md](runbooks/performance-troubleshooting.md) | High latency, slow ingestion |
| [circuit-breaker-recovery.md](runbooks/circuit-breaker-recovery.md) | Sentinel circuit-breaker recovery |
| [credential-rotation.md](runbooks/credential-rotation.md) | Credential rotation (manual or emergency) |
| [failed-batch-recovery.md](runbooks/failed-batch-recovery.md) | Recovering failed ingestion batches |

## Configuration & Deployment

- `config/` — YAML config defaults and environment overrides (`base.yaml`, `dev.yaml`, `prod.yaml`).
- `deployment/` — Terraform, Kubernetes manifests, and deployment scripts.
- `Makefile` — Common developer tasks: `make install-dev`, `make lint`, `make test`, `make format`.

## Source Code

- `src/` — Application source code (core, security, monitoring, utils, ml).
- `tests/` — Unit and integration tests.
- `examples/` — Usage examples for config and monitoring.

## Maintenance Notes

- Keep a single canonical README. Add new top-level docs here; avoid duplicating content between `docs/` and top-level files.
- When renaming files, update references in this TOC and in `README.md`.
- New ADRs go in `docs/adr/` and must be added to `docs/adr/README.md`.
