# Project Structure

This document describes the organization of the S3 Sentinel Connector codebase.

## Directory Layout

```
s3-sentinel-connector/
├── src/                        # Main source code
│   ├── config/                 # Configuration management
│   ├── core/                   # Core pipeline components
│   ├── ml/                     # Machine learning features (optional)
│   ├── monitoring/             # Metrics and alerting
│   ├── security/               # Security components
│   └── utils/                  # Shared utilities
├── tests/                      # Test suite
│   ├── unit/                   # Unit tests (by module)
│   └── integration/            # Integration tests
├── config/                     # YAML configuration files
├── docs/                       # Documentation
│   ├── adr/                    # Architecture Decision Records
│   └── runbooks/               # Operational runbooks
├── deployment/                 # Deployment artifacts
│   ├── kubernetes/             # K8s manifests
│   ├── monitoring/             # Monitoring configs
│   ├── scripts/                # Deployment scripts
│   └── terraform/              # Infrastructure as code
├── audit/                      # VIBE audit reports
└── scripts/                    # Development scripts
```

## Module Descriptions

### `src/config/`
Configuration management with Key Vault integration.

| File | Purpose |
|------|---------|
| `config_manager.py` | Main ConfigManager class with hot reload |

**Key Classes:**
- `ConfigManager`: Central configuration with Key Vault secrets
- `DatabaseConfig`, `AwsConfig`, `SentinelConfig`, `MonitoringConfig`: Typed config dataclasses

### `src/core/`
Core data pipeline components.

| File | Purpose |
|------|---------|
| `log_parser.py` | Log parsing with multiple format support |
| `s3_handler.py` | AWS S3 log ingestion with rate limiting |
| `sentinel_router.py` | Azure Sentinel ingestion with batching |

**Key Classes:**
- `LogParser` (ABC): Abstract base for log parsers
- `FirewallLogParser`, `JsonLogParser`: Concrete parsers
- `S3Handler`: S3 operations with rate limiting
- `SentinelRouter`: Sentinel ingestion with circuit breaker

### `src/security/`
Security components for authentication, encryption, and access control.

| File | Purpose |
|------|---------|
| `credential_manager.py` | Key Vault credential management |
| `rotation_manager.py` | Credential rotation automation |
| `encryption.py` | Data encryption utilities |
| `config_validator.py` | Security policy validation |
| `access_control.py` | RBAC and JWT authentication |
| `audit.py` | Security audit logging |

**Key Classes:**
- `CredentialManager`: Key Vault integration with caching
- `RotationManager`: Automated credential rotation
- `EncryptionManager`: Data encryption
- `ConfigurationValidator`: Security policy enforcement
- `AccessControl`: JWT-based authentication

### `src/monitoring/`
Observability and alerting components.

| File | Purpose |
|------|---------|
| `pipeline_monitor.py` | Main monitoring class |
| `alerts.py` | Alert definitions and firing |
| `component_metrics.py` | Per-component metrics |
| `__init__.py` | MonitoringManager (aggregator) |

**Key Classes:**
- `PipelineMonitor`: Metrics collection and export
- `AlertCondition`: Alert threshold definitions
- `MonitoringManager`: Background task coordination

### `src/utils/`
Shared utility modules.

| File | Purpose |
|------|---------|
| `circuit_breaker.py` | Circuit breaker pattern |
| `rate_limiter.py` | Token bucket rate limiting |
| `error_handling.py` | Retry decorators and error tracking |
| `tracing.py` | Correlation ID propagation |
| `validation.py` | Input validation utilities |
| `transformations.py` | Data transformation helpers |

**Key Classes:**
- `CircuitBreaker`: Async circuit breaker
- `RateLimiter`: Token bucket implementation
- `ErrorHandler`: Centralized error handling
- Decorators: `@retry_with_backoff`, `@with_circuit_breaker`

### `src/ml/`
Optional machine learning features.

| File | Purpose |
|------|---------|
| `enhanced_connector.py` | ML-enhanced log processing |

**Key Classes:**
- `EnhancedConnector`: Anomaly detection, pattern analysis

## Configuration Files

| Path | Purpose |
|------|---------|
| `config/base.yaml` | Default configuration |
| `config/dev.yaml` | Development overrides |
| `config/prod.yaml` | Production overrides |
| `config/tables.yaml` | Sentinel table mappings |
| `config/logging.yaml` | Logging configuration |

## Test Organization

```
tests/
├── unit/                       # Isolated unit tests
│   ├── config/                 # Config tests
│   ├── core/                   # Core module tests
│   ├── monitoring/             # Monitoring tests
│   ├── security/               # Security tests
│   └── utils/                  # Utility tests
├── integration/                # Multi-component tests
└── conftest.py                 # Shared fixtures
```

## Import Conventions

1. **Standard library imports first**
2. **Third-party imports second**
3. **Local imports third** (from src.*)
4. **Relative imports within same package**

Example:
```python
import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from azure.identity import DefaultAzureCredential
import boto3

from src.config.config_manager import ConfigManager
from src.utils.circuit_breaker import CircuitBreaker
from .helpers import normalize_timestamp
```

## Module Dependencies

```
config/
  └── (no internal dependencies)

utils/
  └── (no internal dependencies)

core/
  ├── config/
  └── utils/

security/
  ├── config/
  └── utils/

monitoring/
  ├── config/
  └── utils/

ml/
  ├── core/
  ├── config/
  └── monitoring/
```

No circular dependencies exist between modules.

## Key Design Principles

1. **Separation of Concerns**: Each module has a single responsibility
2. **Dependency Injection**: Components receive dependencies via constructor
3. **Configuration-Driven**: Behavior controlled by YAML configs
4. **Async-First**: I/O operations are async where possible
5. **Fail-Fast**: Invalid configuration fails at startup
6. **Observable**: All components emit structured metrics

## See Also

- [Architecture Documentation](architecture.md)
- [API Contracts](API_CONTRACTS.md)
- [Deployment Guide](deployment.md)
