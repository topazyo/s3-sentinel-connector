import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from src.utils.error_handling import (
    ErrorConfig,
    ErrorHandler,
    NonRetryableError,
    RetryableError,
    retry_with_backoff,
)


@pytest.mark.asyncio
async def test_retry_with_backoff_retries_retryable_then_succeeds():
    attempts = {"count": 0}

    @retry_with_backoff(retries=3, base_delay=0.01)
    async def flaky_operation():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RetryableError("temporary failure")
        return "ok"

    with patch(
        "src.utils.error_handling.asyncio.sleep", new_callable=AsyncMock
    ) as sleep:
        result = await flaky_operation()

    assert result == "ok"
    assert attempts["count"] == 3
    assert sleep.await_count == 2


@pytest.mark.asyncio
async def test_retry_with_backoff_does_not_retry_non_retryable_errors():
    attempts = {"count": 0}

    @retry_with_backoff(retries=3, base_delay=0.01)
    async def non_retryable_operation():
        attempts["count"] += 1
        raise NonRetryableError("permanent failure")

    with patch(
        "src.utils.error_handling.asyncio.sleep", new_callable=AsyncMock
    ) as sleep:
        with pytest.raises(NonRetryableError):
            await non_retryable_operation()

    assert attempts["count"] == 1
    assert sleep.await_count == 0


@pytest.mark.asyncio
async def test_retry_with_backoff_stops_at_configured_retry_limit():
    attempts = {"count": 0}

    @retry_with_backoff(retries=2, base_delay=0.01)
    async def always_fails():
        attempts["count"] += 1
        raise RetryableError("still failing")

    with patch(
        "src.utils.error_handling.asyncio.sleep", new_callable=AsyncMock
    ) as sleep:
        with pytest.raises(RetryableError):
            await always_fails()

    assert attempts["count"] == 3
    assert sleep.await_count == 2


@pytest.mark.asyncio
async def test_retry_with_backoff_timeout_error_no_retry_by_default():
    attempts = {"count": 0}

    @retry_with_backoff(retries=3, base_delay=0.01)
    async def timeout_operation():
        attempts["count"] += 1
        raise asyncio.TimeoutError("operation timed out")

    with patch(
        "src.utils.error_handling.asyncio.sleep", new_callable=AsyncMock
    ) as sleep:
        with pytest.raises(asyncio.TimeoutError):
            await timeout_operation()

    assert attempts["count"] == 1
    assert sleep.await_count == 0


def test_error_handler_retry_delay_is_capped_by_max_delay():
    handler = ErrorHandler(
        ErrorConfig(
            max_retries=3,
            base_delay=10.0,
            max_delay=15.0,
            exponential_base=2.0,
            jitter=0.0,
        )
    )

    delay = handler.get_retry_delay(retry_count=3)

    assert delay == 15.0
