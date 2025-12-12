# S3 Sentinel Connector — Agent Guide
## Architecture Basics
- Pipeline runs S3 ingestion (`src/core/s3_handler.py`) → parsing (`src/core/log_parser.py`) → optional ML enrichment (`src/ml/enhanced_connector.py`) → Sentinel routing (`src/core/sentinel_router.py`).
- `docs/architecture.md` details the intended flow; keep new components aligned with that sequence and data contracts between stages.
- Security (`src/security/*`) and monitoring (`src/monitoring/pipeline_monitor.py`) wrap the flow; reuse them rather than reimplementing secrets, alerting, or metrics.
## S3 Intake & Parsing
- `S3Handler` is constructed with retry, batch, and threading controls; `process_files_batch` fans out via `ThreadPoolExecutor` and aggregates metrics under `results['metrics']`.
- Retry semantics rely on raising `RetryableError`; `tests/test_s3_handler.py` expects `_handle_aws_error` to flag SlowDown/InternalError for retry and others to bubble as `ClientError`.
- `download_object` is expected to stream data, transparently decompress `.gz`, and return bytes that pass `_validate_content` (JSON parsing for `.json`, non-empty for others).
- Parsing factories in `src/core/log_parser.py` map raw fields to Sentinel-friendly names; `FirewallLogParser.validate` enforces IP format and action enums, so extend mappings before touching Sentinel schemas.
## Sentinel Routing & Tables
- `SentinelRouter.route_logs` is async and uses `asyncio.TaskGroup`; when adding work ensure coroutine-safe helpers and avoid blocking I/O.
- Table metadata flows through `TableConfig`; keep it in sync with `config/tables.yaml` so required fields, types, and batch sizes match ingestion rules.
- `_prepare_log_entry` applies `transform_map` and ensures `TimeGenerated`; any new log type must define transform and datatype maps before batching.
- Ingestion goes through `LogsIngestionClient.upload`; tests stub this, so inject or monkeypatch client methods instead of calling Azure endpoints during unit tests.
## Configuration & Secrets
- `ConfigManager` merges `config/base.yaml` with environment overrides (e.g., `config/dev.yaml`); the cache is guarded by `_config_lock` and decorated `@lru_cache`.
- Environment overrides must use the `APP_<SECTION>_<KEY>` pattern (e.g., `APP_AWS_REGION`) to reach nested config via `_set_nested_value`.
- Hot reload relies on `watchdog`; disable via `enable_hot_reload=False` in tests or scripts to avoid background threads in constrained environments.
- Secrets live behind `CredentialManager` (`src/security/credential_manager.py`), which chains managed identity and default credentials and encrypts cached secrets with Fernet when available.
## Monitoring, ML, Security Layers
- `PipelineMonitor` spawns async loops for health, metrics, and alerts, exporting both to Azure Monitor and Prometheus; patch `MetricsIngestionClient` during tests to prevent network calls.
- Alert fan-out couples to webhook actions (Teams/Slack) via `aiohttp`; new alert types should extend `AlertConfig` and reuse `_check_alert_condition`.
- `MLEnhancedConnector` expects models under `models/` plus numpy/pandas/TensorFlow; wrap calls with try/except and honor cache methods to keep inference fast.
- Credential rotation flows through `RotationManager`; call `check_rotation_needed` before `rotate_credentials` and respect `min_rotation_interval_hours` in configuration.
## Developer Workflow
- Prefer `pip install -r requirements.txt`; add extras used in code/tests (`pytest-asyncio`, `moto`, `prometheus-client`, `aiohttp`, `watchdog`, `numpy`, `pandas`, `scikit-learn`, `tensorflow`, `joblib`).
- The package layout is src-based; run scripts/tests with `PYTHONPATH=src` or install in editable mode (`pip install -e .`) after aligning `setup.py` with actual requirement file locations.
- Terraform and Kubernetes manifests live under `deployment/`; follow `docs/deployment.md` for infra before shipping runtime changes.
- Operational scripts in `scripts/` (e.g., `diagnose_connectivity.sh`, `check_compliance.sh`) are the source of truth for troubleshooting—update them when behavior changes.
## Testing Patterns
- Use `pytest --asyncio-mode=auto`; async fixtures in `tests/test_sentinel_router.py` rely on that setting.
- S3 flows are mocked with `moto.mock_s3`; seed buckets via fixtures like `mock_s3_bucket` instead of manual boto3 calls in tests.
- Config tests create temp dirs; instantiate `ConfigManager(..., enable_hot_reload=False)` unless you intentionally validate the watchdog path.
- Security tests expect `ConfigurationValidator.validate_configuration` to return dictionaries with `valid`, `violations`, and `warnings`; preserve that contract when extending rules.
