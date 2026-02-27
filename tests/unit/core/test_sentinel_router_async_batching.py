import asyncio
from unittest.mock import Mock

import pytest

from src.core.sentinel_router import SentinelRouter


@pytest.mark.asyncio
async def test_route_logs_caps_batch_concurrency(monkeypatch):
    logs_client = Mock()
    logs_client.upload = Mock(return_value=None)

    router = SentinelRouter(
        dcr_endpoint="https://test-dcr.azure.com",
        rule_id="test-rule",
        stream_name="test-stream",
        logs_client=logs_client,
        max_concurrent_batches=2,
    )

    router.table_configs["firewall"].batch_size = 1

    active = 0
    peak_active = 0

    async def fake_ingest_batch(batch, table_config, results):
        nonlocal active, peak_active
        active += 1
        peak_active = max(peak_active, active)
        await asyncio.sleep(0.01)
        results["processed"] += len(batch)
        results["batch_count"] += 1
        active -= 1

    monkeypatch.setattr(router, "_ingest_batch", fake_ingest_batch)

    logs = [
        {
            "TimeGenerated": f"2024-01-01T10:00:{index:02d}Z",
            "SourceIP": "192.168.1.1",
            "DestinationIP": "10.0.0.1",
            "Action": "ALLOW",
        }
        for index in range(6)
    ]

    results = await router.route_logs("firewall", logs)

    assert peak_active <= 2
    assert results["processed"] == 6
    assert results["batch_count"] == 6
    assert results["failed"] == 0
