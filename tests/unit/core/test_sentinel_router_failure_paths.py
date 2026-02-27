"""Unit tests for SentinelRouter ingestion failure paths (B3-007)."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock, patch

import pytest
from azure.core.exceptions import AzureError

from src.core.sentinel_router import SentinelRouter
from src.utils.circuit_breaker import CircuitBreakerOpenError


@pytest.fixture
def router() -> SentinelRouter:
    """Create router with mocked Azure client for failure-path tests."""
    return SentinelRouter(
        dcr_endpoint="https://test.ingest.monitor.azure.com",
        rule_id="dcr-test123",
        stream_name="Custom-TestStream",
        logs_client=Mock(),
    )


@pytest.mark.asyncio
async def test_ingest_batch_handles_circuit_breaker_open(router: SentinelRouter):
    """Circuit breaker open errors increment failures and store failed batch."""
    batch = [{"TimeGenerated": "2024-01-01T00:00:00Z", "SourceIP": "1.1.1.1"}]
    table_config = router.table_configs["firewall"]
    results = {"processed": 0, "failed": 0, "batch_count": 0}

    breaker_error = CircuitBreakerOpenError(
        "azure-sentinel", datetime.now(timezone.utc), recovery_timeout=60
    )

    with patch.object(router._circuit_breaker, "call", side_effect=breaker_error):
        with patch.object(
            router, "_handle_failed_batch", new_callable=AsyncMock
        ) as mfb:
            await router._ingest_batch(batch, table_config, results)

    assert results["failed"] == len(batch)
    mfb.assert_awaited_once_with(batch, breaker_error)


@pytest.mark.asyncio
async def test_ingest_batch_handles_azure_error(router: SentinelRouter):
    """Azure ingestion errors increment failures and store failed batch."""
    batch = [{"TimeGenerated": "2024-01-01T00:00:00Z", "SourceIP": "2.2.2.2"}]
    table_config = router.table_configs["firewall"]
    results = {"processed": 0, "failed": 0, "batch_count": 0}

    azure_error = AzureError("ingestion failed")

    with patch.object(router._circuit_breaker, "call", side_effect=azure_error):
        with patch.object(
            router, "_handle_failed_batch", new_callable=AsyncMock
        ) as mfb:
            await router._ingest_batch(batch, table_config, results)

    assert results["failed"] == len(batch)
    mfb.assert_awaited_once_with(batch, azure_error)


@pytest.mark.asyncio
async def test_ingest_batch_handles_unexpected_exception(router: SentinelRouter):
    """Unexpected exceptions increment failures without crashing ingest flow."""
    batch = [{"TimeGenerated": "2024-01-01T00:00:00Z", "SourceIP": "3.3.3.3"}]
    table_config = router.table_configs["firewall"]
    results = {"processed": 0, "failed": 0, "batch_count": 0}

    with patch.object(
        router._circuit_breaker, "call", side_effect=RuntimeError("boom")
    ):
        with patch.object(
            router, "_handle_failed_batch", new_callable=AsyncMock
        ) as mfb:
            await router._ingest_batch(batch, table_config, results)

    assert results["failed"] == len(batch)
    mfb.assert_not_awaited()
