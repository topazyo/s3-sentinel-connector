# src/security/credential_manager.py
"""Key Vault-backed credential retrieval, caching, and rotation support."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from azure.core.exceptions import ResourceNotFoundError
from azure.identity.aio import (
    ChainedTokenCredential,
    DefaultAzureCredential,
    ManagedIdentityCredential,
)
from azure.keyvault.secrets.aio import SecretClient
from cryptography.fernet import Fernet

# Phase 4 (Resilience - B2-002): Circuit breaker and retry for Key Vault
from ..utils.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpenError,
)
from ..utils.error_handling import RetryableError


class CredentialManager:
    """Manages secure credential access with resilience and optional encryption."""

    def __init__(
        self,
        vault_url: str,
        cache_duration: int = 3600,
        enable_encryption: bool = True,
        encryption_secret_name: str = "credential-encryption-key",
    ) -> None:
        """
        Initialize credential manager

        Args:
            vault_url: Azure Key Vault URL
            cache_duration: Cache duration in seconds
            enable_encryption: Enable local encryption of cached credentials
        """
        self.vault_url = vault_url
        self.cache_duration = cache_duration
        self.enable_encryption = enable_encryption
        self._encryption_secret_name = encryption_secret_name

        # Initialize credential cache
        self._cache: Dict[str, str] = {}
        self._cache_times: Dict[str, datetime] = {}

        # Set up logging
        self._setup_logging()

        # Initialize Azure clients
        self._initialize_azure_clients()

        # Phase 4 (Resilience - B2-002): Circuit breaker for Key Vault
        circuit_config = CircuitBreakerConfig(
            failure_threshold=5,
            recovery_timeout=60,
            success_threshold=2,
            operation_timeout=10.0,  # 10 second timeout for Key Vault operations
        )
        self._circuit_breaker = CircuitBreaker("azure-key-vault", circuit_config)

        # Initialize encryption placeholders (key fetched lazily from Key Vault)
        self.fernet: Optional[Fernet] = None
        self._encryption_ready = False

    def _setup_logging(self):
        """Configure secure logging"""
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)

        # Ensure sensitive data isn't logged
        logging.getLogger("azure").setLevel(logging.WARNING)

    def _initialize_azure_clients(self):
        """Initialize Azure clients with fallback authentication"""
        try:
            # Chain different credential options
            credential = ChainedTokenCredential(
                ManagedIdentityCredential(), DefaultAzureCredential()
            )

            self.secret_client = SecretClient(
                vault_url=self.vault_url, credential=credential
            )

            self.logger.info("Successfully initialized Azure Key Vault client")

        except Exception as e:
            self.logger.error(
                "Failed to initialize Azure clients: %s", self._safe_error(e)
            )
            raise

    async def _ensure_encryption(self) -> None:
        """Ensure encryption key is loaded from Key Vault before cache operations."""
        if not self.enable_encryption or self._encryption_ready:
            return

        try:
            key_bytes = await self._fetch_or_create_encryption_key()
            self.fernet = Fernet(key_bytes)
            self._encryption_ready = True
        except Exception as e:
            self.logger.error(
                "Failed to initialize cache encryption: %s", self._safe_error(e)
            )
            self.enable_encryption = False

    async def get_credential(
        self, credential_name: str, force_refresh: bool = False
    ) -> str:
        """
        Get credential from cache or Key Vault with circuit breaker protection

        Phase 4 (Resilience - B2-002): Added timeout, retry, and circuit breaker

        Args:
            credential_name: Name of the credential
            force_refresh: Force refresh from Key Vault

        Returns:
            Credential value

        Raises:
            CircuitBreakerOpenError: Circuit breaker is open, Key Vault unavailable
            RetryableError: Timeout or transient Key Vault error
        """
        try:
            # Check cache first (Phase 6: Performance optimization)
            if not force_refresh and self._is_cache_valid(credential_name):
                cached = await self._get_from_cache(credential_name)
                if cached is not None:
                    return cached

            # Phase 4 (B2-002): Get from Key Vault with circuit breaker + timeout
            async def fetch_from_key_vault():
                return await self.secret_client.get_secret(credential_name)

            try:
                secret = await self._circuit_breaker.call(fetch_from_key_vault)
                value = secret.value
            except CircuitBreakerOpenError as e:
                # Phase 4 (Resilience): Circuit open, check cache as fallback
                self.logger.warning(
                    f"Key Vault circuit breaker open for credential '{credential_name}': {e}"
                )
                cached = await self._get_from_cache(credential_name)
                if cached is not None:
                    self.logger.info(
                        f"Using cached credential '{credential_name}' (circuit open)"
                    )
                    return cached
                # No cache available, re-raise
                raise
            except asyncio.TimeoutError as e:
                # Phase 4 (Resilience): Timeout, mark as retryable
                self.logger.error(
                    f"Key Vault timeout for credential '{credential_name}' "
                    f"(timeout: {self._circuit_breaker.config.operation_timeout}s)"
                )
                raise RetryableError(f"Key Vault timeout for {credential_name}") from e

            # Update cache (Phase 6: Reduce Key Vault load)
            await self._ensure_encryption()
            self._update_cache(credential_name, value)

            return value

        except CircuitBreakerOpenError:
            # Already handled above, re-raise
            raise
        except RetryableError:
            # Already handled above, re-raise
            raise
        except ResourceNotFoundError as e:
            # Phase 4 (Resilience): Non-retryable error (credential doesn't exist)
            self.logger.error(
                "Credential %s not found in Key Vault: %s",
                credential_name,
                self._safe_error(e),
            )
            raise
        except Exception as e:
            # Phase 4 (Resilience): Unexpected error, log and re-raise
            self.logger.error(
                "Failed to get credential %s: %s", credential_name, self._safe_error(e)
            )
            raise

    def _is_cache_valid(self, credential_name: str) -> bool:
        """Check if cached credential is still valid"""
        if credential_name not in self._cache_times:
            return False

        age = datetime.now(timezone.utc) - self._cache_times[credential_name]
        return age.total_seconds() < self.cache_duration

    async def _get_from_cache(self, credential_name: str) -> Optional[str]:
        """Get credential from cache with decryption if enabled."""
        cached_value = self._cache.get(credential_name)

        if cached_value is None:
            return None

        if self.enable_encryption:
            await self._ensure_encryption()
            try:
                return self.fernet.decrypt(cached_value.encode()).decode()
            except Exception as e:
                self.logger.warning(
                    "Cached credential decrypt failed for %s: %s. Refetching from Key Vault.",
                    credential_name,
                    self._safe_error(e),
                )
                return None

        return cached_value

    def _update_cache(self, credential_name: str, value: str):
        """Update cache with encryption if enabled"""
        if self.enable_encryption:
            try:
                encrypted_value = self.fernet.encrypt(value.encode()).decode()
                self._cache[credential_name] = encrypted_value
            except Exception as e:
                self.logger.error(
                    "Failed to encrypt credential %s: %s",
                    credential_name,
                    self._safe_error(e),
                )
                self._cache[credential_name] = value
        else:
            self._cache[credential_name] = value

        self._cache_times[credential_name] = datetime.now(timezone.utc)

    async def rotate_credential(
        self, credential_name: str, new_value: Optional[str] = None
    ) -> str:
        """
        Rotate credential in Key Vault with circuit breaker protection

        Phase 4 (Resilience - B2-002): Added timeout and circuit breaker

        Args:
            credential_name: Name of the credential
            new_value: Optional new value (auto-generated if not provided)

        Returns:
            New credential value
        """
        try:
            if new_value is None:
                new_value = self._generate_secure_credential()

            # Phase 4 (B2-002): Update in Key Vault with circuit breaker + timeout
            async def set_secret_with_circuit_breaker():
                return await self.secret_client.set_secret(credential_name, new_value)

            await self._circuit_breaker.call(set_secret_with_circuit_breaker)

            # Update cache
            await self._ensure_encryption()
            self._update_cache(credential_name, new_value)

            self.logger.info("Successfully rotated credential %s", credential_name)
            return new_value

        except CircuitBreakerOpenError as e:
            # Phase 4 (Resilience): Circuit open, credential rotation unavailable
            self.logger.error(
                f"Key Vault circuit breaker open during rotation of '{credential_name}': {e}"
            )
            raise
        except asyncio.TimeoutError as e:
            # Phase 4 (Resilience): Timeout during rotation
            self.logger.error(
                f"Key Vault timeout during rotation of '{credential_name}'"
            )
            raise RetryableError(f"Key Vault timeout rotating {credential_name}") from e
        except Exception as e:
            self.logger.error(
                "Failed to rotate credential %s: %s",
                credential_name,
                self._safe_error(e),
            )
            raise

    def _generate_secure_credential(self, length: int = 32) -> str:
        """Generate secure random credential"""
        import secrets
        import string

        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        return "".join(secrets.choice(alphabet) for _ in range(length))

    async def validate_credentials(self) -> Dict[str, Any]:
        """Validate all cached credentials"""
        validation_results = {"valid": [], "invalid": [], "errors": []}

        for credential_name in self._cache:
            try:
                # Attempt to get credential from Key Vault
                vault_value = await self.secret_client.get_secret(credential_name)
                cached_value = await self._get_from_cache(credential_name)

                if cached_value is not None and vault_value.value == cached_value:
                    validation_results["valid"].append(credential_name)
                else:
                    validation_results["invalid"].append(credential_name)

            except Exception as e:
                validation_results["errors"].append(
                    {"credential": credential_name, "error": self._safe_error(e)}
                )

        return validation_results

    async def _fetch_or_create_encryption_key(self) -> bytes:
        """Fetch encryption key from Key Vault; create it if missing."""
        try:
            secret = await self.secret_client.get_secret(self._encryption_secret_name)
            if not secret.value:
                raise ValueError("Encryption key secret is empty")
            return secret.value.encode()
        except Exception as e:
            self.logger.warning(
                "Encryption key %s missing or inaccessible (%s); generating new key.",
                self._encryption_secret_name,
                self._safe_error(e),
            )
            key = Fernet.generate_key()
            try:
                await self.secret_client.set_secret(
                    self._encryption_secret_name, key.decode()
                )
            except Exception as write_error:
                self.logger.error(
                    "Failed to persist generated encryption key to Key Vault: %s",
                    self._safe_error(write_error),
                )
                raise
            return key

    def _redact_path_from_error(self, msg: str) -> str:
        """
        Redact file paths from error messages to prevent information disclosure.

        Phase 2 (Consistency - B2-010): Redacts system file paths from error messages

        Examples:
            "FileNotFoundError: /etc/app/keys/secret.key not found"
            → "FileNotFoundError: [PATH]/secret.key not found"

            "PermissionError: C:\\Users\\app\\config.yaml access denied"
            → "PermissionError: [PATH]/config.yaml access denied"

        Args:
            msg: Error message potentially containing file paths

        Returns:
            Error message with file paths redacted to [PATH]/filename
        """
        import re

        # Pattern 1: Unix absolute paths (/path/to/file.ext)
        # Requires file with extension to avoid matching URLs
        # Negative lookbehind ensures not part of URL (://path)
        msg = re.sub(r"(?<![:/])(/[\w\-./]+/[\w\-.]+\.[\w]+)", r"[PATH]/\1", msg)
        # Extract just filename from the replacement (fix the pattern)
        msg = re.sub(r"\[PATH\](/[\w\-./]+/)([\w\-.]+)", r"[PATH]/\2", msg)

        # Pattern 2: Windows absolute paths (C:\path\to\file.ext)
        msg = re.sub(r"([A-Z]:\\[\w\\\-./]+\\([\w\-.]+))", r"[PATH]/\2", msg)

        # Pattern 3: Windows paths with forward slashes (C:/path/to/file.ext)
        msg = re.sub(r"([A-Z]:/([\w/\-./]+/)([\w\-.]+))", r"[PATH]/\3", msg)

        return msg

    def _safe_error(self, err: Exception) -> str:
        """
        Redact potentially sensitive content from error messages.

        Phase 2 (Consistency - B2-010): Redacts file paths to prevent information disclosure
        """
        msg = str(err)

        # Phase 2 (B2-010): Redact file paths from error messages
        msg = self._redact_path_from_error(msg)

        # Truncate if too long
        if len(msg) > 500:
            return msg[:500] + "..."
        return msg
