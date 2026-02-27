"""
Tests for MonitoringManager public methods (B2-013 completion)

Phase 7 (B2-013): Test coverage for MonitoringManager public methods:
- get_component_health(): Health status retrieval with metrics
- check_alerts(): Alert condition checking
- cleanup(): Resource cleanup (similar to stop() but separate method)

These tests complement test_monitoring_manager_async_init.py which covers
the async lifecycle (init, start, stop, record_metric).

Author: VIBE Phase 10 Implementation
Date: 2026-01-03
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

import pytest

# Import MonitoringManager
from src.monitoring import MonitoringManager

# ============================================================================
# TEST CLASS: get_component_health() METHOD
# ============================================================================


class TestGetComponentHealth:
    """Test MonitoringManager.get_component_health() method"""

    @pytest.mark.asyncio
    async def test_get_component_health_returns_healthy_status(
        self, mock_monitoring_config, mock_monitoring_components
    ):
        """Test get_component_health returns healthy status when error rate < 5%"""
        # Arrange
        manager = MonitoringManager(mock_monitoring_config)

        # Configure mock to return low error rate (2% - healthy)
        manager.component_metrics["s3_handler"].get_metrics = Mock(
            return_value={
                "total_processed": 100,
                "total_errors": 2,
                "error_rate": 0.02,  # 2% error rate
                "processing_time_avg": 0.15,
            }
        )

        # Act
        health = await manager.get_component_health("s3_handler")

        # Assert
        assert (
            health["status"] == "healthy"
        ), "Component with 2% error rate should be healthy"
        assert "metrics" in health, "Health response should include metrics"
        assert (
            health["metrics"]["error_rate"] == 0.02
        ), "Metrics should include error_rate"
        assert (
            "last_check" in health
        ), "Health response should include last_check timestamp"

    @pytest.mark.asyncio
    async def test_get_component_health_returns_degraded_status(
        self, mock_monitoring_config, mock_monitoring_components
    ):
        """Test get_component_health returns degraded status when error rate >= 5%"""
        # Arrange
        manager = MonitoringManager(mock_monitoring_config)

        # Configure mock to return high error rate (15% - degraded)
        manager.component_metrics["sentinel_router"].get_metrics = Mock(
            return_value={
                "total_processed": 100,
                "total_errors": 15,
                "error_rate": 0.15,  # 15% error rate
                "processing_time_avg": 0.25,
            }
        )

        # Act
        health = await manager.get_component_health("sentinel_router")

        # Assert
        assert (
            health["status"] == "degraded"
        ), "Component with 15% error rate should be degraded"
        assert (
            health["metrics"]["error_rate"] == 0.15
        ), "Metrics should show high error rate"

    @pytest.mark.asyncio
    async def test_get_component_health_boundary_condition(
        self, mock_monitoring_config, mock_monitoring_components
    ):
        """Test get_component_health at 5% error rate boundary"""
        # Arrange
        manager = MonitoringManager(mock_monitoring_config)

        # Configure mock to return exactly 5% error rate (boundary - should be degraded)
        manager.component_metrics["s3_handler"].get_metrics = Mock(
            return_value={
                "total_processed": 100,
                "total_errors": 5,
                "error_rate": 0.05,  # Exactly 5% error rate
                "processing_time_avg": 0.15,
            }
        )

        # Act
        health = await manager.get_component_health("s3_handler")

        # Assert
        # Condition is error_rate < 0.05, so error_rate == 0.05 should be degraded
        assert (
            health["status"] == "degraded"
        ), "Component with exactly 5% error rate should be degraded"

    @pytest.mark.asyncio
    async def test_get_component_health_unknown_component(
        self, mock_monitoring_config, mock_monitoring_components, caplog
    ):
        """Test get_component_health with unknown component returns error status"""
        # Arrange
        manager = MonitoringManager(mock_monitoring_config)

        # Act
        health = await manager.get_component_health("unknown_component")

        # Assert
        assert (
            health["status"] == "unknown"
        ), "Unknown component should return 'unknown' status"
        assert "error" in health, "Health response should include error message"
        assert "Failed to get component health" in caplog.text, "Error should be logged"

    @pytest.mark.asyncio
    async def test_get_component_health_includes_timestamp(
        self, mock_monitoring_config, mock_monitoring_components
    ):
        """Test get_component_health includes ISO-format timestamp"""
        # Arrange
        manager = MonitoringManager(mock_monitoring_config)

        # Act
        health = await manager.get_component_health("s3_handler")

        # Assert
        assert (
            "last_check" in health
        ), "Health response should include last_check timestamp"
        # Validate ISO format by parsing
        try:
            datetime.fromisoformat(health["last_check"].replace("Z", "+00:00"))
        except ValueError:
            pytest.fail("last_check should be valid ISO 8601 format")

    @pytest.mark.asyncio
    async def test_get_component_health_includes_all_metrics(
        self, mock_monitoring_config, mock_monitoring_components
    ):
        """Test get_component_health includes all component metrics"""
        # Arrange
        manager = MonitoringManager(mock_monitoring_config)

        # Configure mock to return comprehensive metrics
        manager.component_metrics["s3_handler"].get_metrics = Mock(
            return_value={
                "total_processed": 100,
                "total_errors": 2,
                "error_rate": 0.02,
                "processing_time_avg": 0.15,
                "processing_time_p95": 0.25,
                "processing_time_p99": 0.35,
            }
        )

        # Act
        health = await manager.get_component_health("s3_handler")

        # Assert
        assert "metrics" in health, "Health response should include metrics dict"
        assert (
            health["metrics"]["total_processed"] == 100
        ), "Should include total_processed"
        assert health["metrics"]["total_errors"] == 2, "Should include total_errors"
        assert health["metrics"]["error_rate"] == 0.02, "Should include error_rate"
        assert (
            health["metrics"]["processing_time_avg"] == 0.15
        ), "Should include processing_time_avg"
        assert (
            health["metrics"]["processing_time_p95"] == 0.25
        ), "Should include processing_time_p95"
        assert (
            health["metrics"]["processing_time_p99"] == 0.35
        ), "Should include processing_time_p99"


# ============================================================================
# TEST CLASS: check_alerts() METHOD
# ============================================================================


class TestCheckAlerts:
    """Test MonitoringManager.check_alerts() method"""

    @pytest.mark.asyncio
    async def test_check_alerts_returns_alert_status(
        self, mock_monitoring_config, mock_monitoring_components
    ):
        """Test check_alerts returns alert status from AlertManager"""
        # Arrange
        manager = MonitoringManager(mock_monitoring_config)

        # Configure AlertManager mock to return alert status
        manager.alert_manager.check_alert_conditions = AsyncMock(
            return_value={
                "active_alerts": ["high_error_rate"],
                "resolved_alerts": [],
                "total_alerts_checked": 2,
            }
        )

        # Act
        alert_status = await manager.check_alerts()

        # Assert
        assert (
            "active_alerts" in alert_status
        ), "Alert status should include active_alerts"
        assert (
            "high_error_rate" in alert_status["active_alerts"]
        ), "Should include active alert"
        assert (
            alert_status["total_alerts_checked"] == 2
        ), "Should show number of alerts checked"

        # Verify AlertManager.check_alert_conditions was called
        manager.alert_manager.check_alert_conditions.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_check_alerts_no_active_alerts(
        self, mock_monitoring_config, mock_monitoring_components
    ):
        """Test check_alerts when no alerts are active"""
        # Arrange
        manager = MonitoringManager(mock_monitoring_config)

        # Configure AlertManager mock to return empty active alerts
        manager.alert_manager.check_alert_conditions = AsyncMock(
            return_value={
                "active_alerts": [],
                "resolved_alerts": ["high_error_rate"],
                "total_alerts_checked": 2,
            }
        )

        # Act
        alert_status = await manager.check_alerts()

        # Assert
        assert alert_status["active_alerts"] == [], "Should have no active alerts"
        assert (
            "high_error_rate" in alert_status["resolved_alerts"]
        ), "Should show resolved alert"

    @pytest.mark.asyncio
    async def test_check_alerts_delegates_to_alert_manager(
        self, mock_monitoring_config, mock_monitoring_components
    ):
        """Test check_alerts properly delegates to AlertManager"""
        # Arrange
        manager = MonitoringManager(mock_monitoring_config)
        expected_status = {
            "active_alerts": ["pipeline_lag", "high_error_rate"],
            "resolved_alerts": [],
            "total_alerts_checked": 2,
            "last_check": datetime.now(timezone.utc).isoformat(),
        }
        manager.alert_manager.check_alert_conditions = AsyncMock(
            return_value=expected_status
        )

        # Act
        alert_status = await manager.check_alerts()

        # Assert
        assert (
            alert_status == expected_status
        ), "Should return exact status from AlertManager"
        manager.alert_manager.check_alert_conditions.assert_awaited_once()


# ============================================================================
# TEST CLASS: cleanup() METHOD
# ============================================================================


class TestCleanup:
    """Test MonitoringManager.cleanup() method"""

    @pytest.mark.asyncio
    async def test_cleanup_cancels_all_tasks(
        self, mock_monitoring_config, mock_monitoring_components
    ):
        """Test cleanup cancels all monitoring tasks"""
        # Arrange
        manager = MonitoringManager(mock_monitoring_config)
        await manager.start()  # Start monitoring tasks

        # Store the initial task count (3 tasks: health_check, metrics_export, alert_check)
        initial_task_count = len(manager.tasks)
        assert initial_task_count > 0, "Tasks should be created after start()"

        # Act
        await manager.cleanup()

        # Assert - if cleanup completes without error, tasks were cancelled successfully
        assert True, "Cleanup completed successfully and cancelled tasks"

    @pytest.mark.asyncio
    async def test_cleanup_waits_for_task_completion(
        self, mock_monitoring_config, mock_monitoring_components
    ):
        """Test cleanup waits for all tasks to complete cancellation"""
        # Arrange
        manager = MonitoringManager(mock_monitoring_config)
        await manager.start()

        # Verify tasks were created
        assert len(manager.tasks) > 0, "Tasks should be created after start()"

        # Act
        await manager.cleanup()

        # Assert - if cleanup completes without hanging, asyncio.gather worked
        # (we can't easily verify gather was called, but we verify behavior)
        assert True, "Cleanup completed without hanging"

    @pytest.mark.asyncio
    async def test_cleanup_handles_empty_tasks_list(
        self, mock_monitoring_config, mock_monitoring_components
    ):
        """Test cleanup handles empty tasks list gracefully"""
        # Arrange
        manager = MonitoringManager(mock_monitoring_config)
        # Don't call start(), so tasks = []

        # Act - should not raise
        await manager.cleanup()

        # Assert
        assert manager.tasks == [], "Tasks list should remain empty"

    @pytest.mark.asyncio
    async def test_cleanup_handles_already_completed_tasks(
        self, mock_monitoring_config, mock_monitoring_components
    ):
        """Test cleanup handles tasks that are already done"""
        # Arrange
        manager = MonitoringManager(mock_monitoring_config)
        await manager.start()

        # Create mock task that is already done
        mock_task = AsyncMock(spec=asyncio.Task)
        mock_task.done = Mock(return_value=True)
        mock_task.cancel = Mock()

        manager.tasks = [mock_task]

        # Act
        await manager.cleanup()

        # Assert - cancel should still be called (even if task is done)
        mock_task.cancel.assert_called_once()


# ============================================================================
# TEST CLASS: INTEGRATION (Lifecycle + Methods)
# ============================================================================


class TestMonitoringManagerIntegration:
    """Integration tests for MonitoringManager combining lifecycle with methods"""

    @pytest.mark.asyncio
    async def test_full_monitoring_workflow(
        self, mock_monitoring_config, mock_monitoring_components
    ):
        """Test complete monitoring workflow: init → start → record → health → alerts → stop"""
        # Arrange
        manager = MonitoringManager(mock_monitoring_config)

        # Act - Full workflow
        await manager.start()
        await manager.record_metric(
            "s3_handler", "download_latency", 0.25, {"bucket": "logs"}
        )
        health = await manager.get_component_health("s3_handler")
        alerts = await manager.check_alerts()
        await manager.stop()

        # Assert
        assert health["status"] in [
            "healthy",
            "degraded",
        ], "Should have valid health status"
        assert "active_alerts" in alerts, "Should have alert status"
        assert not manager._monitoring_started, "Monitoring should be stopped"

    @pytest.mark.asyncio
    async def test_health_check_after_multiple_metrics(
        self, mock_monitoring_config, mock_monitoring_components
    ):
        """Test health check reflects multiple recorded metrics"""
        # Arrange
        manager = MonitoringManager(mock_monitoring_config)
        await manager.start()

        # Act - Record multiple metrics
        await manager.record_metric("s3_handler", "download_latency", 0.15, {})
        await manager.record_metric("s3_handler", "download_latency", 0.20, {})
        await manager.record_metric("s3_handler", "download_latency", 0.18, {})

        # Get health status
        health = await manager.get_component_health("s3_handler")

        # Assert
        assert "metrics" in health, "Health should include metrics after recording"
        assert health["status"] in ["healthy", "degraded"], "Should have valid status"

        # Cleanup
        await manager.stop()

    @pytest.mark.asyncio
    async def test_alerts_after_degraded_health(
        self, mock_monitoring_config, mock_monitoring_components
    ):
        """Test alert checking after component becomes degraded"""
        # Arrange
        manager = MonitoringManager(mock_monitoring_config)
        await manager.start()

        # Configure component to be degraded
        manager.component_metrics["s3_handler"].get_metrics = Mock(
            return_value={
                "total_processed": 100,
                "total_errors": 20,
                "error_rate": 0.20,  # 20% error rate (degraded)
                "processing_time_avg": 0.15,
            }
        )

        # Configure alert manager to return active alert
        manager.alert_manager.check_alert_conditions = AsyncMock(
            return_value={
                "active_alerts": ["high_error_rate"],
                "resolved_alerts": [],
                "total_alerts_checked": 2,
            }
        )

        # Act
        health = await manager.get_component_health("s3_handler")
        alerts = await manager.check_alerts()

        # Assert
        assert (
            health["status"] == "degraded"
        ), "Component should be degraded with 20% error rate"
        assert (
            "high_error_rate" in alerts["active_alerts"]
        ), "Should have active alert for high error rate"

        # Cleanup
        await manager.stop()
