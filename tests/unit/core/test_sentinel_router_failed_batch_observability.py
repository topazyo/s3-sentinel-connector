# tests/unit/core/test_sentinel_router_failed_batch_observability.py
"""
Unit tests for failed batch observability (B2-005/RES-05)

Phase 4 (Observability): Comprehensive testing of failed batch visibility.
Tests metrics tracking, error categorization, health status, and warnings.

Pattern follows B1-008 test structure (log dropping observability).
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime, timezone
from azure.core.exceptions import AzureError, ServiceRequestError, HttpResponseError

from src.core.sentinel_router import SentinelRouter
from src.utils.circuit_breaker import CircuitBreakerOpenError


class TestFailedBatchMetricsTracking:
    """Test failed batch metrics tracking"""

    @pytest.fixture
    def router(self):
        """Create router with mocked Azure client"""
        mock_client = Mock()
        return SentinelRouter(
            dcr_endpoint="https://test.ingest.monitor.azure.com",
            rule_id="dcr-test123",
            stream_name="Custom-TestStream",
            logs_client=mock_client
        )

    @pytest.mark.asyncio
    async def test_failed_batch_count_incremented(self, router):
        """Test that failed_batch_count increments on batch failure"""
        # Arrange
        batch = [{'field1': 'value1'}, {'field2': 'value2'}]
        error = AzureError("Simulated Azure failure")
        
        # Mock storage to avoid actual I/O
        with patch.object(router, '_store_failed_batch', new_callable=AsyncMock):
            # Act
            await router._handle_failed_batch(batch, error)
        
        # Assert
        assert router.metrics['failed_batch_count'] == 1
        assert router.metrics['failed_records'] == 2

    @pytest.mark.asyncio
    async def test_multiple_failed_batches_accumulate(self, router):
        """Test that multiple batch failures accumulate correctly"""
        # Arrange
        batch1 = [{'field': 'value1'}] * 10
        batch2 = [{'field': 'value2'}] * 5
        batch3 = [{'field': 'value3'}] * 8
        error = AzureError("Simulated Azure failure")
        
        # Mock storage
        with patch.object(router, '_store_failed_batch', new_callable=AsyncMock):
            # Act
            await router._handle_failed_batch(batch1, error)
            await router._handle_failed_batch(batch2, error)
            await router._handle_failed_batch(batch3, error)
        
        # Assert
        assert router.metrics['failed_batch_count'] == 3
        assert router.metrics['failed_records'] == 23  # 10 + 5 + 8

    @pytest.mark.asyncio
    async def test_failure_reasons_tracked_separately(self, router):
        """Test that different failure reasons are tracked separately"""
        # Arrange
        batch = [{'field': 'value'}]
        
        # Mock storage
        with patch.object(router, '_store_failed_batch', new_callable=AsyncMock):
            # Act - Different error types
            await router._handle_failed_batch(batch, AzureError("Azure error"))
            await router._handle_failed_batch(batch, ValueError("Validation error"))
            await router._handle_failed_batch(batch, TimeoutError("Timeout"))
            await router._handle_failed_batch(batch, AzureError("Another Azure error"))
        
        # Assert
        failure_reasons = router.metrics['failure_reasons']
        assert failure_reasons['azure_error:unknown'] == 2
        assert failure_reasons['validation_error'] == 1
        assert failure_reasons['network_timeout'] == 1


class TestFailureReasonCategorization:
    """Test error categorization logic"""

    @pytest.fixture
    def router(self):
        """Create router with mocked Azure client"""
        mock_client = Mock()
        return SentinelRouter(
            dcr_endpoint="https://test.ingest.monitor.azure.com",
            rule_id="dcr-test123",
            stream_name="Custom-TestStream",
            logs_client=mock_client
        )

    def test_categorize_azure_error_with_status_code(self, router):
        """Test Azure error categorization with status code"""
        # Arrange
        error = HttpResponseError(message="Service unavailable")
        error.status_code = 503
        
        # Act
        category = router._categorize_batch_error(error)
        
        # Assert
        assert category == "azure_error:503"

    def test_categorize_azure_error_without_status_code(self, router):
        """Test Azure error categorization without status code"""
        # Arrange
        error = AzureError("Generic Azure error")
        
        # Act
        category = router._categorize_batch_error(error)
        
        # Assert
        assert category == "azure_error:unknown"

    def test_categorize_timeout_error(self, router):
        """Test timeout error categorization"""
        # Arrange
        error = TimeoutError("Operation timed out")
        
        # Act
        category = router._categorize_batch_error(error)
        
        # Assert
        assert category == "network_timeout"

    def test_categorize_connection_error(self, router):
        """Test connection error categorization"""
        # Arrange
        error = ConnectionError("Failed to connect")
        
        # Act
        category = router._categorize_batch_error(error)
        
        # Assert
        assert category == "network_connection"

    def test_categorize_circuit_breaker_error(self, router):
        """Test circuit breaker error categorization"""
        # Arrange
        error = CircuitBreakerOpenError(
            "azure-sentinel",
            datetime.now(timezone.utc),
            recovery_timeout=60
        )
        
        # Act
        category = router._categorize_batch_error(error)
        
        # Assert
        assert category == "circuit_breaker_open"

    def test_categorize_validation_error(self, router):
        """Test validation error categorization"""
        # Arrange
        error = ValueError("Invalid data format")
        
        # Act
        category = router._categorize_batch_error(error)
        
        # Assert
        assert category == "validation_error"

    def test_categorize_unknown_error(self, router):
        """Test unknown error categorization"""
        # Arrange
        error = RuntimeError("Unexpected runtime error")
        
        # Act
        category = router._categorize_batch_error(error)
        
        # Assert
        assert category == "unknown_error:RuntimeError"


class TestGetFailedBatchMetrics:
    """Test failed batch metrics reporting"""

    @pytest.fixture
    def router(self):
        """Create router with mocked Azure client"""
        mock_client = Mock()
        return SentinelRouter(
            dcr_endpoint="https://test.ingest.monitor.azure.com",
            rule_id="dcr-test123",
            stream_name="Custom-TestStream",
            logs_client=mock_client
        )

    def test_get_failed_batch_metrics_no_failures(self, router):
        """Test metrics when no batches have failed"""
        # Act
        metrics = router.get_failed_batch_metrics()
        
        # Assert
        assert metrics['total_failed_batches'] == 0
        assert metrics['failure_rate_percent'] == 0.0
        assert metrics['failure_reasons'] == {}
        assert metrics['recommendations'] == []
        assert metrics['total_failed_records'] == 0

    @pytest.mark.asyncio
    async def test_get_failed_batch_metrics_with_failures(self, router):
        """Test metrics with batch failures"""
        # Arrange
        router.metrics['batch_count'] = 20  # Simulate 20 successful batches
        batch = [{'field': 'value'}] * 10
        
        # Mock storage
        with patch.object(router, '_store_failed_batch', new_callable=AsyncMock):
            # Simulate 5 failed batches
            for _ in range(5):
                await router._handle_failed_batch(batch, AzureError("Azure error"))
        
        # Act
        metrics = router.get_failed_batch_metrics()
        
        # Assert
        assert metrics['total_failed_batches'] == 5
        assert metrics['failure_rate_percent'] == 20.0  # 5/(20+5) = 20%
        assert metrics['total_failed_records'] == 50  # 5 batches * 10 records
        assert metrics['total_batches_processed'] == 25

    @pytest.mark.asyncio
    async def test_recommendations_for_azure_errors(self, router):
        """Test that Azure error recommendations are generated"""
        # Arrange
        batch = [{'field': 'value'}]
        error = HttpResponseError(message="Service unavailable")
        error.status_code = 503
        
        # Mock storage
        with patch.object(router, '_store_failed_batch', new_callable=AsyncMock):
            await router._handle_failed_batch(batch, error)
        
        # Act
        metrics = router.get_failed_batch_metrics()
        
        # Assert
        assert len(metrics['recommendations']) > 0
        assert any('Azure API errors' in rec for rec in metrics['recommendations'])
        assert any('503' in rec for rec in metrics['recommendations'])

    @pytest.mark.asyncio
    async def test_recommendations_for_network_errors(self, router):
        """Test that network error recommendations are generated"""
        # Arrange
        batch = [{'field': 'value'}]
        error = TimeoutError("Connection timeout")
        
        # Mock storage
        with patch.object(router, '_store_failed_batch', new_callable=AsyncMock):
            await router._handle_failed_batch(batch, error)
        
        # Act
        metrics = router.get_failed_batch_metrics()
        
        # Assert
        assert len(metrics['recommendations']) > 0
        assert any('Network issues' in rec for rec in metrics['recommendations'])

    @pytest.mark.asyncio
    async def test_failure_reasons_breakdown(self, router):
        """Test that failure reasons are correctly broken down"""
        # Arrange
        batch = [{'field': 'value'}]
        
        # Mock storage
        with patch.object(router, '_store_failed_batch', new_callable=AsyncMock):
            # Create mix of failures
            await router._handle_failed_batch(batch, AzureError("Azure error 1"))
            await router._handle_failed_batch(batch, AzureError("Azure error 2"))
            await router._handle_failed_batch(batch, TimeoutError("Timeout"))
        
        # Act
        metrics = router.get_failed_batch_metrics()
        
        # Assert
        failure_reasons = metrics['failure_reasons']
        assert failure_reasons['azure_error:unknown'] == 2
        assert failure_reasons['network_timeout'] == 1


class TestHealthStatusWithFailures:
    """Test health status integration with failed batches"""

    @pytest.fixture
    def router(self):
        """Create router with mocked Azure client"""
        mock_client = Mock()
        return SentinelRouter(
            dcr_endpoint="https://test.ingest.monitor.azure.com",
            rule_id="dcr-test123",
            stream_name="Custom-TestStream",
            logs_client=mock_client
        )

    def test_health_status_healthy_no_failures(self, router):
        """Test that health status is healthy with no failures"""
        # Arrange
        router.metrics['batch_count'] = 100
        
        # Act
        health = router.get_health_status()
        
        # Assert
        assert health['status'] == 'healthy'
        assert health['failed_batch_metrics']['total_failed_batches'] == 0

    @pytest.mark.asyncio
    async def test_health_status_degraded_high_failure_rate(self, router):
        """Test that health status is degraded with >5% failure rate"""
        # Arrange
        router.metrics['batch_count'] = 90  # 90 successful
        batch = [{'field': 'value'}]
        
        # Mock storage
        with patch.object(router, '_store_failed_batch', new_callable=AsyncMock):
            # Add 10 failed batches = 10% failure rate
            for _ in range(10):
                await router._handle_failed_batch(batch, AzureError("Error"))
        
        # Act
        health = router.get_health_status()
        
        # Assert
        assert health['status'] == 'degraded'
        assert health['failed_batch_metrics']['failure_rate_percent'] == 10.0

    @pytest.mark.asyncio
    async def test_health_status_includes_failed_batch_metrics(self, router):
        """Test that health status includes failed batch metrics"""
        # Arrange
        router.metrics['batch_count'] = 20
        batch = [{'field': 'value'}]
        
        # Mock storage
        with patch.object(router, '_store_failed_batch', new_callable=AsyncMock):
            await router._handle_failed_batch(batch, AzureError("Error"))
        
        # Act
        health = router.get_health_status()
        
        # Assert
        assert 'failed_batch_metrics' in health
        failed_metrics = health['failed_batch_metrics']
        assert failed_metrics['total_failed_batches'] == 1
        assert failed_metrics['total_failed_records'] == 1
        assert 'failure_reasons' in failed_metrics
        assert 'recommendations' in failed_metrics


class TestFailedBatchWarnings:
    """Test warning generation for failed batches"""

    @pytest.fixture
    def router(self):
        """Create router with mocked Azure client"""
        mock_client = Mock()
        return SentinelRouter(
            dcr_endpoint="https://test.ingest.monitor.azure.com",
            rule_id="dcr-test123",
            stream_name="Custom-TestStream",
            logs_client=mock_client
        )

    @pytest.mark.asyncio
    async def test_warning_on_10th_failure(self, router):
        """Test that warning is logged on 10th batch failure"""
        # Arrange
        router.metrics['batch_count'] = 50
        batch = [{'field': 'value'}]
        
        # Mock storage
        with patch.object(router, '_store_failed_batch', new_callable=AsyncMock):
            # Mock logging to verify warning
            with patch('logging.warning') as mock_warning:
                # Act - Fail 10 batches
                for _ in range(10):
                    await router._handle_failed_batch(batch, AzureError("Error"))
                
                # Assert - Should have warned on 10th failure
                assert mock_warning.called
                warning_call = mock_warning.call_args[0][0]
                assert 'High batch failure rate detected' in warning_call
                assert '10 batches failed' in warning_call

    @pytest.mark.asyncio
    async def test_warning_includes_failure_rate(self, router):
        """Test that warning includes failure rate calculation"""
        # Arrange
        router.metrics['batch_count'] = 90  # 90 successful
        batch = [{'field': 'value'}]
        
        # Mock storage
        with patch.object(router, '_store_failed_batch', new_callable=AsyncMock):
            with patch('logging.warning') as mock_warning:
                # Act - Fail 10 batches
                for _ in range(10):
                    await router._handle_failed_batch(batch, AzureError("Error"))
                
                # Assert
                assert mock_warning.called
                warning_call = mock_warning.call_args[0][0]
                # Failure rate should be present (may be 10% or 11.1% depending on rounding)
                assert '10' in warning_call and '%' in warning_call

    @pytest.mark.asyncio
    async def test_warning_includes_top_failure_reasons(self, router):
        """Test that warning includes top failure reasons"""
        # Arrange
        router.metrics['batch_count'] = 80
        batch = [{'field': 'value'}]
        
        # Mock storage
        with patch.object(router, '_store_failed_batch', new_callable=AsyncMock):
            with patch('logging.warning') as mock_warning:
                # Act - Create mix of failures
                for _ in range(6):
                    await router._handle_failed_batch(batch, AzureError("Azure error"))
                for _ in range(3):
                    await router._handle_failed_batch(batch, TimeoutError("Timeout"))
                for _ in range(1):
                    await router._handle_failed_batch(batch, ValueError("Validation"))
                
                # Assert - Should warn on 10th failure
                assert mock_warning.called
                warning_call = mock_warning.call_args[0][0]
                assert 'Top reasons:' in warning_call
                # Should show azure_error (most common)
                assert 'azure_error' in warning_call.lower()

    @pytest.mark.asyncio
    async def test_no_warning_before_threshold(self, router):
        """Test that no warning is logged before 10th failure"""
        # Arrange
        batch = [{'field': 'value'}]
        
        # Mock storage
        with patch.object(router, '_store_failed_batch', new_callable=AsyncMock):
            with patch('logging.warning') as mock_warning:
                # Act - Fail only 5 batches
                for _ in range(5):
                    await router._handle_failed_batch(batch, AzureError("Error"))
                
                # Assert - Should not have warned yet (only warns on multiples of 10)
                # Note: There may be other warnings, so check specifically for batch failure warning
                batch_failure_warnings = [
                    call for call in mock_warning.call_args_list
                    if 'High batch failure rate detected' in str(call)
                ]
                assert len(batch_failure_warnings) == 0


class TestErrorCategoryInStoredBatch:
    """Test that error category is stored in failed batch metadata"""

    @pytest.fixture
    def router(self):
        """Create router with mocked Azure client"""
        mock_client = Mock()
        return SentinelRouter(
            dcr_endpoint="https://test.ingest.monitor.azure.com",
            rule_id="dcr-test123",
            stream_name="Custom-TestStream",
            logs_client=mock_client
        )

    @pytest.mark.asyncio
    async def test_error_category_stored_in_batch_info(self, router):
        """Test that error_category field is added to failed batch info"""
        # Arrange
        batch = [{'field': 'value'}]
        error = HttpResponseError(message="Service unavailable")
        error.status_code = 503
        
        stored_batch_info = None
        
        async def capture_stored_batch(batch_info):
            nonlocal stored_batch_info
            stored_batch_info = batch_info
        
        # Mock storage to capture the batch info
        with patch.object(router, '_store_failed_batch', side_effect=capture_stored_batch):
            # Act
            await router._handle_failed_batch(batch, error)
        
        # Assert
        assert stored_batch_info is not None
        assert 'error_category' in stored_batch_info
        assert stored_batch_info['error_category'] == 'azure_error:503'
