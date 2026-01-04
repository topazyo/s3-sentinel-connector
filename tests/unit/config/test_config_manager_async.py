# tests/unit/config/test_config_manager_async.py

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest
import yaml
from azure.core.exceptions import ResourceNotFoundError

from src.config.config_manager import ConfigManager, ConfigurationError


class TestConfigManagerAsyncFactory:
    """Test ConfigManager.create() async factory method"""

    @pytest.mark.asyncio
    async def test_create_factory_without_vault(self, tmp_path):
        """Test async factory creates ConfigManager without Key Vault"""
        # Create test config files
        base_config = {
            "aws": {
                "region": "us-east-1",
                "bucket_name": "test-bucket",
                "access_key_id": "test-key",
                "secret_access_key": "test-secret",
            },
            "sentinel": {
                "workspace_id": "test-workspace",
                "dcr_endpoint": "https://test.endpoint",
                "rule_id": "test-rule",
                "stream_name": "test-stream",
                "table_name": "Custom_Test_CL",
            },
        }

        base_config_path = tmp_path / "base.yaml"
        with open(base_config_path, "w") as f:
            yaml.dump(base_config, f)

        dev_config_path = tmp_path / "dev.yaml"
        with open(dev_config_path, "w") as f:
            yaml.dump({}, f)

        # Create ConfigManager via async factory (no vault_url)
        config_manager = await ConfigManager.create(
            config_path=str(tmp_path),
            environment="dev",
            vault_url=None,
            enable_hot_reload=False,
        )

        assert config_manager is not None
        assert config_manager.secret_client is None
        assert config_manager.environment == "dev"
        assert config_manager.vault_url is None

    @pytest.mark.asyncio
    async def test_create_factory_with_vault(self, tmp_path):
        """Test async factory initializes Key Vault client"""
        # Create test config files
        base_config = {
            "aws": {
                "region": "us-east-1",
                "bucket_name": "test-bucket",
                "access_key_id": "test-key",
                "secret_access_key": "test-secret",
            },
            "sentinel": {
                "workspace_id": "test-workspace",
                "dcr_endpoint": "https://test.endpoint",
                "rule_id": "test-rule",
                "stream_name": "test-stream",
                "table_name": "Custom_Test_CL",
            },
        }

        base_config_path = tmp_path / "base.yaml"
        with open(base_config_path, "w") as f:
            yaml.dump(base_config, f)

        dev_config_path = tmp_path / "dev.yaml"
        with open(dev_config_path, "w") as f:
            yaml.dump({}, f)

        # Mock async SecretClient
        with (
            patch("src.config.config_manager.SecretClient") as mock_client_class,
            patch("src.config.config_manager.DefaultAzureCredential"),
        ):
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client

            # Create ConfigManager via async factory with vault_url
            config_manager = await ConfigManager.create(
                config_path=str(tmp_path),
                environment="dev",
                vault_url="https://test.vault.azure.net",
                enable_hot_reload=False,
            )

            assert config_manager is not None
            assert config_manager.secret_client is not None
            assert config_manager.vault_url == "https://test.vault.azure.net"
            mock_client_class.assert_called_once()


class TestConfigManagerAsyncGetSecret:
    """Test ConfigManager.get_secret() with async client"""

    @pytest.mark.asyncio
    async def test_get_secret_success(self, tmp_path):
        """Test get_secret() successfully retrieves secret from async client"""
        # Create test config files
        base_config = {
            "aws": {
                "region": "us-east-1",
                "bucket_name": "test-bucket",
                "access_key_id": "test-key",
                "secret_access_key": "test-secret",
            },
            "sentinel": {
                "workspace_id": "test-workspace",
                "dcr_endpoint": "https://test.endpoint",
                "rule_id": "test-rule",
                "stream_name": "test-stream",
                "table_name": "Custom_Test_CL",
            },
        }

        base_config_path = tmp_path / "base.yaml"
        with open(base_config_path, "w") as f:
            yaml.dump(base_config, f)

        dev_config_path = tmp_path / "dev.yaml"
        with open(dev_config_path, "w") as f:
            yaml.dump({}, f)

        # Mock async SecretClient
        with (
            patch("src.config.config_manager.SecretClient") as mock_client_class,
            patch("src.config.config_manager.DefaultAzureCredential"),
        ):
            mock_client = AsyncMock()
            mock_secret = Mock()
            mock_secret.value = "test-secret-value"
            mock_client.get_secret = AsyncMock(return_value=mock_secret)
            mock_client_class.return_value = mock_client

            config_manager = await ConfigManager.create(
                config_path=str(tmp_path),
                environment="dev",
                vault_url="https://test.vault.azure.net",
                enable_hot_reload=False,
            )

            # Test get_secret() with async client
            secret_value = await config_manager.get_secret("test-secret")

            assert secret_value == "test-secret-value"
            mock_client.get_secret.assert_called_once_with("test-secret")

    @pytest.mark.asyncio
    async def test_get_secret_not_found(self, tmp_path):
        """Test get_secret() handles ResourceNotFoundError"""
        base_config = {
            "aws": {
                "region": "us-east-1",
                "bucket_name": "test-bucket",
                "access_key_id": "test-key",
                "secret_access_key": "test-secret",
            },
            "sentinel": {
                "workspace_id": "test-workspace",
                "dcr_endpoint": "https://test.endpoint",
                "rule_id": "test-rule",
                "stream_name": "test-stream",
                "table_name": "Custom_Test_CL",
            },
        }

        base_config_path = tmp_path / "base.yaml"
        with open(base_config_path, "w") as f:
            yaml.dump(base_config, f)

        dev_config_path = tmp_path / "dev.yaml"
        with open(dev_config_path, "w") as f:
            yaml.dump({}, f)

        with (
            patch("src.config.config_manager.SecretClient") as mock_client_class,
            patch("src.config.config_manager.DefaultAzureCredential"),
        ):
            mock_client = AsyncMock()
            mock_client.get_secret = AsyncMock(
                side_effect=ResourceNotFoundError("Secret not found")
            )
            mock_client_class.return_value = mock_client

            config_manager = await ConfigManager.create(
                config_path=str(tmp_path),
                environment="dev",
                vault_url="https://test.vault.azure.net",
                enable_hot_reload=False,
            )

            with pytest.raises(ConfigurationError) as exc_info:
                await config_manager.get_secret("nonexistent-secret")

            assert "Failed to retrieve secret" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_secret_no_vault_url(self, tmp_path):
        """Test get_secret() raises error when vault_url not configured"""
        base_config = {
            "aws": {
                "region": "us-east-1",
                "bucket_name": "test-bucket",
                "access_key_id": "test-key",
                "secret_access_key": "test-secret",
            },
            "sentinel": {
                "workspace_id": "test-workspace",
                "dcr_endpoint": "https://test.endpoint",
                "rule_id": "test-rule",
                "stream_name": "test-stream",
                "table_name": "Custom_Test_CL",
            },
        }

        base_config_path = tmp_path / "base.yaml"
        with open(base_config_path, "w") as f:
            yaml.dump(base_config, f)

        dev_config_path = tmp_path / "dev.yaml"
        with open(dev_config_path, "w") as f:
            yaml.dump({}, f)

        config_manager = await ConfigManager.create(
            config_path=str(tmp_path),
            environment="dev",
            vault_url=None,
            enable_hot_reload=False,
        )

        with pytest.raises(ConfigurationError) as exc_info:
            await config_manager.get_secret("test-secret")

        assert "Key Vault URL not configured" in str(exc_info.value)


class TestConfigManagerAsyncSyncCompatibility:
    """Test ConfigManager async/sync compatibility"""

    def test_sync_init_still_works(self, tmp_path):
        """Test synchronous __init__ still works (backward compatibility)"""
        base_config = {
            "aws": {
                "region": "us-east-1",
                "bucket_name": "test-bucket",
                "access_key_id": "test-key",
                "secret_access_key": "test-secret",
            },
            "sentinel": {
                "workspace_id": "test-workspace",
                "dcr_endpoint": "https://test.endpoint",
                "rule_id": "test-rule",
                "stream_name": "test-stream",
                "table_name": "Custom_Test_CL",
            },
        }

        base_config_path = tmp_path / "base.yaml"
        with open(base_config_path, "w") as f:
            yaml.dump(base_config, f)

        dev_config_path = tmp_path / "dev.yaml"
        with open(dev_config_path, "w") as f:
            yaml.dump({}, f)

        # Test sync init (no vault_url for backward compatibility)
        config_manager = ConfigManager(
            config_path=str(tmp_path),
            environment="dev",
            vault_url=None,
            enable_hot_reload=False,
        )

        assert config_manager is not None
        assert config_manager.secret_client is None
        assert config_manager.environment == "dev"

    @pytest.mark.asyncio
    async def test_resolve_secret_reference_with_async_client(
        self, tmp_path, monkeypatch
    ):
        """Test _resolve_secret_reference uses env fallback in sync context (async client cannot be awaited)"""
        base_config = {
            "aws": {
                "region": "us-east-1",
                "bucket_name": "test-bucket",
                "access_key_id": "keyvault:aws-access-key",  # Key Vault reference
                "secret_access_key": "test-secret",
            },
            "sentinel": {
                "workspace_id": "test-workspace",
                "dcr_endpoint": "https://test.endpoint",
                "rule_id": "test-rule",
                "stream_name": "test-stream",
                "table_name": "Custom_Test_CL",
            },
        }

        base_config_path = tmp_path / "base.yaml"
        with open(base_config_path, "w") as f:
            yaml.dump(base_config, f)

        dev_config_path = tmp_path / "dev.yaml"
        with open(dev_config_path, "w") as f:
            yaml.dump({}, f)

        # Set environment variable fallback (sync methods use env vars)
        monkeypatch.setenv("AWS_ACCESS_KEY", "env-fallback-key")

        with (
            patch("src.config.config_manager.SecretClient") as mock_client_class,
            patch("src.config.config_manager.DefaultAzureCredential"),
        ):
            mock_client = AsyncMock()
            mock_secret = Mock()
            mock_secret.value = "resolved-key-from-vault"
            mock_client.get_secret = AsyncMock(return_value=mock_secret)
            mock_client_class.return_value = mock_client

            config_manager = await ConfigManager.create(
                config_path=str(tmp_path),
                environment="dev",
                vault_url="https://test.vault.azure.net",
                enable_hot_reload=False,
            )

            # Phase 4 (B2-008): Sync method _resolve_secret_reference falls back to env var
            # (cannot await async client in sync context)
            resolved_value = config_manager._resolve_secret_reference(
                "keyvault:aws-access-key"
            )

            assert (
                resolved_value == "env-fallback-key"
            )  # Falls back to env var in sync context

            # For async Key Vault access, use get_secret() directly
            async_resolved_value = await config_manager.get_secret("aws-access-key")
            assert async_resolved_value == "resolved-key-from-vault"


class TestConfigManagerAsyncClientIsolation:
    """Test async client isolation from sync operations"""

    @pytest.mark.asyncio
    async def test_concurrent_get_secret_calls(self, tmp_path):
        """Test concurrent async get_secret() calls are properly isolated"""
        base_config = {
            "aws": {
                "region": "us-east-1",
                "bucket_name": "test-bucket",
                "access_key_id": "test-key",
                "secret_access_key": "test-secret",
            },
            "sentinel": {
                "workspace_id": "test-workspace",
                "dcr_endpoint": "https://test.endpoint",
                "rule_id": "test-rule",
                "stream_name": "test-stream",
                "table_name": "Custom_Test_CL",
            },
        }

        base_config_path = tmp_path / "base.yaml"
        with open(base_config_path, "w") as f:
            yaml.dump(base_config, f)

        dev_config_path = tmp_path / "dev.yaml"
        with open(dev_config_path, "w") as f:
            yaml.dump({}, f)

        with (
            patch("src.config.config_manager.SecretClient") as mock_client_class,
            patch("src.config.config_manager.DefaultAzureCredential"),
        ):
            mock_client = AsyncMock()

            async def mock_get_secret(name):
                await asyncio.sleep(0.01)  # Simulate I/O delay
                mock_secret = Mock()
                mock_secret.value = f"secret-value-{name}"
                return mock_secret

            mock_client.get_secret = mock_get_secret
            mock_client_class.return_value = mock_client

            config_manager = await ConfigManager.create(
                config_path=str(tmp_path),
                environment="dev",
                vault_url="https://test.vault.azure.net",
                enable_hot_reload=False,
            )

            # Concurrent calls to get_secret()
            results = await asyncio.gather(
                config_manager.get_secret("secret1"),
                config_manager.get_secret("secret2"),
                config_manager.get_secret("secret3"),
            )

            assert results == [
                "secret-value-secret1",
                "secret-value-secret2",
                "secret-value-secret3",
            ]


class TestConfigManagerEdgeCases:
    """Test ConfigManager edge cases with async client"""

    @pytest.mark.asyncio
    async def test_factory_init_failure_handled(self, tmp_path):
        """Test factory handles Key Vault initialization failure"""
        base_config = {
            "aws": {
                "region": "us-east-1",
                "bucket_name": "test-bucket",
                "access_key_id": "test-key",
                "secret_access_key": "test-secret",
            },
            "sentinel": {
                "workspace_id": "test-workspace",
                "dcr_endpoint": "https://test.endpoint",
                "rule_id": "test-rule",
                "stream_name": "test-stream",
                "table_name": "Custom_Test_CL",
            },
        }

        base_config_path = tmp_path / "base.yaml"
        with open(base_config_path, "w") as f:
            yaml.dump(base_config, f)

        dev_config_path = tmp_path / "dev.yaml"
        with open(dev_config_path, "w") as f:
            yaml.dump({}, f)

        with (
            patch("src.config.config_manager.SecretClient"),
            patch(
                "src.config.config_manager.DefaultAzureCredential",
                side_effect=Exception("Auth failed"),
            ),
        ):

            with pytest.raises(ConfigurationError) as exc_info:
                await ConfigManager.create(
                    config_path=str(tmp_path),
                    environment="dev",
                    vault_url="https://test.vault.azure.net",
                    enable_hot_reload=False,
                )

            assert "Failed to initialize secrets management" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_resolve_secret_reference_env_fallback(self, tmp_path, monkeypatch):
        """Test _resolve_secret_reference falls back to env var when Key Vault unavailable (dev only)"""
        base_config = {
            "aws": {
                "region": "us-east-1",
                "bucket_name": "test-bucket",
                "access_key_id": "keyvault:aws-access-key",
                "secret_access_key": "test-secret",
            },
            "sentinel": {
                "workspace_id": "test-workspace",
                "dcr_endpoint": "https://test.endpoint",
                "rule_id": "test-rule",
                "stream_name": "test-stream",
                "table_name": "Custom_Test_CL",
            },
        }

        base_config_path = tmp_path / "base.yaml"
        with open(base_config_path, "w") as f:
            yaml.dump(base_config, f)

        dev_config_path = tmp_path / "dev.yaml"
        with open(dev_config_path, "w") as f:
            yaml.dump({}, f)

        # Set environment variable fallback
        monkeypatch.setenv("AWS_ACCESS_KEY", "env-fallback-key")

        with (
            patch("src.config.config_manager.SecretClient") as mock_client_class,
            patch("src.config.config_manager.DefaultAzureCredential"),
        ):
            mock_client = AsyncMock()
            mock_client.get_secret = AsyncMock(
                side_effect=Exception("Key Vault unavailable")
            )
            mock_client_class.return_value = mock_client

            config_manager = await ConfigManager.create(
                config_path=str(tmp_path),
                environment="dev",  # Dev environment allows fallback
                vault_url="https://test.vault.azure.net",
                enable_hot_reload=False,
            )

            # Fallback to environment variable in dev
            resolved_value = config_manager._resolve_secret_reference(
                "keyvault:aws-access-key"
            )

            assert resolved_value == "env-fallback-key"
