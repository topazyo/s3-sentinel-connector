from unittest.mock import AsyncMock, Mock, patch

import pytest


@pytest.fixture
def mock_monitoring_config():
    """Shared monitoring configuration fixture for monitoring unit tests."""
    return {
        "app_name": "test-app",
        "environment": "test",
        "components": ["s3_handler", "sentinel_router"],
        "metrics": {"endpoint": "http://prometheus:9090"},
        "alerts": [
            {"name": "high_error_rate", "threshold": 0.1, "duration": 300},
            {"name": "pipeline_lag", "threshold": 1000, "duration": 600},
        ],
    }


@pytest.fixture
def mock_monitoring_components():
    """Shared monitoring component mocks for MonitoringManager tests."""
    with (
        patch("src.monitoring.PipelineMonitor") as mock_pipeline,
        patch("src.monitoring.ComponentMetrics") as mock_metrics,
        patch("src.monitoring.AlertManager") as mock_alerts,
    ):
        mock_pipeline.return_value._health_check_loop = AsyncMock()
        mock_pipeline.return_value._metrics_export_loop = AsyncMock()
        mock_pipeline.return_value.record_metric = AsyncMock()

        mock_metrics_instance = Mock()
        mock_metrics_instance.record_metric = Mock()
        mock_metrics_instance.get_metrics = Mock(
            return_value={
                "total_processed": 100,
                "total_errors": 2,
                "error_rate": 0.02,
                "processing_time_avg": 0.15,
                "processing_time_p95": 0.25,
            }
        )
        mock_metrics.return_value = mock_metrics_instance

        mock_alerts_instance = Mock()
        mock_alerts_instance._alert_check_loop = AsyncMock()
        mock_alerts_instance.check_alert_conditions = AsyncMock(
            return_value={
                "active_alerts": [],
                "resolved_alerts": [],
                "total_alerts_checked": 2,
            }
        )
        mock_alerts.return_value = mock_alerts_instance

        yield {
            "pipeline": mock_pipeline,
            "alerts": mock_alerts,
            "metrics": mock_metrics,
            "pipeline_instance": mock_pipeline.return_value,
            "alerts_instance": mock_alerts_instance,
            "pipeline_monitor": mock_pipeline,
            "component_metrics": mock_metrics,
            "alert_manager": mock_alerts,
        }
