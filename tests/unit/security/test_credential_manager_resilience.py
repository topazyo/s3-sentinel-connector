# tests/unit/security/test_credential_manager_resilience.py
"""
Tests for CredentialManager Key Vault resilience features

Phase 4 (Resilience - B2-002/RES-02): Test circuit breaker, timeout,
and retry logic for Key Vault operations.

Phase 7 (Testing): Comprehensive coverage of failure scenarios.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from azure.core.exceptions import ResourceNotFoundError, ServiceRequestError

from src.security.credential_manager import CredentialManager
from src.utils.circuit_breaker import CircuitBreakerOpenError, CircuitState
from src.utils.error_handling import RetryableError


def create_credential_manager():
    """Factory to create CredentialManager with mocked SecretClient"""
    mock_client = AsyncMock()
    mock_client.get_secret = AsyncMock()
    mock_client.set_secret = AsyncMock()

    with patch(
        "src.security.credential_manager.SecretClient", return_value=mock_client
    ):
        manager = CredentialManager(
            vault_url="https://test-vault.vault.azure.net/",
            cache_duration=3600,
            enable_encryption=False,  # Disable encryption for simpler tests
        )
        # Replace secret_client with our mock
        manager.secret_client = mock_client
        return manager, mock_client


class TestKeyVaultCircuitBreaker:
    """Test circuit breaker integration with Key Vault operations

    Phase 4 (Resilience - B2-002): Verify circuit breaker protects Key Vault calls
    """

    @pytest.mark.asyncio
    async def test_get_credential_success_keeps_circuit_closed(self):
        """Successful credential fetch keeps circuit breaker closed"""
        credential_manager, mock_secret_client = create_credential_manager()

        # Mock successful response
        mock_secret = MagicMock()
        mock_secret.value = "test-secret-value"
        mock_secret_client.get_secret.return_value = mock_secret

        # Multiple successful calls
        for _i in range(5):
            result = await credential_manager.get_credential("test-cred")
            assert result == "test-secret-value"

        # Circuit should still be closed
        assert credential_manager._circuit_breaker.state == CircuitState.CLOSED
        assert credential_manager._circuit_breaker.failure_count == 0

    @pytest.mark.asyncio
    async def test_get_credential_timeout_increments_failure_count(self):
        """Timeout during credential fetch increments circuit breaker failure count"""
        credential_manager, mock_secret_client = create_credential_manager()

        # Mock timeout (simulate slow Key Vault response)
        async def slow_response(*args, **kwargs):
            await asyncio.sleep(15)  # Exceeds 10s timeout
            mock_secret = MagicMock()
            mock_secret.value = "value"
            return mock_secret

        mock_secret_client.get_secret.side_effect = slow_response

        # First timeout attempt
        with pytest.raises(RetryableError):
            await credential_manager.get_credential("test-cred")

        # Failure count should increment
        assert credential_manager._circuit_breaker.failure_count == 1
        assert (
            credential_manager._circuit_breaker.state == CircuitState.CLOSED
        )  # Still closed after 1 failure

    @pytest.mark.asyncio
    async def test_get_credential_opens_circuit_after_threshold(self):
        """Circuit opens after failure threshold exceeded"""
        credential_manager, mock_secret_client = create_credential_manager()

        # Mock repeated failures
        mock_secret_client.get_secret.side_effect = ServiceRequestError(
            "Key Vault unavailable"
        )

        # Trigger failures up to threshold (5 failures, min_calls_before_open=10 default)
        # Need to meet both thresholds
        credential_manager._circuit_breaker.config.min_calls_before_open = 1

        for i in range(5):
            with pytest.raises(ServiceRequestError):
                await credential_manager.get_credential(f"test-cred-{i}")

        # Circuit should now be OPEN
        assert credential_manager._circuit_breaker.state == CircuitState.OPEN
        assert credential_manager._circuit_breaker.failure_count == 5

    @pytest.mark.asyncio
    async def test_get_credential_circuit_open_raises_immediately(self):
        """When circuit is open, requests fail immediately without calling Key Vault"""
        credential_manager, mock_secret_client = create_credential_manager()

        # Open the circuit manually
        credential_manager._circuit_breaker.config.min_calls_before_open = 1
        mock_secret_client.get_secret.side_effect = ServiceRequestError("Unavailable")

        # Cause circuit to open
        for _ in range(5):
            with pytest.raises(ServiceRequestError):
                await credential_manager.get_credential("test-cred")

        assert credential_manager._circuit_breaker.state == CircuitState.OPEN

        # Reset mock to verify Key Vault isn't called
        mock_secret_client.get_secret.reset_mock()

        # Next request should fail immediately with CircuitBreakerOpenError
        with pytest.raises(CircuitBreakerOpenError) as exc_info:
            await credential_manager.get_credential("another-cred")

        # Verify Key Vault was NOT called (fast fail)
        assert mock_secret_client.get_secret.call_count == 0
        assert "Circuit breaker OPEN" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_credential_falls_back_to_cache_when_circuit_open(self):
        """Circuit open causes fallback to cached credential"""
        credential_manager, mock_secret_client = create_credential_manager()

        # First, populate cache with a successful fetch
        mock_secret = MagicMock()
        mock_secret.value = "cached-secret-value"
        mock_secret_client.get_secret.return_value = mock_secret

        result = await credential_manager.get_credential("test-cred")
        assert result == "cached-secret-value"

        # Now open the circuit
        credential_manager._circuit_breaker.config.min_calls_before_open = 1
        mock_secret_client.get_secret.side_effect = ServiceRequestError("Unavailable")

        for _ in range(5):
            with pytest.raises(ServiceRequestError):
                await credential_manager.get_credential("different-cred")

        assert credential_manager._circuit_breaker.state == CircuitState.OPEN

        # Try to get the cached credential (circuit is open, but cache exists)
        result = await credential_manager.get_credential("test-cred")
        assert result == "cached-secret-value"  # Should return cached value


class TestKeyVaultTimeout:
    """Test timeout enforcement on Key Vault operations

    Phase 4 (Resilience - B2-002): Verify 10-second timeout prevents hanging
    """

    @pytest.mark.asyncio
    async def test_get_credential_enforces_10_second_timeout(self):
        """get_credential times out after 10 seconds"""
        credential_manager, mock_secret_client = create_credential_manager()

        # Mock slow Key Vault response
        async def slow_response(*args, **kwargs):
            await asyncio.sleep(15)  # Exceeds timeout

        mock_secret_client.get_secret.side_effect = slow_response

        start_time = asyncio.get_event_loop().time()

        with pytest.raises(RetryableError):
            await credential_manager.get_credential("test-cred")

        elapsed = asyncio.get_event_loop().time() - start_time

        # Should timeout around 10 seconds (allow small tolerance)
        assert 9.5 < elapsed < 11.0

    @pytest.mark.asyncio
    async def test_rotate_credential_enforces_timeout(self):
        """rotate_credential times out after 10 seconds"""
        credential_manager, mock_secret_client = create_credential_manager()

        # Mock slow Key Vault set_secret
        async def slow_set(*args, **kwargs):
            await asyncio.sleep(15)

        mock_secret_client.set_secret.side_effect = slow_set

        with pytest.raises(RetryableError):
            await credential_manager.rotate_credential("test-cred", "new-value")


class TestKeyVaultRetryableErrors:
    """Test RetryableError handling for transient failures

    Phase 4 (Resilience - B2-002): Verify transient errors are marked retryable
    """

    @pytest.mark.asyncio
    async def test_timeout_raises_retryable_error(self):
        """Timeout is wrapped in RetryableError"""
        credential_manager, mock_secret_client = create_credential_manager()

        async def slow_response(*args, **kwargs):
            await asyncio.sleep(15)

        mock_secret_client.get_secret.side_effect = slow_response

        with pytest.raises(RetryableError) as exc_info:
            await credential_manager.get_credential("test-cred")

        # Verify it's a timeout-related retryable error
        assert "timeout" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_resource_not_found_not_retryable(self):
        """ResourceNotFoundError is not retryable (credential doesn't exist)"""
        credential_manager, mock_secret_client = create_credential_manager()

        mock_secret_client.get_secret.side_effect = ResourceNotFoundError(
            "Credential not found"
        )

        with pytest.raises(ResourceNotFoundError):
            await credential_manager.get_credential("nonexistent-cred")

        # Failure count should not increment for non-retryable errors
        # (circuit breaker marks this as failure, but application logic should not retry)


class TestRotateCredentialResilience:
    """Test rotate_credential resilience features

    Phase 4 (Resilience - B2-002): Verify rotation handles failures gracefully
    """

    @pytest.mark.asyncio
    async def test_rotate_credential_circuit_breaker_protection(self):
        """rotate_credential uses circuit breaker"""
        credential_manager, mock_secret_client = create_credential_manager()

        # Mock successful rotation
        mock_secret_client.set_secret.return_value = None

        result = await credential_manager.rotate_credential("test-cred", "new-value")
        assert result == "new-value"

        # Verify circuit breaker was involved (call count incremented)
        assert credential_manager._circuit_breaker.total_calls > 0

    @pytest.mark.asyncio
    async def test_rotate_credential_fails_when_circuit_open(self):
        """rotate_credential fails immediately when circuit is open"""
        credential_manager, mock_secret_client = create_credential_manager()

        # Open the circuit
        credential_manager._circuit_breaker.config.min_calls_before_open = 1
        mock_secret_client.set_secret.side_effect = ServiceRequestError("Unavailable")

        for _ in range(5):
            with pytest.raises(ServiceRequestError):
                await credential_manager.rotate_credential(f"cred-{_}", "value")

        assert credential_manager._circuit_breaker.state == CircuitState.OPEN

        # Next rotation should fail immediately
        with pytest.raises(CircuitBreakerOpenError):
            await credential_manager.rotate_credential("another-cred", "value")


class TestCircuitBreakerMetrics:
    """Test circuit breaker metrics exposure

    Phase 4 (Observability - B2-002): Verify metrics tracking for Key Vault circuit
    """

    @pytest.mark.asyncio
    async def test_circuit_breaker_tracks_call_count(self):
        """Circuit breaker tracks total calls"""
        credential_manager, mock_secret_client = create_credential_manager()

        mock_secret = MagicMock()
        mock_secret.value = "value"
        mock_secret_client.get_secret.return_value = mock_secret

        # Make 10 calls
        for i in range(10):
            await credential_manager.get_credential(f"cred-{i}")

        metrics = credential_manager._circuit_breaker.get_metrics()
        assert metrics["total_calls"] == 10
        assert metrics["name"] == "azure-key-vault"

    @pytest.mark.asyncio
    async def test_circuit_breaker_tracks_failures(self):
        """Circuit breaker tracks failure count"""
        credential_manager, mock_secret_client = create_credential_manager()

        mock_secret_client.get_secret.side_effect = ServiceRequestError("Error")

        # Make 3 failing calls
        for i in range(3):
            with pytest.raises(ServiceRequestError):
                await credential_manager.get_credential(f"cred-{i}")

        metrics = credential_manager._circuit_breaker.get_metrics()
        assert metrics["failure_count"] == 3


class TestCacheFallback:
    """Test cache fallback when Key Vault is unavailable

    Phase 4 (Resilience - B2-002): Verify graceful degradation with cache
    """

    @pytest.mark.asyncio
    async def test_cache_used_when_circuit_open(self):
        """Cache fallback works when circuit breaker is open"""
        credential_manager, mock_secret_client = create_credential_manager()

        # Populate cache
        mock_secret = MagicMock()
        mock_secret.value = "cached-value"
        mock_secret_client.get_secret.return_value = mock_secret

        result = await credential_manager.get_credential("test-cred")
        assert result == "cached-value"

        # Open circuit
        credential_manager._circuit_breaker.config.min_calls_before_open = 1
        mock_secret_client.get_secret.side_effect = ServiceRequestError("Unavailable")

        for _ in range(5):
            with pytest.raises(ServiceRequestError):
                await credential_manager.get_credential("other-cred")

        # Should use cache for previously fetched credential
        result = await credential_manager.get_credential("test-cred")
        assert result == "cached-value"

    @pytest.mark.asyncio
    async def test_no_cache_circuit_open_raises_error(self):
        """Without cache, circuit open raises CircuitBreakerOpenError"""
        credential_manager, mock_secret_client = create_credential_manager()

        # Open circuit without populating cache
        credential_manager._circuit_breaker.config.min_calls_before_open = 1
        mock_secret_client.get_secret.side_effect = ServiceRequestError("Unavailable")

        for _ in range(5):
            with pytest.raises(ServiceRequestError):
                await credential_manager.get_credential(f"cred-{_}")

        # Try to get uncached credential with circuit open
        with pytest.raises(CircuitBreakerOpenError):
            await credential_manager.get_credential("new-cred")
