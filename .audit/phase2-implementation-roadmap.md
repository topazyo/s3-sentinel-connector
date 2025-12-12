# Phase 2 Implementation Roadmap

## 1. Dependency Analysis

| Function / Area | Location | Blocked By | Notes |
| --- | --- | --- | --- |
| `CoreManager.__init__`, `CoreManager._initialize_components` | `src/core/__init__.py` | `CredentialManager.get_credential`, S3 handler missing APIs | Orchestrator cannot function until S3 handler methods and credential async issues resolved. |
| `S3Handler.process_files_batch`, `S3Handler.list_objects`, `S3Handler._process_single_file` | `src/core/s3_handler.py` | `_log_batch_results`, `download_object`, `_validate_content`, `_handle_aws_error`, `_get_error_message` | Core ingestion blocked until missing helpers implemented. |
| `JsonLogParser.parse` | `src/core/log_parser.py` | `_apply_schema`, bytes decoding | Parser fails until helper added; downstream Sentinel pipeline depends on parsed output. |
| `SentinelRouter._ingest_batch` | `src/core/sentinel_router.py` | Azure client sync usage, `_store_failed_batch` stub | Needs correct async handling and persistence to avoid loss. |
| Monitoring stack (`MonitoringManager`, `PipelineMonitor`) | `src/monitoring/__init__.py`, `pipeline_monitor.py` | Missing modules (`AlertManager`, `metrics`), helper functions `_collect_current_metrics`, `_check_*`, `_get_metric_value`, `_get_teams_webhook`, `_send_slack_alert`, `_get_active_alerts` | Health/alerting disabled until scaffolding restored. |
| ML connector (`MLEnhancedConnector`) | `src/ml/enhanced_connector.py` | Missing feature extractors, enhancement routines, task helpers | Optional but numerous dependencies; should follow core + monitoring repairs. |
| Security layer async misuse | `src/security/credential_manager.py`, `src/security/__init__.py`, `security/access_control.py`, `security/encryption.py` | Synchronous Azure clients awaited, `_get_current_user`, `_reencrypt_data`, config expectations | Credential access/rotation broken until corrected. |
| Retry utilities | `src/utils/error_handling.py` | Missing imports (`asyncio`, `random`) | Required by multiple modules for resilience. |

Implementation order:
1. Utilities & shared helpers (`utils/error_handling`, missing imports).
2. Core ingestion layer (S3 handler helpers, log parser fixes, CoreManager async handling).
3. Sentinel router upload flow (`_ingest_batch`, `_store_failed_batch`).
4. Security basic functionality (credential manager sync/async fixes, access control helper).
5. Monitoring scaffolding (provide missing helpers or stub modules to restore functionality).
6. ML connector (define missing extractors, enhancement pipeline) once core+monitoring stable.
7. Secondary refinements (encryption rotation helper, schema validation depth, etc.).

## 2. Priority Buckets

### CRITICAL (project unusable)
| Item | Location | Status | Dependencies | Complexity |
| --- | --- | --- | --- | --- |
| Restore missing API methods in `S3Handler` (`download_object`, `_validate_content`, `_handle_aws_error`, `_get_error_message`, `_log_batch_results`) | `src/core/s3_handler.py` | Missing | Requires boto3/botocore patterns; interplay with tests. | High |
| Fix async misuse in `CoreManager` & align S3 handler usage | `src/core/__init__.py` | Broken | Depends on working `S3Handler` and credential manager returning dict-like secrets. | High |
| Correct `CredentialManager` async usage of Key Vault SDK | `src/security/credential_manager.py` | Broken | Need synchronous handling or async wrapper; affects CoreManager bootstrapping. | High |
| Implement `_apply_schema` and byte decoding in `JsonLogParser.parse` | `src/core/log_parser.py` | Broken | Depended on by S3 pipeline tests. | Medium |
| Add missing imports (`random`, `asyncio`, `hashlib`, `time`) | Multiple files | Broken | Blocks execution across decorators, ML hashing, encryption. | Low |

### HIGH (core functionality gaps)
| Item | Location | Status | Dependencies | Complexity |
| --- | --- | --- | --- | --- |
| Implement `_get_error_message` and retry classifications for S3 errors | `src/core/s3_handler.py` | Missing | Relies on botocore error structure; ensures retry semantics align with tests. | Medium |
| Make `S3Handler.process_files_batch` support callback signature & metrics logging | `src/core/s3_handler.py` | Incomplete | Depends on `_process_single_file`, `_log_batch_results`. | Medium |
| Fix `SentinelRouter._ingest_batch` to use sync client correctly and persist failed batches | `src/core/sentinel_router.py` | Broken/Stub | Requires `_store_failed_batch` implementation. | Medium |
| Provide `_store_failed_batch` persistence (e.g., local storage stub) | `src/core/sentinel_router.py` | Stub | Needed for retries/logging. | Medium |
| Implement `_get_current_user` for AccessControl decorators (or restructure) | `src/security/access_control.py` | Missing | Could accept user via context or token; required for permission checks. | Medium |
| Add `_collect_current_metrics`, `_check_s3_health`, `_check_sentinel_health`, `_check_pipeline_lag` | `src/monitoring/pipeline_monitor.py` | Missing | Maybe stub with placeholder metrics initially. | High |
| Provide `_get_metric_value`, `_export_to_azure_monitor`, `_export_to_prometheus`, `_get_active_alerts`, `_get_teams_webhook`, `_send_slack_alert` | `src/monitoring/pipeline_monitor.py` | Missing | Required for monitoring features. | High |

### MEDIUM (secondary features)
| Item | Location | Status | Dependencies | Complexity |
| --- | --- | --- | --- | --- |
| Define ML feature extractors (`_extract_numerical_features`, `_extract_categorical_features`) | `src/ml/enhanced_connector.py` | Missing | Build after core ingestion works; may leverage pandas. | High |
| Implement `_enhance_logs`, `_get_cache_key`, `_process_anomaly`, `_process_high_priority`, `_process_normal`, `_cache_cleanup`, `_pattern_analysis`, `_update_preprocessors` | `src/ml/enhanced_connector.py` | Missing | Extensive; may need simplification. | Very High |
| Reconcile `MonitoringManager` imports (`metrics`, `alerts`) by creating modules or adjusting design | `src/monitoring/__init__.py` | Broken | Depends on final monitoring design. | Medium |
| Improve config validation depth (`ConfigManager._validate_config`) | `src/config/config_manager.py` | Needs review | After core issues fixed. | Low |
| Provide security config schema / convert dicts to `SecurityPolicy` | `src/security/__init__.py` | Needs review | Tied to overall security config approach. | Medium |
| Implement `_reencrypt_data` for key rotation or remove reference | `src/security/encryption.py` | Missing | Optional but necessary for rotation story. | Medium |

### LOW (quality & polish)
| Item | Location | Status | Dependencies | Complexity |
| --- | --- | --- | --- | --- |
| Handle Prometheus metric registration cleanup/shutdown | `src/monitoring/pipeline_monitor.py` | Missing | After monitoring rebuilt. | Low |
| Improve logging import consistency (`logging` missing in some modules) | Various | Missing | Straightforward. | Low |
| Schema validation enhancements for config/environment overrides | `src/config/config_manager.py` | Needs review | Optional improvement. | Low |
| Expand unit tests once core functionality restored | `tests/` | Missing coverage | After implementation. | Medium |

## 3. Summary
- Begin with shared utilities/import fixes, then restore S3 ingestion and core orchestrator functionality.
- Address security credential access patterns to unblock CoreManager initialization.
- Rebuild monitoring scaffolding to reinstate health/alert loops.
- Defer ML enhancements until foundational layers pass tests; treat as separate incremental milestone.
- Track stubs and missing helpers explicitly to ensure no reference remains unresolved before closing Phase 2.
