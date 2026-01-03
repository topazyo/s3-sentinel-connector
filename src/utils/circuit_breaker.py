# src/utils/circuit_breaker.py
"""
Circuit Breaker Pattern Implementation

Phase 4 (Resilience - B2-001/RES-01): Prevents cascading failures by
monitoring external service health and short-circuiting requests when
failure thresholds are exceeded.

Based on Phase 4 Audit recommendations (VIBE_PHASE4_RESILIENCE_OBSERVABILITY_REPORT.md)

State Machine:
    CLOSED → OPEN → HALF_OPEN → CLOSED
    
    CLOSED: Normal operation, requests pass through
    OPEN: Failures exceeded threshold, requests immediately fail
    HALF_OPEN: Recovery testing, allow limited requests through
    CLOSED: Recovery successful, resume normal operation
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any, Callable, TypeVar, Awaitable
import functools


logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"         # Normal operation
    OPEN = "open"             # Failure threshold exceeded
    HALF_OPEN = "half_open"   # Testing recovery


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior
    
    Phase 4 (Resilience): Configurable thresholds for different services
    """
    failure_threshold: int = 5          # Failures before opening circuit
    recovery_timeout: int = 60          # Seconds before attempting recovery
    half_open_max_calls: int = 3        # Test calls in half-open state
    success_threshold: int = 2          # Successes needed to close circuit
    min_calls_before_open: int = 10     # Minimum calls before opening circuit
    
    # Phase 6 (Performance): Timeout for operations
    operation_timeout: float = 30.0     # Default operation timeout in seconds


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open and operation is blocked
    
    Phase 4 (Resilience): Explicit error for circuit breaker failures
    """
    def __init__(self, service_name: str, opened_at: datetime, recovery_timeout: int):
        self.service_name = service_name
        self.opened_at = opened_at
        self.recovery_timeout = recovery_timeout
        self.next_attempt_at = opened_at.timestamp() + recovery_timeout
        
        time_remaining = max(0, self.next_attempt_at - time.time())
        super().__init__(
            f"Circuit breaker OPEN for '{service_name}'. "
            f"Opened at {opened_at.isoformat()}. "
            f"Recovery attempt in {time_remaining:.1f}s."
        )


class CircuitBreaker:
    """Circuit breaker for protecting external service calls
    
    Phase 4 (Resilience - B2-001): Implements circuit breaker pattern to prevent
    cascading failures in distributed systems.
    
    Usage:
        ```python
        # Create circuit breaker for Azure Sentinel
        breaker = CircuitBreaker("azure-sentinel", config)
        
        # Wrap service call
        @breaker.call
        async def send_logs(logs):
            return await sentinel_client.upload(logs)
        
        # Use the wrapped function
        try:
            result = await send_logs(my_logs)
        except CircuitBreakerOpenError as e:
            logger.warning(f"Circuit open: {e}")
            # Handle degraded mode
        ```
    
    Attributes:
        name: Service name for logging/metrics
        config: Circuit breaker configuration
        state: Current circuit state (CLOSED, OPEN, HALF_OPEN)
        failure_count: Consecutive failures in current window
        success_count: Consecutive successes in half-open state
        total_calls: Total calls made through circuit
        last_failure_time: Timestamp of most recent failure
        opened_at: Timestamp when circuit opened
    """
    
    def __init__(self, name: str, config: Optional[CircuitBreakerConfig] = None):
        """Initialize circuit breaker
        
        Args:
            name: Service name for identification (e.g., 'azure-sentinel', 's3', 'key-vault')
            config: Circuit breaker configuration (uses defaults if None)
        """
        self.name = name
        self.config = config or CircuitBreakerConfig()
        
        # State machine
        self._state = CircuitState.CLOSED
        self._state_lock = asyncio.Lock()  # Thread-safe state transitions
        
        # Metrics tracking
        self.failure_count = 0
        self.success_count = 0
        self.total_calls = 0
        self.half_open_calls = 0
        
        # Timestamps
        self.last_failure_time: Optional[float] = None
        self.opened_at: Optional[datetime] = None
        
        # Phase 4 (Observability): Track state transitions
        self.state_transitions: list[Dict[str, Any]] = []
        
        logger.info(
            f"Circuit breaker initialized for '{name}': "
            f"failure_threshold={self.config.failure_threshold}, "
            f"recovery_timeout={self.config.recovery_timeout}s"
        )
    
    @property
    def state(self) -> CircuitState:
        """Current circuit state"""
        return self._state
    
    async def call(self, func: Callable[..., Awaitable[Any]], *args, **kwargs) -> Any:
        """Execute function through circuit breaker
        
        Phase 4 (Resilience): Protects external service calls with state machine logic
        
        Args:
            func: Async function to execute
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func
            
        Returns:
            Result from func execution
            
        Raises:
            CircuitBreakerOpenError: Circuit is open, operation blocked
            Any exception from func: If circuit is closed/half-open and func fails
        """
        async with self._state_lock:
            self.total_calls += 1
            current_state = self._state
            
            # Check if circuit should transition from OPEN → HALF_OPEN
            if current_state == CircuitState.OPEN:
                if self._should_attempt_recovery():
                    await self._transition_to_half_open()
                    current_state = CircuitState.HALF_OPEN
                else:
                    # Circuit still open, reject call immediately
                    # Phase 4 (Resilience): opened_at should always be set when state is OPEN
                    opened_at = self.opened_at or datetime.now(timezone.utc)
                    raise CircuitBreakerOpenError(
                        self.name,
                        opened_at,
                        self.config.recovery_timeout
                    )
            
            # HALF_OPEN: Limit concurrent test calls
            if current_state == CircuitState.HALF_OPEN:
                if self.half_open_calls >= self.config.half_open_max_calls:
                    # Too many test calls in flight, reject
                    # Phase 4 (Resilience): opened_at should always be set in HALF_OPEN state
                    opened_at = self.opened_at or datetime.now(timezone.utc)
                    raise CircuitBreakerOpenError(
                        self.name,
                        opened_at,
                        self.config.recovery_timeout
                    )
                self.half_open_calls += 1
        
        # Execute function outside lock to avoid blocking state transitions
        try:
            # Phase 6 (Performance): Apply timeout to prevent hanging
            result = await asyncio.wait_for(
                func(*args, **kwargs),
                timeout=self.config.operation_timeout
            )
            
            # Success: Update state
            await self._on_success()
            return result
            
        except asyncio.TimeoutError as e:
            # Phase 4 (Resilience): Timeout counts as failure
            logger.warning(
                f"Circuit breaker '{self.name}': Operation timeout after {self.config.operation_timeout}s"
            )
            await self._on_failure()
            raise
            
        except Exception as e:
            # Any exception counts as failure
            await self._on_failure()
            raise
        
        finally:
            # Decrement half-open call counter
            if current_state == CircuitState.HALF_OPEN:
                async with self._state_lock:
                    self.half_open_calls -= 1
    
    async def _on_success(self):
        """Handle successful operation
        
        Phase 4 (Resilience): Update state machine on success
        """
        async with self._state_lock:
            if self._state == CircuitState.HALF_OPEN:
                self.success_count += 1
                
                # Phase 4: Sufficient successes in half-open → close circuit
                if self.success_count >= self.config.success_threshold:
                    await self._transition_to_closed()
                else:
                    logger.debug(
                        f"Circuit breaker '{self.name}' half-open: "
                        f"{self.success_count}/{self.config.success_threshold} successes"
                    )
            
            elif self._state == CircuitState.CLOSED:
                # Reset failure count on success
                self.failure_count = 0
    
    async def _on_failure(self):
        """Handle failed operation
        
        Phase 4 (Resilience): Update state machine on failure
        """
        async with self._state_lock:
            self.last_failure_time = time.time()
            
            if self._state == CircuitState.HALF_OPEN:
                # Phase 4: Any failure in half-open → reopen circuit
                logger.warning(
                    f"Circuit breaker '{self.name}': Failure during recovery test, reopening"
                )
                await self._transition_to_open()
                
            elif self._state == CircuitState.CLOSED:
                self.failure_count += 1
                
                # Phase 4: Check if should open circuit (with minimum calls threshold)
                if (self.total_calls >= self.config.min_calls_before_open and
                    self.failure_count >= self.config.failure_threshold):
                    
                    logger.error(
                        f"Circuit breaker '{self.name}': Failure threshold exceeded "
                        f"({self.failure_count}/{self.config.failure_threshold}), opening circuit"
                    )
                    await self._transition_to_open()
                else:
                    logger.warning(
                        f"Circuit breaker '{self.name}': Failure {self.failure_count}/"
                        f"{self.config.failure_threshold} (calls: {self.total_calls})"
                    )
    
    def _should_attempt_recovery(self) -> bool:
        """Check if circuit should attempt recovery from OPEN state
        
        Phase 4 (Resilience): Time-based recovery attempts
        """
        if not self.opened_at:
            return False
        
        time_since_open = time.time() - self.opened_at.timestamp()
        return time_since_open >= self.config.recovery_timeout
    
    async def _transition_to_open(self):
        """Transition circuit to OPEN state
        
        Phase 4 (Resilience): Block all requests until recovery timeout
        """
        old_state = self._state
        self._state = CircuitState.OPEN
        self.opened_at = datetime.now(timezone.utc)
        self.success_count = 0
        self.half_open_calls = 0
        
        # Phase 4 (Observability): Track transition
        self._record_transition(old_state, CircuitState.OPEN)
        
        logger.error(
            f"Circuit breaker '{self.name}': CLOSED → OPEN "
            f"(failures: {self.failure_count}, calls: {self.total_calls})"
        )
    
    async def _transition_to_half_open(self):
        """Transition circuit to HALF_OPEN state
        
        Phase 4 (Resilience): Allow limited test requests
        """
        old_state = self._state
        self._state = CircuitState.HALF_OPEN
        self.failure_count = 0
        self.success_count = 0
        self.half_open_calls = 0
        
        # Phase 4 (Observability): Track transition
        self._record_transition(old_state, CircuitState.HALF_OPEN)
        
        logger.info(
            f"Circuit breaker '{self.name}': OPEN → HALF_OPEN "
            f"(attempting recovery after {self.config.recovery_timeout}s)"
        )
    
    async def _transition_to_closed(self):
        """Transition circuit to CLOSED state
        
        Phase 4 (Resilience): Resume normal operation
        """
        old_state = self._state
        self._state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.opened_at = None
        
        # Phase 4 (Observability): Track transition
        self._record_transition(old_state, CircuitState.CLOSED)
        
        logger.info(
            f"Circuit breaker '{self.name}': HALF_OPEN → CLOSED "
            f"(recovery successful, resuming normal operation)"
        )
    
    def _record_transition(self, from_state: CircuitState, to_state: CircuitState):
        """Record state transition for observability
        
        Phase 4 (Observability): Track state transitions for metrics
        """
        transition = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'from_state': from_state.value,
            'to_state': to_state.value,
            'failure_count': self.failure_count,
            'success_count': self.success_count,
            'total_calls': self.total_calls
        }
        self.state_transitions.append(transition)
        
        # Keep only last 100 transitions (Phase 6: Memory management)
        if len(self.state_transitions) > 100:
            self.state_transitions = self.state_transitions[-100:]
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get circuit breaker metrics for monitoring
        
        Phase 4 (Observability - B2-001): Expose metrics for dashboards
        
        Returns:
            Dict with current metrics:
                - name: Service name
                - state: Current circuit state
                - failure_count: Consecutive failures
                - success_count: Consecutive successes (half-open only)
                - total_calls: Total calls made
                - opened_at: Timestamp when opened (if OPEN)
                - state_transitions: Recent state transitions
        """
        metrics = {
            'name': self.name,
            'state': self._state.value,
            'failure_count': self.failure_count,
            'success_count': self.success_count,
            'total_calls': self.total_calls,
            'half_open_calls': self.half_open_calls,
            'opened_at': self.opened_at.isoformat() if self.opened_at else None,
            'state_transitions': self.state_transitions[-10:],  # Last 10 transitions
            'config': {
                'failure_threshold': self.config.failure_threshold,
                'recovery_timeout': self.config.recovery_timeout,
                'success_threshold': self.config.success_threshold
            }
        }
        return metrics
    
    def reset(self):
        """Reset circuit breaker to initial state
        
        Phase 4 (Resilience): Manual reset for testing or recovery override
        """
        logger.warning(f"Circuit breaker '{self.name}': Manual reset to CLOSED")
        self._state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.total_calls = 0
        self.half_open_calls = 0
        self.last_failure_time = None
        self.opened_at = None


# Type variable for decorator return type
T = TypeVar('T')


def with_circuit_breaker(breaker: CircuitBreaker):
    """Decorator for wrapping functions with circuit breaker protection
    
    Phase 4 (Resilience - B2-001): Convenience decorator for protecting functions
    
    Usage:
        ```python
        sentinel_breaker = CircuitBreaker("azure-sentinel")
        
        @with_circuit_breaker(sentinel_breaker)
        async def upload_logs(logs):
            return await sentinel_client.upload(logs)
        
        # Calls are automatically protected
        try:
            await upload_logs(my_logs)
        except CircuitBreakerOpenError:
            # Handle degraded mode
            pass
        ```
    """
    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            return await breaker.call(func, *args, **kwargs)
        return wrapper
    return decorator
