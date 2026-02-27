# Contributing to S3 to Sentinel Log Connector

Thank you for contributing! This guide covers setup, code standards, and the PR process.
If you are a new contributor, read [docs/onboarding.md](docs/onboarding.md) first.
For security vulnerabilities, see [SECURITY.md](SECURITY.md).

---

## Table of Contents

1. [Development Setup](#development-setup)
2. [Coding Standards](#coding-standards)
3. [Running Tests](#running-tests)
4. [Submitting a Pull Request](#submitting-a-pull-request)
5. [Reporting Bugs](#reporting-bugs)
6. [Suggesting Enhancements](#suggesting-enhancements)

---

## Development Setup

```bash
# Clone and bootstrap
git clone https://github.com/your-org/s3-sentinel-connector.git
cd s3-sentinel-connector

# Create venv and install runtime + dev dependencies
make install-dev

# Activate the virtual environment
# Linux/macOS:
source .venv/bin/activate
# Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
```

See `README.md` for required environment variables (Azure DCE/DCR endpoints, Key Vault URL, AWS credentials).

---

## Coding Standards

### Language

This is a **Python-only** project (3.9+). Do not add PowerShell or other scripting unless in `scripts/` helpers.

### Style

| Tool | Purpose | Command |
|------|---------|---------|
| `black` | Code formatting | `make format` |
| `isort` | Import ordering | `make format` |
| `ruff` | Linting | `make lint` |

All three run automatically in CI. Run locally before pushing:

```bash
make lint    # fails on style violations
make format  # auto-fixes formatting
```

### Type Annotations

All new public functions and methods **must** have complete type annotations.
Check types with:

```bash
mypy src/
```

### Docstrings

All public modules, classes, and methods require docstrings (Google-style).
Format:

```python
def my_function(arg: str) -> bool:
    """One-line summary.

    Args:
        arg: Description of the argument.

    Returns:
        Description of return value.

    Raises:
        ValueError: When arg is empty.
    """
```

### Security Rules (Phase 5)

- **Never** hardcode credentials, tokens, or URLs. Use `CredentialManager` (Key Vault-backed).
- **Never** log credentials or personal data — redact before logging.
- Run `bandit -r src/` to confirm no security warnings before submitting.

### Architecture Patterns (Phase 4 / Phase 6)

- I/O operations must have explicit timeouts and use `retry_with_backoff` (see `src/utils/error_handling.py`).
- Sentinel ingestion must batch records (do not send one-by-one).
- Use `PipelineMonitor` for structured metrics — no bare `print()` or unstructured `logging.info()`.

See `AGENTS.md` and the `docs/adr/` index for pattern decisions.

---

## Running Tests

```bash
# Run all unit + integration tests
make test

# Run with coverage report (target: ≥80%)
pytest --cov=src --cov-report=term-missing

# Run only a specific module
pytest tests/unit/test_sentinel_router.py -v
```

Coverage must not drop below 80% on touched files. If your change reduces coverage,
add or update tests before opening a PR.

## Terraform Checks (if touching `deployment/terraform/`)

If your PR changes Terraform files, run the standardized Terraform quality gate before opening the PR:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File deployment/scripts/terraform_fmt_recursive.ps1 -Check
pwsh -NoProfile -ExecutionPolicy Bypass -File deployment/scripts/terraform_validate_all.ps1
```

VS Code tasks are also available in `.vscode/tasks.json`:

- `terraform fmt check recursive`
- `terraform validate all`
- `terraform quality gate`

---

## Submitting a Pull Request

### Before Opening a PR

Run the full local check suite:

```bash
make lint            # ruff + isort + black
mypy src/            # type checking
pytest --cov=src     # tests + coverage
bandit -r src/       # security scan
```

All four must pass with no new errors or warnings.

### PR Checklist

Use this checklist in your PR description:

```
## PR Checklist

### Functional
- [ ] Fixes the intended issue / implements stated feature
- [ ] Minimal scope — single concern per PR

### Quality Gates
- [ ] `make lint` passes
- [ ] `mypy src/` passes (no new type errors)
- [ ] `pytest --cov=src` passes; coverage ≥ 80% on touched files
- [ ] `bandit -r src/` passes (no new security warnings)

### Resilience (Phase 4)
- [ ] External I/O has explicit timeouts
- [ ] Error handling uses `ErrorHandler` / `retry_with_backoff`
- [ ] Structured logging via `PipelineMonitor` (no bare `print`)

### Security (Phase 5)
- [ ] No hardcoded secrets, tokens, or URLs
- [ ] No credentials in log output
- [ ] Input validation applied to external data

### Testing (Phase 7)
- [ ] Unit tests added for happy path + error cases
- [ ] Integration tests added if multi-module interaction
- [ ] No flaky or time-dependent tests

### Documentation (Phase 8)
- [ ] Docstrings added / updated
- [ ] ADR created if decision has lasting architectural impact
- [ ] Runbook updated if operational behaviour changes
- [ ] `README.md` or `CONTRIBUTING.md` updated if user-facing flow changes
```

Reviewers use `VIBE_QA_CHECKLIST_TEMPLATE.md` for the full 10-phase gate review.

### Commit Message Convention

```
<type>(<scope>): <short summary>

Types: feat | fix | refactor | test | docs | chore | security | perf
Scope: s3 | sentinel | security | monitoring | config | ml | utils | tests | docs

Examples:
  feat(sentinel): add batch retry with exponential backoff
  fix(security): rotate credential on KeyVault 401 response
  docs(runbooks): correct circuit-breaker config snippet
  test(s3): add unit tests for filtered file listing
```

---

## Reporting Bugs

1. Search existing issues before filing a new one.
2. Use the bug report template.
3. Include:
   - Python version and OS
   - Minimal reproduction steps
   - Relevant log output (redact any credentials or PII)
   - Expected vs. actual behaviour

---

## Suggesting Enhancements

1. Search existing issues and discussions.
2. Use the feature request template.
3. Describe the use case and expected behaviour.
4. If the change affects system architecture, propose an ADR (see `docs/adr/README.md`).

---

## Questions?

Open a Discussion on GitHub or ping the team in the project channel.
