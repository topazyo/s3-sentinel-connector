from unittest.mock import Mock

import pytest

from src.core.log_parser import FirewallLogParser
from src.core.sentinel_router import SentinelRouter


@pytest.mark.asyncio
async def test_firewall_parser_output_routes_without_contract_drop():
    parser = FirewallLogParser()
    parsed_log = parser.parse(
        b"2024-01-01T10:00:00Z|192.168.1.100|10.0.0.1|ALLOW|rule1|TCP|80|443|1024"
    )

    mock_logs_client = Mock()
    mock_logs_client.upload = Mock(return_value=None)

    router = SentinelRouter(
        dcr_endpoint="https://test.ingest.monitor.azure.com",
        rule_id="dcr-test",
        stream_name="Custom-FirewallLogs",
        logs_client=mock_logs_client,
        credential=Mock(),
    )

    result = await router.route_logs("firewall", [parsed_log])

    assert result["processed"] == 1
    assert result["failed"] == 0
    assert result["dropped"] == 0
    assert result["batch_count"] == 1
