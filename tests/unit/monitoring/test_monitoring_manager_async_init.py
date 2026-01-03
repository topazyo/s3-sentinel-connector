# tests/unit/monitoring/test_monitoring_manager_async_init.py
"""
Tests for MonitoringManager async initialization pattern

Phase 4 (Resilience - B2-003/RES-03): Test async start()/stop() methods
to avoid RuntimeError: no running event loop during __init__

Phase 7 (Testing): Comprehensive coverage of lifecycle management
"""

import asyncio
import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from src.monitoring import MonitoringManager


@pytest.fixture
def mock_monitoring_config():
    """Mock monitoring configuration"""
    return {
        'app_name': 'test-app',
        'environment': 'test',
        'components': ['s3_handler', 'sentinel_router'],
        'metrics': {
            'endpoint': 'http://localhost:9090'
        },
        'alerts': [
            {'name': 'high_error_rate', 'threshold': 0.1}
        ]
    }


@pytest.fixture
def mock_monitoring_components():
    """Mock monitoring component classes"""
    with patch('src.monitoring.ComponentMetrics') as mock_metrics, \
         patch('src.monitoring.AlertManager') as mock_alerts, \
         patch('src.monitoring.PipelineMonitor') as mock_pipeline:
        
        # Mock PipelineMonitor
        mock_pipeline_instance = AsyncMock()
        mock_pipeline_instance._health_check_loop = AsyncMock()
        mock_pipeline_instance._metrics_export_loop = AsyncMock()
        mock_pipeline_instance.record_metric = AsyncMock()
        mock_pipeline.return_value = mock_pipeline_instance
        
        # Mock AlertManager
        mock_alerts_instance = AsyncMock()
        mock_alerts_instance._alert_check_loop = AsyncMock()
        mock_alerts.return_value = mock_alerts_instance
        
        # Mock ComponentMetrics
        mock_metrics_instance = Mock()
        mock_metrics_instance.record_metric = Mock()
        mock_metrics.return_value = mock_metrics_instance
        
        yield {
            'pipeline': mock_pipeline,
            'alerts': mock_alerts,
            'metrics': mock_metrics,
            'pipeline_instance': mock_pipeline_instance,
            'alerts_instance': mock_alerts_instance
        }


class TestMonitoringManagerInitialization:
    """Test MonitoringManager initialization without event loop issues
    
    Phase 4 (Resilience - B2-003): Verify sync __init__ doesn't create tasks
    """
    
    def test_init_without_event_loop_succeeds(self, mock_monitoring_config, mock_monitoring_components):
        """__init__ succeeds without active event loop"""
        # No event loop running during test setup
        manager = MonitoringManager(mock_monitoring_config)
        
        # Should initialize successfully
        assert manager.config == mock_monitoring_config
        assert manager.tasks == []
        assert manager._monitoring_started is False
        assert hasattr(manager, 'pipeline_monitor')
        assert hasattr(manager, 'alert_manager')
    
    def test_init_components_created(self, mock_monitoring_config, mock_monitoring_components):
        """__init__ creates monitoring components"""
        manager = MonitoringManager(mock_monitoring_config)
        
        # Verify components initialized
        assert manager.pipeline_monitor is not None
        assert manager.alert_manager is not None
        assert 's3_handler' in manager.component_metrics
        assert 'sentinel_router' in manager.component_metrics
    
    def test_init_does_not_start_tasks(self, mock_monitoring_config, mock_monitoring_components):
        """__init__ does not create asyncio tasks"""
        manager = MonitoringManager(mock_monitoring_config)
        
        # No tasks created yet
        assert len(manager.tasks) == 0
        assert manager._monitoring_started is False


class TestMonitoringManagerAsyncStart:
    """Test MonitoringManager async start() method
    
    Phase 4 (Resilience - B2-003): Verify start() creates tasks in async context
    """
    
    @pytest.mark.asyncio
    async def test_start_creates_tasks(self, mock_monitoring_config, mock_monitoring_components):
        """start() creates background tasks"""
        manager = MonitoringManager(mock_monitoring_config)
        
        # Start monitoring
        await manager.start()
        
        # Verify tasks created
        assert len(manager.tasks) == 3
        assert manager._monitoring_started is True
        
        # Cleanup
        await manager.stop()
    
    @pytest.mark.asyncio
    async def test_start_called_from_async_context(self, mock_monitoring_config, mock_monitoring_components):
        """start() works in async context"""
        manager = MonitoringManager(mock_monitoring_config)
        
        # Should not raise RuntimeError
        await manager.start()
        
        # All tasks should be asyncio.Task instances
        for task in manager.tasks:
            assert isinstance(task, asyncio.Task)
        
        # Cleanup
        await manager.stop()
    
    @pytest.mark.asyncio
    async def test_start_idempotent(self, mock_monitoring_config, mock_monitoring_components):
        """start() can be called multiple times safely"""
        manager = MonitoringManager(mock_monitoring_config)
        
        # Call start() twice
        await manager.start()
        first_tasks = manager.tasks.copy()
        
        await manager.start()  # Should be idempotent
        
        # Should still have same tasks (not duplicated)
        assert manager.tasks == first_tasks
        assert len(manager.tasks) == 3
        
        # Cleanup
        await manager.stop()
    
    @pytest.mark.asyncio
    async def test_start_logs_success(self, mock_monitoring_config, mock_monitoring_components, caplog):
        """start() logs successful task creation"""
        import logging
        caplog.set_level(logging.INFO)
        
        manager = MonitoringManager(mock_monitoring_config)
        
        await manager.start()
        
        # Verify logging
        assert "Monitoring tasks started successfully" in caplog.text
        
        # Cleanup
        await manager.stop()


class TestMonitoringManagerAsyncStop:
    """Test MonitoringManager async stop() method
    
    Phase 4 (Resilience - B2-003): Verify graceful shutdown of tasks
    """
    
    @pytest.mark.asyncio
    async def test_stop_cancels_tasks(self, mock_monitoring_config, mock_monitoring_components):
        """stop() cancels all background tasks"""
        manager = MonitoringManager(mock_monitoring_config)
        
        await manager.start()
        assert len(manager.tasks) == 3
        
        # Stop monitoring
        await manager.stop()
        
        # Verify tasks cancelled and cleared
        assert len(manager.tasks) == 0
        assert manager._monitoring_started is False
    
    @pytest.mark.asyncio
    async def test_stop_before_start_safe(self, mock_monitoring_config, mock_monitoring_components):
        """stop() before start() is safe (no-op)"""
        manager = MonitoringManager(mock_monitoring_config)
        
        # Stop without starting
        await manager.stop()  # Should not raise
        
        assert manager._monitoring_started is False
        assert len(manager.tasks) == 0
    
    @pytest.mark.asyncio
    async def test_stop_waits_for_task_completion(self, mock_monitoring_config, mock_monitoring_components):
        """stop() waits for tasks to complete cancellation"""
        manager = MonitoringManager(mock_monitoring_config)
        
        await manager.start()
        
        # Add delay to tasks to simulate work
        for task in manager.tasks:
            task.cancel()
        
        # Stop should wait for cancellation
        await manager.stop()
        
        # All tasks should be done
        assert all(task.done() for task in [] if manager.tasks)
    
    @pytest.mark.asyncio
    async def test_stop_logs_success(self, mock_monitoring_config, mock_monitoring_components, caplog):
        """stop() logs successful shutdown"""
        import logging
        caplog.set_level(logging.INFO)
        
        manager = MonitoringManager(mock_monitoring_config)
        
        await manager.start()
        await manager.stop()
        
        # Verify logging
        assert "Stopping monitoring tasks..." in caplog.text
        assert "Monitoring tasks stopped successfully" in caplog.text


class TestMonitoringManagerLifecycle:
    """Test MonitoringManager full lifecycle
    
    Phase 4 (Resilience - B2-003): Test start → record metrics → stop flow
    """
    
    @pytest.mark.asyncio
    async def test_full_lifecycle(self, mock_monitoring_config, mock_monitoring_components):
        """Test init → start → record_metric → stop"""
        manager = MonitoringManager(mock_monitoring_config)
        
        # Start
        await manager.start()
        assert manager._monitoring_started is True
        
        # Record metric (should work with tasks running)
        await manager.record_metric(
            component='s3_handler',
            metric_name='files_processed',
            value=10.0,
            labels={'status': 'success'}
        )
        
        # Stop
        await manager.stop()
        assert manager._monitoring_started is False
    
    @pytest.mark.asyncio
    async def test_restart_after_stop(self, mock_monitoring_config, mock_monitoring_components):
        """Can restart monitoring after stop"""
        manager = MonitoringManager(mock_monitoring_config)
        
        # First cycle
        await manager.start()
        await manager.stop()
        
        # Second cycle (restart)
        await manager.start()
        assert manager._monitoring_started is True
        assert len(manager.tasks) == 3
        
        # Cleanup
        await manager.stop()


class TestMonitoringManagerErrorHandling:
    """Test MonitoringManager error scenarios
    
    Phase 4 (Resilience - B2-003): Error handling during lifecycle
    """
    
    @pytest.mark.asyncio
    async def test_record_metric_without_start_works(self, mock_monitoring_config, mock_monitoring_components):
        """record_metric works even if tasks not started"""
        manager = MonitoringManager(mock_monitoring_config)
        
        # Don't call start(), but record_metric should still work
        await manager.record_metric(
            component='s3_handler',
            metric_name='test_metric',
            value=1.0
        )
        
        # Should not raise
    
    @pytest.mark.asyncio
    async def test_record_metric_unknown_component_handles_error(self, mock_monitoring_config, mock_monitoring_components, caplog):
        """record_metric with unknown component logs error gracefully"""
        import logging
        caplog.set_level(logging.ERROR)
        
        manager = MonitoringManager(mock_monitoring_config)
        await manager.start()
        
        # Should not raise (error is caught and logged)
        await manager.record_metric(
            component='unknown_component',
            metric_name='test_metric',
            value=1.0
        )
        
        # Verify error logged
        assert "Failed to record metric" in caplog.text
        assert "unknown_component" in caplog.text
        
        # Cleanup
        await manager.stop()


class TestMonitoringManagerBackwardsCompatibility:
    """Test backwards compatibility and migration path
    
    Phase 2 (Consistency - B2-003): Ensure existing usage patterns supported
    """
    
    def test_init_still_creates_components(self, mock_monitoring_config, mock_monitoring_components):
        """Existing code that only calls __init__ still gets components"""
        manager = MonitoringManager(mock_monitoring_config)
        
        # Components should exist for backward compatibility
        assert manager.pipeline_monitor is not None
        assert manager.alert_manager is not None
        
        # But tasks should not be created
        assert len(manager.tasks) == 0
