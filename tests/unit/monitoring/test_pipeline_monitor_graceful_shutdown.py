# tests/unit/monitoring/test_pipeline_monitor_graceful_shutdown.py
"""
Tests for PipelineMonitor graceful shutdown of background loops

Phase 4 (Resilience - B2-004/RES-04): Test CancelledError handling
in _health_check_loop, _metrics_export_loop, and _alert_check_loop

Phase 7 (Testing): Comprehensive coverage of shutdown scenarios
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.monitoring.pipeline_monitor import PipelineMonitor, AlertConfig


@pytest.fixture
def mock_azure_clients():
    """Mock Azure monitoring clients"""
    with patch('src.monitoring.pipeline_monitor.MetricsIngestionClient') as mock_metrics, \
         patch('src.monitoring.pipeline_monitor.DefaultAzureCredential') as mock_cred:
        
        # Mock credential
        mock_cred.return_value = MagicMock()
        
        # Mock metrics client
        mock_metrics_instance = MagicMock()
        mock_metrics_instance.ingest_metrics = AsyncMock()
        mock_metrics.return_value = mock_metrics_instance
        
        yield {
            'metrics': mock_metrics,
            'credential': mock_cred,
            'metrics_instance': mock_metrics_instance
        }


@pytest.fixture
def pipeline_monitor(mock_azure_clients):
    """Create PipelineMonitor instance"""
    monitor = PipelineMonitor(
        metrics_endpoint='https://test.monitor.azure.com',
        app_name='test-app',
        environment='test',
        alert_configs=[
            AlertConfig(
                name='test_alert',
                threshold=0.8,
                window_minutes=5,
                severity='HIGH',
                description='Test alert',
                action='notify'
            )
        ],
        enable_background_tasks=False  # Don't auto-start
    )
    return monitor


class TestHealthCheckLoopGracefulShutdown:
    """Test _health_check_loop graceful shutdown
    
    Phase 4 (Resilience - B2-004): Verify CancelledError handling
    """
    
    @pytest.mark.asyncio
    async def test_health_check_loop_handles_cancellation(self, pipeline_monitor):
        """_health_check_loop handles CancelledError gracefully"""
        # Mock health check methods to avoid actual network calls
        pipeline_monitor._check_s3_health = AsyncMock(return_value={'status': True})
        pipeline_monitor._check_sentinel_health = AsyncMock(return_value={'status': True})
        pipeline_monitor._check_pipeline_lag = AsyncMock(return_value=0.5)
        
        # Start the loop
        task = asyncio.create_task(pipeline_monitor._health_check_loop())
        
        # Let it run for a short time
        await asyncio.sleep(0.1)
        
        # Cancel the task
        task.cancel()
        
        # Should raise CancelledError (not unhandled exception)
        with pytest.raises(asyncio.CancelledError):
            await task
    
    @pytest.mark.asyncio
    async def test_health_check_loop_logs_shutdown(self, pipeline_monitor, caplog):
        """_health_check_loop logs shutdown messages"""
        import logging
        caplog.set_level(logging.INFO)
        
        # Mock health check methods
        pipeline_monitor._check_s3_health = AsyncMock(return_value={'status': True})
        pipeline_monitor._check_sentinel_health = AsyncMock(return_value={'status': True})
        pipeline_monitor._check_pipeline_lag = AsyncMock(return_value=0.5)
        
        # Start and cancel
        task = asyncio.create_task(pipeline_monitor._health_check_loop())
        await asyncio.sleep(0.1)
        task.cancel()
        
        try:
            await task
        except asyncio.CancelledError:
            pass
        
        # Verify logging
        assert "Health check loop cancelled, shutting down gracefully" in caplog.text
        assert "Health check loop shutdown complete" in caplog.text
    
    @pytest.mark.asyncio
    async def test_health_check_loop_continues_after_error(self, pipeline_monitor):
        """_health_check_loop continues running after non-cancellation errors"""
        # Mock to fail first, then succeed
        call_count = 0
        
        async def failing_health_check():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("Test error")
            return {'status': True}
        
        pipeline_monitor._check_s3_health = failing_health_check
        pipeline_monitor._check_sentinel_health = AsyncMock(return_value={'status': True})
        pipeline_monitor._check_pipeline_lag = AsyncMock(return_value=0.5)
        
        # Start loop
        task = asyncio.create_task(pipeline_monitor._health_check_loop())
        
        # Wait for error recovery (short sleep in code)
        await asyncio.sleep(0.1)
        
        # Should still be running
        assert not task.done()
        
        # Cancel
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


class TestMetricsExportLoopGracefulShutdown:
    """Test _metrics_export_loop graceful shutdown
    
    Phase 4 (Resilience - B2-004): Verify CancelledError handling
    """
    
    @pytest.mark.asyncio
    async def test_metrics_export_loop_handles_cancellation(self, pipeline_monitor):
        """_metrics_export_loop handles CancelledError gracefully"""
        # Mock export methods
        pipeline_monitor._collect_current_metrics = MagicMock(return_value={})
        pipeline_monitor._export_to_azure_monitor = AsyncMock()
        pipeline_monitor._export_to_prometheus = MagicMock()
        
        # Start the loop
        task = asyncio.create_task(pipeline_monitor._metrics_export_loop())
        
        # Let it run briefly
        await asyncio.sleep(0.1)
        
        # Cancel the task
        task.cancel()
        
        # Should raise CancelledError (not unhandled exception)
        with pytest.raises(asyncio.CancelledError):
            await task
    
    @pytest.mark.asyncio
    async def test_metrics_export_loop_logs_shutdown(self, pipeline_monitor, caplog):
        """_metrics_export_loop logs shutdown messages"""
        import logging
        caplog.set_level(logging.INFO)
        
        # Mock export methods
        pipeline_monitor._collect_current_metrics = MagicMock(return_value={})
        pipeline_monitor._export_to_azure_monitor = AsyncMock()
        pipeline_monitor._export_to_prometheus = MagicMock()
        
        # Start and cancel
        task = asyncio.create_task(pipeline_monitor._metrics_export_loop())
        await asyncio.sleep(0.1)
        task.cancel()
        
        try:
            await task
        except asyncio.CancelledError:
            pass
        
        # Verify logging
        assert "Metrics export loop cancelled, shutting down gracefully" in caplog.text
        assert "Metrics export loop shutdown complete" in caplog.text
    
    @pytest.mark.asyncio
    async def test_metrics_export_loop_continues_after_error(self, pipeline_monitor):
        """_metrics_export_loop continues running after export errors"""
        # Mock to fail first, then succeed
        call_count = 0
        
        async def failing_export(metrics):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Export failed")
        
        pipeline_monitor._collect_current_metrics = MagicMock(return_value={})
        pipeline_monitor._export_to_azure_monitor = failing_export
        pipeline_monitor._export_to_prometheus = MagicMock()
        
        # Start loop
        task = asyncio.create_task(pipeline_monitor._metrics_export_loop())
        
        # Wait for error recovery
        await asyncio.sleep(0.1)
        
        # Should still be running
        assert not task.done()
        
        # Cancel
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


class TestAlertCheckLoopGracefulShutdown:
    """Test _alert_check_loop graceful shutdown
    
    Phase 4 (Resilience - B2-004): Verify CancelledError handling
    """
    
    @pytest.mark.asyncio
    async def test_alert_check_loop_handles_cancellation(self, pipeline_monitor):
        """_alert_check_loop handles CancelledError gracefully"""
        # Mock alert checking
        pipeline_monitor._check_alert_condition = AsyncMock()
        
        # Start the loop
        task = asyncio.create_task(pipeline_monitor._alert_check_loop())
        
        # Let it run briefly
        await asyncio.sleep(0.1)
        
        # Cancel the task
        task.cancel()
        
        # Should raise CancelledError (not unhandled exception)
        with pytest.raises(asyncio.CancelledError):
            await task
    
    @pytest.mark.asyncio
    async def test_alert_check_loop_logs_shutdown(self, pipeline_monitor, caplog):
        """_alert_check_loop logs shutdown messages"""
        import logging
        caplog.set_level(logging.INFO)
        
        # Mock alert checking
        pipeline_monitor._check_alert_condition = AsyncMock()
        
        # Start and cancel
        task = asyncio.create_task(pipeline_monitor._alert_check_loop())
        await asyncio.sleep(0.1)
        task.cancel()
        
        try:
            await task
        except asyncio.CancelledError:
            pass
        
        # Verify logging
        assert "Alert check loop cancelled, shutting down gracefully" in caplog.text
        assert "Alert check loop shutdown complete" in caplog.text
    
    @pytest.mark.asyncio
    async def test_alert_check_loop_continues_after_error(self, pipeline_monitor):
        """_alert_check_loop continues running after check errors"""
        # Mock to fail first, then succeed
        call_count = 0
        
        async def failing_alert_check(alert_config):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Alert check failed")
        
        pipeline_monitor._check_alert_condition = failing_alert_check
        
        # Start loop
        task = asyncio.create_task(pipeline_monitor._alert_check_loop())
        
        # Wait for error recovery
        await asyncio.sleep(0.1)
        
        # Should still be running
        assert not task.done()
        
        # Cancel
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


class TestMultipleLoopsGracefulShutdown:
    """Test graceful shutdown of all loops together
    
    Phase 4 (Resilience - B2-004): Integration test for concurrent shutdown
    """
    
    @pytest.mark.asyncio
    async def test_all_loops_shutdown_together(self, pipeline_monitor):
        """All three loops can be cancelled simultaneously"""
        # Mock all dependencies
        pipeline_monitor._check_s3_health = AsyncMock(return_value={'status': True})
        pipeline_monitor._check_sentinel_health = AsyncMock(return_value={'status': True})
        pipeline_monitor._check_pipeline_lag = AsyncMock(return_value=0.5)
        pipeline_monitor._collect_current_metrics = MagicMock(return_value={})
        pipeline_monitor._export_to_azure_monitor = AsyncMock()
        pipeline_monitor._export_to_prometheus = MagicMock()
        pipeline_monitor._check_alert_condition = AsyncMock()
        
        # Start all loops
        tasks = [
            asyncio.create_task(pipeline_monitor._health_check_loop()),
            asyncio.create_task(pipeline_monitor._metrics_export_loop()),
            asyncio.create_task(pipeline_monitor._alert_check_loop())
        ]
        
        # Let them run
        await asyncio.sleep(0.1)
        
        # Cancel all
        for task in tasks:
            task.cancel()
        
        # Wait for all to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # All should be CancelledError
        assert all(isinstance(r, asyncio.CancelledError) for r in results)
    
    @pytest.mark.asyncio
    async def test_loops_can_restart_after_shutdown(self, pipeline_monitor):
        """Loops can be restarted after graceful shutdown"""
        # Mock dependencies
        pipeline_monitor._check_s3_health = AsyncMock(return_value={'status': True})
        pipeline_monitor._check_sentinel_health = AsyncMock(return_value={'status': True})
        pipeline_monitor._check_pipeline_lag = AsyncMock(return_value=0.5)
        
        # First run
        task1 = asyncio.create_task(pipeline_monitor._health_check_loop())
        await asyncio.sleep(0.05)
        task1.cancel()
        try:
            await task1
        except asyncio.CancelledError:
            pass
        
        # Second run (restart)
        task2 = asyncio.create_task(pipeline_monitor._health_check_loop())
        await asyncio.sleep(0.05)
        
        # Should be running
        assert not task2.done()
        
        # Cleanup
        task2.cancel()
        try:
            await task2
        except asyncio.CancelledError:
            pass


class TestErrorHandlingDuringShutdown:
    """Test error handling during shutdown scenarios
    
    Phase 4 (Resilience - B2-004): Edge cases during cancellation
    """
    
    @pytest.mark.asyncio
    async def test_cancellation_during_sleep(self, pipeline_monitor):
        """Loop handles cancellation during asyncio.sleep"""
        # Mock dependencies
        pipeline_monitor._check_s3_health = AsyncMock(return_value={'status': True})
        pipeline_monitor._check_sentinel_health = AsyncMock(return_value={'status': True})
        pipeline_monitor._check_pipeline_lag = AsyncMock(return_value=0.5)
        
        # Start loop
        task = asyncio.create_task(pipeline_monitor._health_check_loop())
        
        # Cancel immediately (likely during sleep)
        await asyncio.sleep(0.01)
        task.cancel()
        
        # Should handle cancellation cleanly
        with pytest.raises(asyncio.CancelledError):
            await task
    
    @pytest.mark.asyncio
    async def test_cancellation_during_async_operation(self, pipeline_monitor):
        """Loop handles cancellation during long async operation"""
        # Mock health check that takes a while
        async def slow_health_check():
            await asyncio.sleep(10)  # Long operation
            return {'status': True}
        
        pipeline_monitor._check_s3_health = slow_health_check
        pipeline_monitor._check_sentinel_health = AsyncMock(return_value={'status': True})
        pipeline_monitor._check_pipeline_lag = AsyncMock(return_value=0.5)
        
        # Start loop
        task = asyncio.create_task(pipeline_monitor._health_check_loop())
        
        # Cancel during async operation
        await asyncio.sleep(0.05)
        task.cancel()
        
        # Should propagate cancellation
        with pytest.raises(asyncio.CancelledError):
            await task
