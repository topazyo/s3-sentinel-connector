# Changelog

All notable changes to this project are documented in this file.

The format is based on Keep a Changelog.

## [Unreleased]

### Added
- Operational runtime commands in `s3-sentinel` CLI:
  - `run` (long-lived pipeline mode)
  - `ingest` (single cycle)
  - `validate-config`
  - `replay-failed`
- Health/readiness/metrics HTTP server for Kubernetes probes and Prometheus scraping.
- Failed batch cleanup utility (`scripts/cleanup_failed_batches.py`).
- Container build context controls via `.dockerignore`.
- Additional pre-commit hooks (hygiene hooks, detect-secrets, Terraform fmt check).
- CI dependency vulnerability scan (`pip-audit`) and CD image scan (Trivy).
- Terraform backend scaffolding files for dev/prod environments.

### Changed
- Docker runtime default command now starts service mode (`s3-sentinel run`).
- Kubernetes overlays updated to modern Kustomize `resources` references.

## [1.0.0] - 2026-02-27

### Added
- Completion of all VIBE audit debt remediation batches (1-8).
- Security hardening, resilience patterns, and performance optimizations across core pipeline modules.
- Documentation baseline: API contracts, runbooks, onboarding, and architecture notes.
- Month 2 implementation baseline:
  - Docker build foundation (`Dockerfile`)
  - Pre-commit quality hooks (`.pre-commit-config.yaml`)
  - Terraform module completion + CI validation checks
  - Active root CD workflow
  - Kubernetes Service/ConfigMap/HPA manifests and monitoring expansions
  - Smoke tests and E2E pipeline test scaffolding
  - Dedicated `component_metrics.py` unit tests
  - RBAC role configuration templates under `config/roles/`

### Changed
- Hardened Terraform security posture by disabling ACR admin credentials and applying AKS AcrPull role assignment.
- Replaced tracked production env template with `prod.env.example` and ignored concrete env files.
