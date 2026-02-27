# src/utils/__init__.py

"""
Utility modules for S3-to-Sentinel connector.

**Phase 2 (Consistency):** Centralized imports for common utilities
**Phase 5 (Security - B1-001):** RateLimiter for abuse prevention
**Phase 4 (Resilience - B2-001):** Error handling, retry mechanisms, circuit breakers
**Phase 4 (Observability - B2-006):** Correlation IDs for distributed tracing
"""

from .circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpenError,
    CircuitState,
    with_circuit_breaker,
)
from .error_handling import RetryableError, retry_with_backoff
from .rate_limiter import RateLimiter
from .tracing import (
    clear_correlation_id,
    get_correlation_context,
    get_correlation_id,
    set_correlation_id,
    with_correlation_id,
)

__all__ = [
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitBreakerOpenError",
    "CircuitState",
    "RateLimiter",
    "RetryableError",
    "clear_correlation_id",
    "get_correlation_context",
    "get_correlation_id",
    "retry_with_backoff",
    "set_correlation_id",
    "with_circuit_breaker",
    "with_correlation_id",
]
