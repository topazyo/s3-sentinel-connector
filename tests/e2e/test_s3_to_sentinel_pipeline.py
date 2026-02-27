"""End-to-end style pipeline tests (mocked S3 + mocked Sentinel client)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from azure.core.exceptions import AzureError

from src.core.log_parser import JsonLogParser


@pytest.mark.asyncio
async def test_s3_parse_route_pipeline_end_to_end(s3_handler, mock_s3_bucket, sentinel_router):
    objects = s3_handler.list_objects(mock_s3_bucket, prefix="logs/firewall")
    assert objects

    parser = JsonLogParser()
    parsed_logs = []

    for obj in objects:
        raw_content = s3_handler.download_object(mock_s3_bucket, obj["Key"])
        raw_log = parser.parse(raw_content)
        raw_log["TimeGenerated"] = "2026-02-27T00:00:00Z"
        parsed_logs.append(raw_log)

    route_result = await sentinel_router.route_logs("firewall", parsed_logs)

    assert route_result["processed"] == len(parsed_logs)
    assert route_result["failed"] == 0
    assert sentinel_router.logs_client.upload.called


@pytest.mark.asyncio
async def test_multi_log_type_firewall_and_vpn_routes(
    s3_handler, mock_s3_bucket, sentinel_router
):
    objects = s3_handler.list_objects(mock_s3_bucket, prefix="logs/firewall")
    parser = JsonLogParser()

    firewall_logs = []
    for obj in objects:
        raw_content = s3_handler.download_object(mock_s3_bucket, obj["Key"])
        parsed = parser.parse(raw_content)
        parsed["TimeGenerated"] = "2026-02-27T00:00:00Z"
        firewall_logs.append(parsed)

    vpn_logs = [
        {
            "TimeGenerated": "2026-02-27T00:00:00Z",
            "UserPrincipalName": "alice@example.com",
            "SessionID": "session-001",
            "ClientIP": "10.10.0.5",
            "BytesIn": 128,
            "BytesOut": 512,
        }
    ]

    firewall_result = await sentinel_router.route_logs("firewall", firewall_logs)
    vpn_result = await sentinel_router.route_logs("vpn", vpn_logs)

    assert firewall_result["processed"] == len(firewall_logs)
    assert firewall_result["failed"] == 0
    assert vpn_result["processed"] == len(vpn_logs)
    assert vpn_result["failed"] == 0


def test_s3_timeout_injection_marks_failed_object(s3_handler, mock_s3_bucket, monkeypatch):
    objects = s3_handler.list_objects(mock_s3_bucket, prefix="logs/firewall")
    parser = JsonLogParser()
    original_download = s3_handler.download_object
    failing_key = objects[0]["Key"]

    def flaky_download(bucket: str, key: str):
        if key == failing_key:
            raise TimeoutError("simulated s3 timeout")
        return original_download(bucket, key)

    monkeypatch.setattr(s3_handler, "download_object", flaky_download)

    result = s3_handler.process_files_batch(
        bucket=mock_s3_bucket,
        objects=objects,
        parser=parser,
    )

    assert result["failed"] == 1
    assert len(result["successful"]) == len(objects) - 1


@pytest.mark.asyncio
async def test_sentinel_429_creates_failed_batch_file(
    sentinel_router, tmp_path
):
    sentinel_router.failed_logs_path = str(tmp_path)
    test_logs = [
        {
            "TimeGenerated": "2026-02-27T00:00:00Z",
            "SourceIP": "192.168.1.10",
            "DestinationIP": "10.0.0.10",
            "Action": "ALLOW",
        }
    ]

    with patch.object(
        sentinel_router._circuit_breaker,
        "call",
        side_effect=AzureError("429 Too Many Requests"),
    ):
        result = await sentinel_router.route_logs("firewall", test_logs)

    assert result["failed"] == 1
    failed_batch_files = list(tmp_path.glob("failed-batch-*.json"))
    assert len(failed_batch_files) == 1

    payload = json.loads(failed_batch_files[0].read_text(encoding="utf-8"))
    assert payload["error_category"].startswith("azure_error")
    assert payload["retry_count"] == 0
