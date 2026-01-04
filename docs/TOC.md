# Table Of Contents — Developer Docs

This file is a compact, curated table of contents for contributors and reviewers. Use it as the central entry point for repository documentation. Keep this file small and update it when you add or move top-level docs.

Purpose
-------
- Quick navigation for new contributors.
- Authoritative list of canonical docs to avoid duplication.

Top-level docs
---------------
- `README.md` — Repository overview, quick start, and development workflow.
- `CONTRIBUTING.md` — How to contribute, PR checks, commit style, and review guidance.
- `LICENSE` — Project license (MIT).

Audit & governance
-------------------
- `AGENTS.md` — Agent operating rules and governance reference.
- `audit/VIBE_AUDIT_ROADMAP.md` — Audit findings and Phase 10 execution roadmap.
- `audit/VIBE_DEBT_EXECUTIVE_SUMMARY.md` — Executive summary of technical debt.

Configuration & deployment
---------------------------
- `config/` — YAML config defaults and environment overrides (`base.yaml`, `dev.yaml`, `prod.yaml`).
- `deployment/` — Terraform, Kubernetes manifests, and deployment scripts.
- `Makefile` — Common developer tasks and build targets.

Code & examples
----------------
- `src/` — Application source code (core, security, monitoring, utils).
- `Solutions/` — Solution-level packaging and verification scripts.
- `tests/` — Unit and integration tests.

CI / Quality
-----------
- `.github/workflows/` — GitHub Actions workflows (CI, lint, test).
- `requirements-dev.txt` and `pyproject.toml` — Development and runtime dependencies.

Maintenance notes
------------------
- Keep a single canonical README. If you add a new top-level doc, update this TOC.
- Avoid duplicating content between `docs/`, `Solutions/`, and top-level files — consolidate when possible.
- When renaming files, update any references in `docs/TOC.md` and the top-level `README.md`.

If you want, open a PR to expand sections into separate markdown pages (Onboarding, Deployment Runbook, Observability).
