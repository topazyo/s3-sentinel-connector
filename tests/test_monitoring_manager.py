from typing import List

import pytest

from src.monitoring import MonitoringManager


class StubMetricsClient:
    def __init__(self):
        self.calls: List[List[dict]] = []

    def ingest_metrics(self, payload):
        self.calls.append(payload)


@pytest.mark.asyncio
async def test_record_metric_updates_component_metrics():
    config = {
        "app_name": "test-app",
        "environment": "test",
        "components": ["core"],
        "metrics": {"endpoint": "https://localhost"},
        "alerts": [
            {
                "name": "pipeline_lag",
                "threshold": 100,
                "window_minutes": 5,
                "severity": "medium",
                "description": "Lag threshold breached",
                "action": "teams",
            }
        ],
    }

    client = StubMetricsClient()
    manager = MonitoringManager(
        config,
        enable_background_tasks=False,
        metrics_client=client,
    )

    await manager.record_metric(
        "core",
        "logs_processed",
        5,
        {"source": "core", "status": "success"},
    )

    health = await manager.get_component_health("core")
    assert health["metrics"]["processed_count"] == 5
    assert health["metrics"]["error_rate"] == 0

    assert client.calls, "expected metrics ingestion call"
    payload = client.calls[-1]
    assert payload[0]["name"] == "logs_processed"
    assert payload[0]["labels"]["source"] == "core"

    dashboard = manager.pipeline_monitor.get_monitoring_dashboard()
    assert dashboard["component_health"].get("core") is None