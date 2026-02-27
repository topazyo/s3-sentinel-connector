from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from s3_sentinel.pipeline import PipelineState
from s3_sentinel.server import HealthServer


def test_health_endpoint_reports_ok(tmp_path):
    state = PipelineState(started_at=datetime.now(timezone.utc), running=True)
    server = HealthServer(state=state, failed_batches_dir=str(tmp_path))

    response = asyncio.run(server.health(None))

    assert response.status == 200


def test_ready_endpoint_returns_503_until_ready(tmp_path):
    state = PipelineState(started_at=datetime.now(timezone.utc), ready=False)
    server = HealthServer(state=state, failed_batches_dir=str(tmp_path))

    response = asyncio.run(server.ready(None))

    assert response.status == 503


def test_metrics_endpoint_includes_failed_batch_gauges(tmp_path):
    (tmp_path / "failed-1.json").write_text('{"data": []}', encoding="utf-8")
    state = PipelineState(started_at=datetime.now(timezone.utc), ready=True)
    server = HealthServer(state=state, failed_batches_dir=str(tmp_path))

    response = asyncio.run(server.metrics(None))

    body = response.body.decode("utf-8")
    assert response.status == 200
    assert "s3_sentinel_failed_batch_files" in body
