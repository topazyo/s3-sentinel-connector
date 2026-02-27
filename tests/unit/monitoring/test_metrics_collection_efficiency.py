from unittest.mock import MagicMock, patch

import pytest

from src.monitoring.pipeline_monitor import PipelineMonitor


@pytest.fixture
def monitor_and_client():
    with (
        patch(
            "src.monitoring.pipeline_monitor.MetricsIngestionClient"
        ) as mock_client_class,
        patch("src.monitoring.pipeline_monitor.DefaultAzureCredential"),
    ):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        monitor = PipelineMonitor(
            metrics_endpoint="http://localhost:9090",
            app_name="test-app",
            environment="test",
        )

        yield monitor, mock_client


@pytest.mark.asyncio
async def test_record_metric_clears_pending_on_success(monitor_and_client):
    monitor, _ = monitor_and_client

    await monitor.record_metric("pipeline_lag", 1.0)

    assert "pipeline_lag" not in monitor._pending_metric_names


@pytest.mark.asyncio
async def test_record_metric_keeps_pending_on_ingest_failure(monitor_and_client):
    monitor, mock_client = monitor_and_client
    mock_client.ingest_metrics.side_effect = RuntimeError("boom")

    await monitor.record_metric("pipeline_lag", 2.0)

    assert "pipeline_lag" in monitor._pending_metric_names
    pending_metrics = monitor._collect_current_metrics(only_pending=True)
    assert len(pending_metrics) == 1
    assert pending_metrics[0]["name"] == "pipeline_lag"


@pytest.mark.asyncio
async def test_export_to_azure_monitor_clears_exported_pending_metrics(
    monitor_and_client,
):
    monitor, _ = monitor_and_client

    monitor._metric_cache["pipeline_lag"] = {
        "name": "pipeline_lag",
        "value": 5,
        "timestamp": "2026-02-22T00:00:00+00:00",
        "labels": {},
        "app": "test-app",
        "environment": "test",
    }
    monitor._pending_metric_names.add("pipeline_lag")

    metrics = monitor._collect_current_metrics(only_pending=True)
    await monitor._export_to_azure_monitor(metrics)

    assert "pipeline_lag" not in monitor._pending_metric_names
