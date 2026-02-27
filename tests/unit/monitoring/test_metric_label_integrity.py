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
async def test_record_metric_caches_independent_label_copy(monitor_and_client):
    monitor, _ = monitor_and_client
    labels = {"source": "s3", "status": "success"}

    await monitor.record_metric("logs_processed", 1, labels)
    labels["status"] = "mutated"

    cached_metric = monitor._metric_cache["logs_processed"]
    assert cached_metric["labels"]["status"] == "success"


@pytest.mark.asyncio
async def test_record_metric_uses_empty_labels_when_none_provided(monitor_and_client):
    monitor, mock_client = monitor_and_client

    await monitor.record_metric("pipeline_lag", 3.5, labels=None)

    cached_metric = monitor._metric_cache["pipeline_lag"]
    assert cached_metric["labels"] == {}
    mock_client.ingest_metrics.assert_called_once()
