"""Integration tests for MonitoringManager cross-component behavior."""

from unittest.mock import Mock, patch

import pytest

from src.monitoring import MonitoringManager
from src.monitoring.pipeline_monitor import PipelineMonitor


@pytest.fixture
def monitoring_config() -> dict:
    """Monitoring configuration for integration scenarios."""
    return {
        "metrics": {"endpoint": "https://test.monitor.azure.com"},
        "app_name": "integration-test-app",
        "environment": "test",
        "components": ["s3_handler", "sentinel_router"],
        "alerts": [
            {
                "name": "high_error_rate",
                "metric": "error_rate",
                "threshold": 0.1,
                "operator": "gt",
                "duration": 60,
                "severity": "warning",
            }
        ],
    }


@pytest.mark.asyncio
async def test_monitoring_manager_full_lifecycle_integration(monitoring_config: dict):
    """MonitoringManager starts, records metrics, and cleans up background tasks."""

    def mock_initialize_clients(self, metrics_endpoint: str) -> None:
        self.metrics_client = Mock()

    with patch.object(PipelineMonitor, "_initialize_clients", mock_initialize_clients):
        manager = MonitoringManager(monitoring_config)

        await manager.start()
        assert manager._monitoring_started is True
        assert len(manager.tasks) == 3

        await manager.record_metric(
            component="s3_handler",
            metric_name="custom_ingestion_latency",
            value=1.25,
            labels={"source": "integration"},
        )

        health = await manager.get_component_health("s3_handler")
        assert health["status"] in {"healthy", "degraded"}
        assert "metrics" in health

        alerts = await manager.check_alerts()
        assert "active_alerts" in alerts
        assert "alert_count" in alerts

        await manager.cleanup()

        assert manager.tasks == []
        assert manager._monitoring_started is False


@pytest.mark.asyncio
async def test_monitoring_manager_stop_and_cleanup_idempotent(monitoring_config: dict):
    """Stop and cleanup can be called in sequence without task leakage."""

    def mock_initialize_clients(self, metrics_endpoint: str) -> None:
        self.metrics_client = Mock()

    with patch.object(PipelineMonitor, "_initialize_clients", mock_initialize_clients):
        manager = MonitoringManager(monitoring_config)

        await manager.start()
        await manager.stop()

        assert manager.tasks == []
        assert manager._monitoring_started is False

        await manager.cleanup()

        assert manager.tasks == []
        assert manager._monitoring_started is False
