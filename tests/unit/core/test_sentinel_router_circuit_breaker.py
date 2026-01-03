# tests/unit/core/test_sentinel_router_circuit_breaker.py
"""
Integration tests for SentinelRouter circuit breaker behavior

Phase 4 (Resilience - B2-012/RES-01): Test circuit breaker integration with
SentinelRouter to verify cascading failure prevention, recovery flows, and
graceful degradation.

Phase 7 (Testing): Addresses Phase 7 audit finding: "No circuit breaker behavior tests"
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, Mock, patch, MagicMock
from datetime import datetime, timezone
from azure.core.exceptions import AzureError, ServiceRequestError, HttpResponseError

from src.core.sentinel_router import SentinelRouter, TableConfig
from src.utils.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitBreakerOpenError, CircuitState


class TestSentinelRouterCircuitBreakerIntegration:
    """Test circuit breaker integration with SentinelRouter
    
    Phase 4 (B2-012): Verify circuit breaker prevents cascading failures
    during Azure Sentinel outages or persistent errors.
    """
    
    @pytest.fixture
    def mock_logs_client(self):
        """Mock Azure Logs Ingestion client
        
        Note: upload() is called synchronously via run_in_executor,
        so we use regular Mock (not AsyncMock).
        """
        client = Mock()
        client.upload = Mock()  # Synchronous mock - called via run_in_executor
        return client
    
    @pytest.fixture
    def sentinel_router(self, mock_logs_client):
        """Create SentinelRouter with mocked client and test-friendly circuit breaker"""
        router = SentinelRouter(
            dcr_endpoint='https://test-dcr.azure.com',
            rule_id='test-rule-id',
            stream_name='Custom-TestStream',
            max_retries=3,
            batch_timeout=30,
            logs_client=mock_logs_client
        )
        
        # Override circuit breaker with test-friendly config
        # (lower min_calls_before_open for faster testing)
        test_circuit_config = CircuitBreakerConfig(
            failure_threshold=5,          # Open after 5 failures
            recovery_timeout=60,          # Attempt recovery after 60s
            success_threshold=2,          # Need 2 successes to close
            operation_timeout=30,         # 30s timeout
            min_calls_before_open=1       # Allow opening after just 1 call (for testing)
        )
        router._circuit_breaker = CircuitBreaker("azure-sentinel", test_circuit_config)
        
        # Register test table configuration
        router.table_configs = {
            'TestTable': TableConfig(
                table_name='TestTable',
                schema_version='1.0',
                required_fields=['timestamp', 'message'],
                retention_days=90,
                transform_map={},
                data_type_map={}
            )
        }
        return router
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_opens_on_repeated_azure_failures(self, sentinel_router):
        """Circuit breaker opens after repeated Azure Sentinel failures
        
        Phase 4 (RES-01): Verifies circuit breaker prevents further attempts
        after failure threshold is exceeded.
        """
        # Configure mock to fail consistently
        sentinel_router.logs_client.upload.side_effect = AzureError("Sentinel unavailable")
        
        # Prepare test data
        
        logs = [{'timestamp': '2024-01-01T00:00:00Z', 'message': f'test-log-{i}'} for i in range(10)]
        
        # Initial state: circuit should be CLOSED
        assert sentinel_router._circuit_breaker.state == CircuitState.CLOSED
        
        # Route logs multiple times to exceed failure threshold (default: 5)
        for attempt in range(6):
            results = await sentinel_router.route_logs('TestTable', logs)
            
            # First 5 attempts should try Azure (and fail)
            if attempt < 5:
                assert results['failed'] == len(logs)
                assert results['processed'] == 0
            else:
                # 6th attempt: circuit should be OPEN, immediate rejection
                assert results['failed'] == len(logs)
                # Circuit breaker should have transitioned to OPEN
                break
        
        # Verify circuit breaker is now OPEN
        assert sentinel_router._circuit_breaker.state == CircuitState.OPEN
        assert sentinel_router._circuit_breaker.opened_at is not None
        
        # Next attempt should fail immediately without calling Azure
        sentinel_router.logs_client.upload.reset_mock()
        results = await sentinel_router.route_logs('TestTable', logs)
        
        # Should fail without Azure call
        assert results['failed'] == len(logs)
        # Verify NO Azure calls were made (circuit breaker blocked)
        assert sentinel_router.logs_client.upload.call_count == 0
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_half_open_recovery(self, sentinel_router):
        """Circuit breaker transitions to half-open and recovers
        
        Phase 4 (RES-01): Verifies circuit breaker can recover after temporary outage.
        """
        # Step 1: Open the circuit with failures
        sentinel_router.logs_client.upload.side_effect = ServiceRequestError("Network failure")
        
        
        logs = [{'timestamp': '2024-01-01T00:00:00Z', 'message': 'test-log'}]
        
        # Trigger failures to open circuit (5 failures required)
        for _ in range(5):
            await sentinel_router.route_logs('TestTable', logs)
        
        assert sentinel_router._circuit_breaker.state == CircuitState.OPEN
        
        # Step 2: Wait for recovery timeout (circuit breaker config: 60s default)
        # Manually transition to HALF_OPEN for testing (simulate timeout)
        sentinel_router._circuit_breaker._state = CircuitState.HALF_OPEN
        sentinel_router._circuit_breaker.success_count = 0
        
        # Step 3: Fix the Azure client (simulate service recovery)
        sentinel_router.logs_client.upload.side_effect = None
        sentinel_router.logs_client.upload.return_value = None
        
        # Step 4: Successful calls in HALF_OPEN should close the circuit
        # Circuit breaker requires 2 successful calls (success_threshold=2)
        for _ in range(2):
            results = await sentinel_router.route_logs('TestTable', logs)
            assert results['processed'] == len(logs)
            assert results['failed'] == 0
        
        # Circuit should now be CLOSED (recovered)
        assert sentinel_router._circuit_breaker.state == CircuitState.CLOSED
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_fails_back_to_open_in_half_open(self, sentinel_router):
        """Circuit breaker returns to OPEN if failures occur in HALF_OPEN
        
        Phase 4 (RES-01): Verifies circuit breaker doesn't prematurely close
        if service is still failing.
        """
        # Open the circuit
        sentinel_router.logs_client.upload.side_effect = AzureError("Sentinel down")
        
        
        logs = [{'timestamp': '2024-01-01T00:00:00Z', 'message': 'test-log'}]
        
        for _ in range(5):
            await sentinel_router.route_logs('TestTable', logs)
        
        assert sentinel_router._circuit_breaker.state == CircuitState.OPEN
        
        # Transition to HALF_OPEN
        sentinel_router._circuit_breaker._state = CircuitState.HALF_OPEN
        sentinel_router._circuit_breaker.success_count = 0
        
        # First test call in HALF_OPEN still fails (service not recovered)
        # Should immediately return to OPEN
        results = await sentinel_router.route_logs('TestTable', logs)
        assert results['failed'] == len(logs)
        
        # Circuit should be back to OPEN (not CLOSED)
        assert sentinel_router._circuit_breaker.state == CircuitState.OPEN
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_metrics_tracked(self, sentinel_router):
        """Circuit breaker metrics are tracked and reported
        
        Phase 4 (Observability): Verifies circuit breaker state is visible
        in health status and metrics.
        """
        # Get initial health status
        health = sentinel_router.get_health_status()
        
        # Should include circuit breaker metrics
        assert 'circuit_breaker' in health
        assert 'state' in health['circuit_breaker']
        assert health['circuit_breaker']['state'] == 'closed'
        
        # Open the circuit
        sentinel_router.logs_client.upload.side_effect = AzureError("Sentinel error")
        
        
        logs = [{'timestamp': '2024-01-01T00:00:00Z', 'message': 'test-log'}]
        for _ in range(5):
            await sentinel_router.route_logs('TestTable', logs)
        
        # Check health status after circuit opens
        health = sentinel_router.get_health_status()
        
        assert health['circuit_breaker']['state'] == 'open'
        assert health['circuit_breaker']['failure_count'] >= 5
        assert health['circuit_breaker']['opened_at'] is not None
        assert 'total_calls' in health['circuit_breaker']
        
        # Health should be degraded when circuit is open
        assert health['status'] == 'degraded'
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_timeout_enforcement(self, sentinel_router):
        """Circuit breaker enforces operation timeouts
        
        Phase 4 (RES-01): Verifies slow Azure responses trigger timeout
        and count as failures toward circuit breaker threshold.
        
        Note: This test uses a short timeout configuration and time.sleep
        in a synchronous mock to simulate a slow Azure response.
        """
        import time
        
        # Reconfigure circuit breaker with very short timeout for testing
        short_timeout_config = CircuitBreakerConfig(
            failure_threshold=5,
            recovery_timeout=60,
            success_threshold=2,
            operation_timeout=0.1,  # 100ms timeout for testing
            min_calls_before_open=1
        )
        sentinel_router._circuit_breaker = CircuitBreaker("azure-sentinel", short_timeout_config)
        
        # Configure synchronous mock to sleep (simulate slow response)
        def slow_upload(*args, **kwargs):
            time.sleep(0.5)  # 500ms - longer than 100ms timeout
            return None
        
        sentinel_router.logs_client.upload = slow_upload
        
        logs = [{'timestamp': '2024-01-01T00:00:00Z', 'message': 'test-log'}]
        
        # First call should timeout (circuit breaker has operation_timeout=0.1s)
        results = await sentinel_router.route_logs('TestTable', logs)
        
        # Should fail due to timeout
        assert results['failed'] == len(logs)
        assert results['processed'] == 0
        
        # Circuit breaker should count this as a failure
        assert sentinel_router._circuit_breaker.failure_count >= 1
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_with_different_error_types(self, sentinel_router):
        """Circuit breaker handles different Azure error types
        
        Phase 4 (RES-01): Verifies all Azure error types contribute to
        circuit breaker failure count.
        """
        
        logs = [{'timestamp': '2024-01-01T00:00:00Z', 'message': 'test-log'}]
                # Test different error types
        error_types = [
            AzureError("Generic Azure error"),
            ServiceRequestError("Network failure"),
            HttpResponseError("HTTP 503 Service Unavailable"),
            Exception("Unexpected error"),
        ]
        
        for error in error_types:
            sentinel_router.logs_client.upload.side_effect = error
            results = await sentinel_router.route_logs('TestTable', logs)
            assert results['failed'] == len(logs)
        
        # All errors should contribute to failure count
        assert sentinel_router._circuit_breaker.failure_count >= len(error_types)
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_reset_on_success(self, sentinel_router):
        """Circuit breaker resets failure count on successful calls
        
        Phase 4 (RES-01): Verifies transient failures don't accumulate
        if interspersed with successes.
        """
        sentinel_router.logs_client.upload.return_value = None
        
        
        logs = [{'timestamp': '2024-01-01T00:00:00Z', 'message': 'test-log'}]
                # Successful call
        results = await sentinel_router.route_logs('TestTable', logs)
        assert results['processed'] == len(logs)
        assert sentinel_router._circuit_breaker.state == CircuitState.CLOSED
        
        # Introduce 2 failures
        sentinel_router.logs_client.upload.side_effect = AzureError("Transient error")
        for _ in range(2):
            await sentinel_router.route_logs('TestTable', logs)
        
        failure_count_after_failures = sentinel_router._circuit_breaker.failure_count
        assert failure_count_after_failures == 2
        
        # Successful call should reset failure count
        sentinel_router.logs_client.upload.side_effect = None
        sentinel_router.logs_client.upload.return_value = None
        results = await sentinel_router.route_logs('TestTable', logs)
        assert results['processed'] == len(logs)
        
        # Failure count should be reset to 0 in CLOSED state
        assert sentinel_router._circuit_breaker.failure_count == 0


class TestCircuitBreakerFailedBatchIntegration:
    """Test circuit breaker interaction with failed batch handling
    
    Phase 4 (B2-012 + B2-005): Verify failed batch storage works correctly
    when circuit breaker is open.
    """
    
    @pytest.fixture
    def sentinel_router_with_storage(self):
        """Create SentinelRouter with local failed batch storage"""
        mock_client = Mock()
        mock_client.upload = Mock()  # Synchronous mock - called via run_in_executor
        
        router = SentinelRouter(
            dcr_endpoint='https://test-dcr.azure.com',
            rule_id='test-rule-id',
            stream_name='Custom-TestStream',
            max_retries=3,
            batch_timeout=30,
            logs_client=mock_client
        )
        
        # Override circuit breaker with test-friendly config
        test_circuit_config = CircuitBreakerConfig(
            failure_threshold=5,
            recovery_timeout=60,
            success_threshold=2,
            operation_timeout=30,
            min_calls_before_open=1  # Allow opening after just 1 call
        )
        router._circuit_breaker = CircuitBreaker("azure-sentinel", test_circuit_config)
        
        # Configure local storage (no Azure Blob)
        # Use setattr to bypass type checking for test configuration
        setattr(router, 'blob_container_client', None)
        setattr(router, 'local_failed_batch_dir', 'failed_batches')
        
        # Register test table configuration
        router.table_configs = {
            'TestTable': TableConfig(
                table_name='TestTable',
                schema_version='1.0',
                required_fields=['timestamp', 'message'],
                retention_days=90,
                transform_map={},
                data_type_map={}
            )
        }
        
        return router
    
    @pytest.mark.asyncio
    async def test_failed_batches_stored_when_circuit_open(self, sentinel_router_with_storage, tmp_path):
        """Failed batches are stored when circuit breaker is OPEN
        
        Phase 4 (B2-012 + B2-005): Verifies failed batch visibility even
        when circuit breaker prevents Azure calls.
        """
        router = sentinel_router_with_storage
        router.local_failed_batch_dir = str(tmp_path / 'failed_batches')
        
        # Open the circuit
        router.logs_client.upload.side_effect = AzureError("Sentinel down")
        
        
        logs = [{'timestamp': '2024-01-01T00:00:00Z', 'message': f'test-log-{i}'} for i in range(10)]
                # Trigger failures to open circuit
        for _ in range(5):
            await router.route_logs('TestTable', logs)
        
        assert router._circuit_breaker.state == CircuitState.OPEN
        
        # Next attempt with circuit OPEN should still store failed batch
        results = await router.route_logs('TestTable', logs)
        
        assert results['failed'] == len(logs)
        
        # Verify failed batch metrics tracked
        failed_batch_metrics = router.get_failed_batch_metrics()
        assert failed_batch_metrics['total_failed_batches'] > 0
        
        # Should track circuit breaker as failure reason
        assert 'circuit_breaker_open' in failed_batch_metrics['failure_reasons']


class TestCircuitBreakerObservability:
    """Test circuit breaker observability and metrics
    
    Phase 4 (B2-012 + Observability): Verify circuit breaker state is
    visible through monitoring and health endpoints.
    """
    
    @pytest.fixture
    def sentinel_router(self):
        """Create SentinelRouter with mocked client"""
        mock_client = Mock()
        mock_client.upload = Mock()  # Synchronous mock - called via run_in_executor
        
        router = SentinelRouter(
            dcr_endpoint='https://test-dcr.azure.com',
            rule_id='test-rule-id',
            stream_name='Custom-TestStream',
            max_retries=3,
            batch_timeout=30,
            logs_client=mock_client
        )
        
        # Override circuit breaker with test-friendly config
        test_circuit_config = CircuitBreakerConfig(
            failure_threshold=5,
            recovery_timeout=60,
            success_threshold=2,
            operation_timeout=30,
            min_calls_before_open=1  # Allow opening after just 1 call
        )
        router._circuit_breaker = CircuitBreaker("azure-sentinel", test_circuit_config)
        
        # Register test table configuration
        router.table_configs = {
            'TestTable': TableConfig(
                table_name='TestTable',
                schema_version='1.0',
                required_fields=['timestamp', 'message'],
                retention_days=90,
                transform_map={},
                data_type_map={}
            )
        }
        
        return router
    
    def test_circuit_breaker_state_in_health_status(self, sentinel_router):
        """Health status includes circuit breaker state
        
        Phase 4 (Observability): Enables monitoring systems to track
        circuit breaker state changes.
        """
        health = sentinel_router.get_health_status()
        
        # Circuit breaker metrics should be present
        assert 'circuit_breaker' in health
        cb_metrics = health['circuit_breaker']
        
        # Required metrics for observability
        assert 'state' in cb_metrics
        assert 'failure_count' in cb_metrics
        assert 'total_calls' in cb_metrics
        assert 'opened_at' in cb_metrics
        
        # Initial state should be CLOSED
        assert cb_metrics['state'] == 'closed'
        assert cb_metrics['failure_count'] == 0
        assert cb_metrics['opened_at'] is None
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_transition_logged(self, sentinel_router, caplog):
        """Circuit breaker state transitions are logged
        
        Phase 4 (Observability): Enables audit trail of circuit breaker
        state changes for incident analysis.
        """
        import logging
        caplog.set_level(logging.ERROR)
        
        # Open the circuit
        sentinel_router.logs_client.upload.side_effect = AzureError("Sentinel error")
        
        
        logs = [{'timestamp': '2024-01-01T00:00:00Z', 'message': 'test-log'}]
        for _ in range(5):
            await sentinel_router.route_logs('TestTable', logs)
        
        # Should have logged circuit breaker state transition
        # Expected log: "Circuit breaker 'azure-sentinel': CLOSED → OPEN"
        assert any('closed' in record.message.lower() and 'open' in record.message.lower() 
                   for record in caplog.records)
    
    @pytest.mark.asyncio
    async def test_health_degraded_when_circuit_open(self, sentinel_router):
        """Health status shows degraded when circuit is OPEN
        
        Phase 4 (Observability): Enables alerting on circuit breaker state.
        """
        # Open the circuit
        sentinel_router.logs_client.upload.side_effect = AzureError("Sentinel error")
        
        
        logs = [{'timestamp': '2024-01-01T00:00:00Z', 'message': 'test-log'}]
        for _ in range(5):
            await sentinel_router.route_logs('TestTable', logs)
        
        health = sentinel_router.get_health_status()
        
        # Health should indicate degradation
        assert health['status'] == 'degraded'
        assert health['circuit_breaker']['state'] == 'open'
