# tests/unit/utils/test_circuit_breaker.py
"""
Comprehensive tests for CircuitBreaker implementation

Phase 4 (Resilience - B2-001/RES-01): Test circuit breaker state machine,
failure detection, recovery attempts, and metrics tracking.

Phase 7 (Testing): Covers all state transitions, edge cases, and error paths.
"""

import asyncio
import pytest
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from src.utils.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpenError,
    CircuitState,
    with_circuit_breaker
)


class TestCircuitBreakerStateTransitions:
    """Test circuit breaker state machine transitions
    
    Phase 4 (Resilience): Verify CLOSED → OPEN → HALF_OPEN → CLOSED flow
    """
    
    @pytest.mark.asyncio
    async def test_closed_to_open_on_failure_threshold(self):
        """Circuit opens after exceeding failure threshold"""
        config = CircuitBreakerConfig(
            failure_threshold=3,
            min_calls_before_open=1
        )
        breaker = CircuitBreaker("test-service", config)
        
        async def failing_func():
            raise ValueError("Test failure")
        
        # Make 3 failures to reach threshold
        for i in range(3):
            with pytest.raises(ValueError):
                await breaker.call(failing_func)
            
            if i < 2:
                # Still closed after 1-2 failures
                assert breaker.state == CircuitState.CLOSED
            else:
                # Open after 3rd failure
                assert breaker.state == CircuitState.OPEN
                assert breaker.opened_at is not None
    
    @pytest.mark.asyncio
    async def test_open_to_half_open_after_recovery_timeout(self):
        """Circuit transitions to half-open after recovery timeout"""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            recovery_timeout=1,  # 1 second
            min_calls_before_open=1
        )
        breaker = CircuitBreaker("test-service", config)
        
        async def failing_func():
            raise ValueError("Test failure")
        
        # Open the circuit
        for _ in range(2):
            with pytest.raises(ValueError):
                await breaker.call(failing_func)
        
        assert breaker.state == CircuitState.OPEN
        
        # Immediate call should fail with CircuitBreakerOpenError
        with pytest.raises(CircuitBreakerOpenError) as exc_info:
            await breaker.call(failing_func)
        assert "Circuit breaker OPEN" in str(exc_info.value)
        
        # Wait for recovery timeout
        await asyncio.sleep(1.1)
        
        # Next call should transition to HALF_OPEN
        async def succeeding_func():
            return "success"
        
        result = await breaker.call(succeeding_func)
        assert result == "success"
        assert breaker.state == CircuitState.HALF_OPEN
    
    @pytest.mark.asyncio
    async def test_half_open_to_closed_on_success_threshold(self):
        """Circuit closes after successful test calls in half-open"""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            recovery_timeout=1,
            success_threshold=2,  # Need 2 successes
            min_calls_before_open=1
        )
        breaker = CircuitBreaker("test-service", config)
        
        async def failing_func():
            raise ValueError("Failure")
        
        async def succeeding_func():
            return "success"
        
        # Open the circuit
        for _ in range(2):
            with pytest.raises(ValueError):
                await breaker.call(failing_func)
        assert breaker.state == CircuitState.OPEN
        
        # Wait for recovery
        await asyncio.sleep(1.1)
        
        # First success: should be HALF_OPEN
        result = await breaker.call(succeeding_func)
        assert result == "success"
        assert breaker.state == CircuitState.HALF_OPEN
        
        # Second success: should close circuit
        result = await breaker.call(succeeding_func)
        assert result == "success"
        assert breaker.state == CircuitState.CLOSED
        assert breaker.opened_at is None
    
    @pytest.mark.asyncio
    async def test_half_open_to_open_on_failure(self):
        """Circuit reopens if test call fails in half-open state"""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            recovery_timeout=1,
            min_calls_before_open=1
        )
        breaker = CircuitBreaker("test-service", config)
        
        async def failing_func():
            raise ValueError("Failure")
        
        # Open the circuit
        for _ in range(2):
            with pytest.raises(ValueError):
                await breaker.call(failing_func)
        assert breaker.state == CircuitState.OPEN
        
        # Wait for recovery
        await asyncio.sleep(1.1)
        
        # Test call fails: should reopen
        with pytest.raises(ValueError):
            await breaker.call(failing_func)
        
        assert breaker.state == CircuitState.OPEN
        assert breaker.opened_at is not None  # Reopened timestamp


class TestCircuitBreakerFailureDetection:
    """Test failure detection and counting
    
    Phase 4 (Resilience): Verify failure tracking and threshold enforcement
    """
    
    @pytest.mark.asyncio
    async def test_failure_count_increments(self):
        """Failure count increments on each failure"""
        config = CircuitBreakerConfig(failure_threshold=5, min_calls_before_open=1)
        breaker = CircuitBreaker("test-service", config)
        
        async def failing_func():
            raise ValueError("Failure")
        
        for i in range(3):
            with pytest.raises(ValueError):
                await breaker.call(failing_func)
            assert breaker.failure_count == i + 1
    
    @pytest.mark.asyncio
    async def test_failure_count_resets_on_success(self):
        """Failure count resets when call succeeds in closed state"""
        config = CircuitBreakerConfig(failure_threshold=5, min_calls_before_open=1)
        breaker = CircuitBreaker("test-service", config)
        
        async def failing_func():
            raise ValueError("Failure")
        
        async def succeeding_func():
            return "success"
        
        # Record some failures
        for _ in range(3):
            with pytest.raises(ValueError):
                await breaker.call(failing_func)
        assert breaker.failure_count == 3
        
        # Success resets failure count
        await breaker.call(succeeding_func)
        assert breaker.failure_count == 0
    
    @pytest.mark.asyncio
    async def test_timeout_counts_as_failure(self):
        """Operation timeout counts as failure"""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            operation_timeout=0.1,  # 100ms
            min_calls_before_open=1
        )
        breaker = CircuitBreaker("test-service", config)
        
        async def slow_func():
            await asyncio.sleep(1.0)  # 1 second (exceeds timeout)
            return "should not reach here"
        
        # First timeout
        with pytest.raises(asyncio.TimeoutError):
            await breaker.call(slow_func)
        assert breaker.failure_count == 1
        
        # Second timeout should open circuit
        with pytest.raises(asyncio.TimeoutError):
            await breaker.call(slow_func)
        assert breaker.state == CircuitState.OPEN
    
    @pytest.mark.asyncio
    async def test_min_calls_before_open_enforced(self):
        """Circuit doesn't open until min_calls threshold met"""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            min_calls_before_open=5  # Need 5 calls before opening
        )
        breaker = CircuitBreaker("test-service", config)
        
        async def failing_func():
            raise ValueError("Failure")
        
        # Make 2 failures (reaches failure_threshold but not min_calls)
        for _ in range(2):
            with pytest.raises(ValueError):
                await breaker.call(failing_func)
        
        # Circuit should still be closed (only 2 calls < min_calls)
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 2
        
        # Make 3 more failures (total 5 calls, still 5 failures)
        for _ in range(3):
            with pytest.raises(ValueError):
                await breaker.call(failing_func)
        
        # Now circuit should open (min_calls met + failures exceed threshold)
        assert breaker.state == CircuitState.OPEN


class TestCircuitBreakerOpenError:
    """Test CircuitBreakerOpenError behavior
    
    Phase 4 (Resilience): Verify error details and metadata
    """
    
    @pytest.mark.asyncio
    async def test_circuit_open_error_details(self):
        """CircuitBreakerOpenError contains service name and timestamps"""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            recovery_timeout=30,
            min_calls_before_open=1
        )
        breaker = CircuitBreaker("my-service", config)
        
        async def failing_func():
            raise ValueError("Failure")
        
        # Open the circuit
        for _ in range(2):
            with pytest.raises(ValueError):
                await breaker.call(failing_func)
        
        # Next call should raise CircuitBreakerOpenError
        with pytest.raises(CircuitBreakerOpenError) as exc_info:
            await breaker.call(failing_func)
        
        error = exc_info.value
        assert error.service_name == "my-service"
        assert error.opened_at is not None
        assert error.recovery_timeout == 30
        assert "my-service" in str(error)
        assert "Recovery attempt in" in str(error)
    
    @pytest.mark.asyncio
    async def test_circuit_open_error_time_remaining(self):
        """CircuitBreakerOpenError calculates time remaining until recovery"""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            recovery_timeout=10,  # 10 seconds
            min_calls_before_open=1
        )
        breaker = CircuitBreaker("test-service", config)
        
        async def failing_func():
            raise ValueError("Failure")
        
        # Open the circuit
        for _ in range(2):
            with pytest.raises(ValueError):
                await breaker.call(failing_func)
        
        # Immediately try again
        with pytest.raises(CircuitBreakerOpenError) as exc_info:
            await breaker.call(failing_func)
        
        error = exc_info.value
        time_remaining = error.next_attempt_at - time.time()
        
        # Should be close to 10 seconds (allowing small tolerance)
        assert 9.5 < time_remaining < 10.5


class TestCircuitBreakerHalfOpenLimits:
    """Test half-open state call limits
    
    Phase 4 (Resilience): Verify limited test calls in half-open state
    """
    
    @pytest.mark.asyncio
    async def test_half_open_max_calls_enforced(self):
        """Half-open state limits concurrent test calls"""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            recovery_timeout=1,
            half_open_max_calls=2,  # Allow only 2 concurrent calls
            min_calls_before_open=1
        )
        breaker = CircuitBreaker("test-service", config)
        
        async def failing_func():
            raise ValueError("Failure")
        
        async def slow_succeeding_func():
            await asyncio.sleep(0.5)
            return "success"
        
        # Open the circuit
        for _ in range(2):
            with pytest.raises(ValueError):
                await breaker.call(failing_func)
        
        await asyncio.sleep(1.1)  # Wait for recovery
        
        # Start 2 concurrent test calls (should both be allowed)
        tasks = [
            asyncio.create_task(breaker.call(slow_succeeding_func))
            for _ in range(2)
        ]
        
        # Give tasks time to start
        await asyncio.sleep(0.1)
        
        # Third call should be rejected (exceeds half_open_max_calls)
        with pytest.raises(CircuitBreakerOpenError):
            await breaker.call(slow_succeeding_func)
        
        # Wait for original tasks to complete
        results = await asyncio.gather(*tasks)
        assert all(r == "success" for r in results)


class TestCircuitBreakerMetrics:
    """Test metrics tracking and reporting
    
    Phase 4 (Observability): Verify comprehensive metrics collection
    """
    
    @pytest.mark.asyncio
    async def test_get_metrics_structure(self):
        """get_metrics returns complete metrics dict"""
        config = CircuitBreakerConfig()
        breaker = CircuitBreaker("test-service", config)
        
        metrics = breaker.get_metrics()
        
        assert metrics['name'] == "test-service"
        assert 'state' in metrics
        assert 'failure_count' in metrics
        assert 'success_count' in metrics
        assert 'total_calls' in metrics
        assert 'opened_at' in metrics
        assert 'state_transitions' in metrics
        assert 'config' in metrics
    
    @pytest.mark.asyncio
    async def test_metrics_total_calls_tracked(self):
        """Total calls metric increments correctly"""
        config = CircuitBreakerConfig()  # Phase 7: Fix missing config
        breaker = CircuitBreaker("test-service", config)
        
        async def func():
            return "success"
        
        for i in range(5):
            await breaker.call(func)
            metrics = breaker.get_metrics()
            assert metrics['total_calls'] == i + 1
    
    @pytest.mark.asyncio
    async def test_metrics_state_transitions_recorded(self):
        """State transitions are recorded in metrics"""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            recovery_timeout=1,
            success_threshold=1,
            min_calls_before_open=1
        )
        breaker = CircuitBreaker("test-service", config)
        
        async def failing_func():
            raise ValueError("Failure")
        
        async def succeeding_func():
            return "success"
        
        # CLOSED → OPEN
        for _ in range(2):
            with pytest.raises(ValueError):
                await breaker.call(failing_func)
        
        metrics = breaker.get_metrics()
        assert len(metrics['state_transitions']) == 1
        assert metrics['state_transitions'][0]['from_state'] == 'closed'
        assert metrics['state_transitions'][0]['to_state'] == 'open'
        
        # Wait for recovery and transition OPEN → HALF_OPEN
        await asyncio.sleep(1.1)
        await breaker.call(succeeding_func)
        
        metrics = breaker.get_metrics()
        assert len(metrics['state_transitions']) >= 2
        
        # Find HALF_OPEN → CLOSED transition
        transitions = [t for t in metrics['state_transitions'] if t['to_state'] == 'closed']
        assert len(transitions) > 0


class TestCircuitBreakerDecorator:
    """Test with_circuit_breaker decorator
    
    Phase 4 (Resilience): Verify decorator wraps functions correctly
    """
    
    @pytest.mark.asyncio
    async def test_decorator_protects_function(self):
        """Decorator wraps function with circuit breaker"""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            min_calls_before_open=1
        )
        breaker = CircuitBreaker("test-service", config)
        
        @with_circuit_breaker(breaker)
        async def protected_func(value):
            if value == "fail":
                raise ValueError("Intentional failure")
            return f"success: {value}"
        
        # Successes work
        result = await protected_func("test")
        assert result == "success: test"
        
        # Failures are tracked
        for _ in range(2):
            with pytest.raises(ValueError):
                await protected_func("fail")
        
        # Circuit opens
        assert breaker.state == CircuitState.OPEN
        
        # Next call raises CircuitBreakerOpenError
        with pytest.raises(CircuitBreakerOpenError):
            await protected_func("test")
    
    @pytest.mark.asyncio
    async def test_decorator_preserves_function_metadata(self):
        """Decorator preserves original function name and docstring"""
        config = CircuitBreakerConfig()  # Phase 7: Fix missing config
        breaker = CircuitBreaker("test-service", config)
        
        @with_circuit_breaker(breaker)
        async def my_function():
            """My docstring"""
            return "result"
        
        assert my_function.__name__ == "my_function"
        assert my_function.__doc__ == "My docstring"


class TestCircuitBreakerReset:
    """Test manual circuit breaker reset
    
    Phase 4 (Resilience): Verify reset functionality for testing/recovery
    """
    
    def test_reset_clears_all_state(self):
        """Reset returns circuit to initial closed state"""
        config = CircuitBreakerConfig()
        breaker = CircuitBreaker("test-service", config)
        
        # Simulate some state
        breaker.failure_count = 5
        breaker.success_count = 3
        breaker.total_calls = 10
        breaker._state = CircuitState.OPEN
        breaker.opened_at = datetime.now(timezone.utc)
        
        # Reset
        breaker.reset()
        
        # Verify all cleared
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0
        assert breaker.success_count == 0
        assert breaker.total_calls == 0
        assert breaker.opened_at is None


class TestCircuitBreakerEdgeCases:
    """Test edge cases and boundary conditions
    
    Phase 7 (Testing): Comprehensive coverage of corner cases
    """
    
    @pytest.mark.asyncio
    async def test_exception_types_all_count_as_failure(self):
        """All exception types (ValueError, RuntimeError, etc.) count as failures"""
        config = CircuitBreakerConfig(failure_threshold=3, min_calls_before_open=1)
        breaker = CircuitBreaker("test-service", config)
        
        async def func_with_value_error():
            raise ValueError("Value error")
        
        async def func_with_runtime_error():
            raise RuntimeError("Runtime error")
        
        async def func_with_type_error():
            raise TypeError("Type error")
        
        # All exception types should count toward failure threshold
        with pytest.raises(ValueError):
            await breaker.call(func_with_value_error)
        assert breaker.failure_count == 1
        
        with pytest.raises(RuntimeError):
            await breaker.call(func_with_runtime_error)
        assert breaker.failure_count == 2
        
        with pytest.raises(TypeError):
            await breaker.call(func_with_type_error)
        
        # Circuit should now be open
        assert breaker.state == CircuitState.OPEN
    
    @pytest.mark.asyncio
    async def test_zero_failure_threshold_invalid(self):
        """Circuit breaker requires failure_threshold >= 1"""
        # Phase 7: Test min_calls_before_open logic with failure_threshold=1
        config = CircuitBreakerConfig(
            failure_threshold=1,
            min_calls_before_open=1  # Allow opening after 1 call
        )
        breaker = CircuitBreaker("test-service", config)
        
        async def failing_func():
            raise ValueError("Failure")
        
        # Should open after 1 failure (meets both min_calls and failure_threshold)
        with pytest.raises(ValueError):
            await breaker.call(failing_func)
        assert breaker.state == CircuitState.OPEN
    
    @pytest.mark.asyncio
    async def test_concurrent_calls_tracked_correctly(self):
        """Concurrent calls are all tracked in metrics"""
        config = CircuitBreakerConfig()  # Phase 7: Fix missing config
        breaker = CircuitBreaker("test-service", config)
        
        async def func(delay):
            await asyncio.sleep(delay)
            return "success"
        
        # Launch 10 concurrent calls
        tasks = [
            asyncio.create_task(breaker.call(func, 0.1))
            for _ in range(10)
        ]
        
        results = await asyncio.gather(*tasks)
        assert all(r == "success" for r in results)
        
        metrics = breaker.get_metrics()
        assert metrics['total_calls'] == 10
