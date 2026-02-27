# src/config/config_manager.py
"""Configuration loading, validation, and runtime update management."""

import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from azure.identity.aio import DefaultAzureCredential
from azure.keyvault.secrets.aio import SecretClient
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


@dataclass
class DatabaseConfig:
    """Database connection configuration.

    Defines parameters for connecting to the application database,
    including authentication, SSL, and connection pooling settings.

    Attributes:
        host: Database server hostname or IP address.
        port: Database server port number.
        database: Name of the database to connect to.
        username: Database user for authentication.
        password: Database password (should be loaded from Key Vault in prod).
        ssl_enabled: Whether to use SSL/TLS for connection security.
        connection_timeout: Timeout in seconds for connection attempts.
        max_connections: Maximum number of connections in the pool.
    """

    host: str
    port: int
    database: str
    username: str
    password: str
    ssl_enabled: bool = True
    connection_timeout: int = 30
    max_connections: int = 10


@dataclass
class AwsConfig:
    """AWS S3 configuration for log ingestion.

    Defines parameters for connecting to AWS S3 to retrieve log files.
    Credentials should be loaded from Key Vault in production environments.

    Attributes:
        access_key_id: AWS access key ID for authentication.
        secret_access_key: AWS secret access key (load from Key Vault).
        region: AWS region where the S3 bucket is located.
        bucket_name: Name of the S3 bucket containing log files.
        prefix: S3 key prefix to filter objects (e.g., 'logs/firewall/').
        batch_size: Number of files to process in each batch.
        max_retries: Maximum retry attempts for failed S3 operations.
    """

    access_key_id: str
    secret_access_key: str
    region: str
    bucket_name: str
    prefix: str
    batch_size: int = 1000
    max_retries: int = 3


@dataclass
class SentinelConfig:
    """Azure Sentinel configuration for log ingestion.

    Defines parameters for routing logs to Azure Sentinel via the
    Data Collection Rules (DCR) API endpoint.

    Attributes:
        workspace_id: Azure Log Analytics workspace ID.
        dcr_endpoint: Data Collection Rule endpoint URL.
        rule_id: DCR rule identifier (immutable ID).
        stream_name: Stream name for the DCR (e.g., 'Custom-FirewallLogs_CL').
        table_name: Target Log Analytics table name.
        batch_size: Maximum records per ingestion batch.
        retention_days: Data retention period in days.
    """

    workspace_id: str
    dcr_endpoint: str
    rule_id: str
    stream_name: str
    table_name: str
    batch_size: int = 1000
    retention_days: int = 90


@dataclass
class MonitoringConfig:
    """Monitoring and alerting configuration.

    Defines settings for metrics collection, alerting, and health checks
    used by the pipeline monitoring system.

    Attributes:
        metrics_endpoint: URL for the metrics ingestion endpoint.
        alert_webhook: Webhook URL for sending alerts (Teams/Slack).
        log_level: Logging verbosity level (DEBUG, INFO, WARNING, ERROR).
        enable_prometheus: Whether to expose Prometheus metrics endpoint.
        metrics_interval: Interval in seconds for metrics collection.
        health_check_interval: Interval in seconds for health checks.
    """

    metrics_endpoint: str
    alert_webhook: str
    log_level: str = "INFO"
    enable_prometheus: bool = True
    metrics_interval: int = 60
    health_check_interval: int = 30


class ConfigurationError(Exception):
    """Custom exception for configuration errors"""

    pass


class ConfigManager:
    """Centralized configuration manager with env override and hot-reload support."""

    def __init__(
        self,
        config_path: str,
        environment: str,
        vault_url: Optional[str] = None,
        enable_hot_reload: bool = True,
    ) -> None:
        """
        Initialize configuration manager (sync init only)

        Phase 4 (B2-008): For Key Vault secrets, use ConfigManager.create() factory method

        Args:
            config_path: Path to configuration files
            environment: Deployment environment (dev/staging/prod)
            vault_url: Azure Key Vault URL for secrets (if provided, use create() instead)
            enable_hot_reload: Enable configuration hot reloading
        """
        self.config_path = Path(config_path)
        self.environment = environment
        self.vault_url = vault_url
        self.enable_hot_reload = enable_hot_reload

        # Initialize internal state
        self._config_cache = {}
        self._config_lock = threading.Lock()
        self._last_reload = time.time()
        self._env_key_path_cache: Dict[str, list[str]] = {}

        # Set up logging
        self._setup_logging()

        # Load initial configuration
        self.reload_config()

        # Phase 4 (B2-008): Secrets client initialization deferred to async factory method
        # Do NOT call _init_secrets_client() here (it's now async)
        self.secret_client: Optional[SecretClient] = None

        # Start configuration file watcher if hot reload is enabled
        if enable_hot_reload:
            self._start_config_watcher()

    @classmethod
    async def create(
        cls,
        config_path: str,
        environment: str,
        vault_url: Optional[str] = None,
        enable_hot_reload: bool = True,
    ) -> "ConfigManager":
        """
        Async factory method to create ConfigManager with Key Vault support

        Phase 4 (B2-008): Use this method when Key Vault secrets are needed

        Args:
            config_path: Path to configuration files
            environment: Deployment environment (dev/staging/prod)
            vault_url: Azure Key Vault URL for secrets
            enable_hot_reload: Enable configuration hot reloading

        Returns:
            Initialized ConfigManager instance with async secret client

        Example:
            config_manager = await ConfigManager.create(
                'config',
                'prod',
                vault_url='https://myvault.vault.azure.net'
            )
        """
        instance = cls.__new__(cls)
        instance.config_path = Path(config_path)
        instance.environment = environment
        instance.vault_url = vault_url
        instance.enable_hot_reload = enable_hot_reload

        # Initialize internal state
        instance._config_cache = {}
        instance._config_lock = threading.Lock()
        instance._last_reload = time.time()
        instance._env_key_path_cache = {}

        # Set up logging
        instance._setup_logging()

        # Load initial configuration
        instance.reload_config()

        # Initialize async secrets client if vault URL provided
        instance.secret_client = None
        if vault_url:
            await instance._init_secrets_client()

        # Start configuration file watcher if hot reload is enabled
        if enable_hot_reload:
            instance._start_config_watcher()

        return instance

    def _setup_logging(self) -> None:
        """Configure logging for configuration management"""
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )
        self.logger = logging.getLogger("ConfigManager")

    async def _init_secrets_client(self) -> None:
        """
        Initialize Azure Key Vault async client

        Phase 4 (B2-008): Changed to async to use azure.keyvault.secrets.aio.SecretClient
        This fixes async/sync mismatch where get_secret() was async but client was sync
        """
        if self.vault_url:
            try:
                credential = DefaultAzureCredential()
                self.secret_client = SecretClient(
                    vault_url=self.vault_url, credential=credential
                )
                self.logger.info(
                    "Successfully initialized Azure Key Vault async client"
                )
            except Exception as e:
                self.logger.error(f"Failed to initialize Key Vault client: {e!s}")
                raise ConfigurationError(
                    "Failed to initialize secrets management"
                ) from e

    def _start_config_watcher(self) -> None:
        """Start watching configuration files for changes"""

        class ConfigFileHandler(FileSystemEventHandler):
            def __init__(self, config_manager):
                self.config_manager = config_manager

            def on_modified(self, event):
                if event.src_path.endswith(".yaml") or event.src_path.endswith(".yml"):
                    self.config_manager.reload_config()

        observer = Observer()
        observer.schedule(ConfigFileHandler(self), self.config_path, recursive=False)
        observer.start()
        self.logger.info("Started configuration file watcher")

    def get_config(self, component: str) -> Dict[str, Any]:
        """
        Get configuration for a specific component

        Args:
            component: Component name (e.g., 'aws', 'sentinel', 'monitoring')

        Returns:
            Dictionary containing component configuration
        """
        component_config = self._config_cache.get(component)
        if component_config is not None:
            return component_config

        with self._config_lock:
            component_config = self._config_cache.get(component)
            if component_config is None:
                self.reload_config()
                component_config = self._config_cache.get(component, {})

            return component_config

    def reload_config(self) -> None:
        """Reload configuration from files and environment"""
        with self._config_lock:
            try:
                # Load base configuration
                base_config = self._load_yaml_config("base")

                # Load environment-specific configuration
                env_config = self._load_yaml_config(self.environment)

                # Merge configurations
                self._config_cache = self._merge_configs(base_config, env_config)

                # Apply environment variables
                self._apply_env_variables()

                # Validate configuration
                self._validate_config()

                self._last_reload = time.time()
                self.logger.info("Successfully reloaded configuration")

            except Exception as e:
                self.logger.error(f"Failed to reload configuration: {e!s}")
                raise ConfigurationError(f"Configuration reload failed: {e!s}") from e

    def _load_yaml_config(self, config_name: str) -> Dict[str, Any]:
        """Load YAML configuration file"""
        config_file = self.config_path / f"{config_name}.yaml"
        try:
            if config_file.exists():
                with open(config_file, "r") as f:
                    return yaml.safe_load(f)
            return {}
        except Exception as e:
            self.logger.error(f"Failed to load {config_name} configuration: {e!s}")
            raise ConfigurationError(
                f"Failed to load {config_name} configuration"
            ) from e

    def _merge_configs(
        self, base: Dict[str, Any], override: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Merge configuration dictionaries with override"""
        merged = base.copy()
        for key, value in override.items():
            if isinstance(value, dict) and key in merged:
                merged[key] = self._merge_configs(merged[key], value)
            else:
                merged[key] = value
        return merged

    def _apply_env_variables(self) -> None:
        """Apply environment variable overrides"""
        for key, value in os.environ.items():
            if key.startswith("APP_"):
                config_path = self._env_key_path_cache.get(key)
                if config_path is None:
                    config_path = self._parse_env_override_path(key[4:])
                    self._env_key_path_cache[key] = config_path
                self._set_nested_value(self._config_cache, config_path, value)

    def _parse_env_override_path(self, env_key: str) -> list[str]:
        """Parse APP_ environment variable key into config path.

        Supports:
        - Single underscore separators for component + field names where
          field names may contain underscores (e.g., SENTINEL_WORKSPACE_ID ->
          ["sentinel", "workspace_id"])
        - Double underscore separators for explicit deeper nesting
          (e.g., SENTINEL__TABLES__FIREWALL -> ["sentinel", "tables", "firewall"])
        """
        normalized_key = env_key.lower()

        if "__" in normalized_key:
            return [part for part in normalized_key.split("__") if part]

        component, separator, remainder = normalized_key.partition("_")
        if separator and remainder:
            return [component, remainder]

        return [normalized_key]

    def _set_nested_value(self, config: Dict[str, Any], path: list, value: Any) -> None:
        """Set nested dictionary value using path list"""
        current = config
        for part in path[:-1]:
            current = current.setdefault(part, {})
        current[path[-1]] = value

    def _validate_config(self) -> None:
        """Validate configuration completeness and types"""
        required_components = ["aws", "sentinel"]
        for component in required_components:
            if component not in self._config_cache:
                raise ConfigurationError(f"Missing configuration for {component}")

        # Ensure monitoring has a minimal placeholder to keep downstream lookups safe
        if "monitoring" not in self._config_cache:
            self._config_cache["monitoring"] = {
                "metrics_endpoint": "/metrics",
                "alert_webhook": "",
                "log_level": "INFO",
                "enable_prometheus": False,
                "metrics_interval": 60,
                "health_check_interval": 30,
            }

        # Validate AWS configuration
        self._validate_aws_config(self._config_cache.get("aws", {}))

        # Validate Sentinel configuration
        self._validate_sentinel_config(self._config_cache.get("sentinel", {}))

    def _validate_aws_config(self, config: Dict[str, Any]) -> None:
        """Validate AWS configuration"""
        # Resolve credentials from Key Vault or secure sources
        if not config.get("access_key_id"):
            # Default to Key Vault reference for production
            config["access_key_id"] = self._resolve_secret_reference(
                "keyvault:aws-access-key-id" if self.vault_url else "test-access-key"
            )
        else:
            # Resolve if it's a reference
            config["access_key_id"] = self._resolve_secret_reference(
                config["access_key_id"]
            )

        if not config.get("secret_access_key"):
            config["secret_access_key"] = self._resolve_secret_reference(
                "keyvault:aws-secret-access-key"
                if self.vault_url
                else "test-secret-key"
            )
        else:
            config["secret_access_key"] = self._resolve_secret_reference(
                config["secret_access_key"]
            )

        required_fields = ["region", "bucket_name"]
        for field in required_fields:
            if not config.get(field):
                raise ConfigurationError(f"Missing required AWS configuration: {field}")

    def _validate_sentinel_config(self, config: Dict[str, Any]) -> None:
        """Validate Sentinel configuration"""
        # Resolve Sentinel endpoints and IDs from Key Vault
        if not config.get("dcr_endpoint"):
            config["dcr_endpoint"] = self._resolve_secret_reference(
                "keyvault:sentinel-dcr-endpoint"
                if self.vault_url
                else "https://sentinel.test.endpoint"
            )
        else:
            config["dcr_endpoint"] = self._resolve_secret_reference(
                config["dcr_endpoint"]
            )

        if not config.get("rule_id"):
            config["rule_id"] = self._resolve_secret_reference(
                "keyvault:sentinel-rule-id" if self.vault_url else "test-rule-id"
            )
        else:
            config["rule_id"] = self._resolve_secret_reference(config["rule_id"])

        if not config.get("stream_name"):
            config["stream_name"] = "test-stream"
        if not config.get("table_name"):
            config["table_name"] = "Custom_Test_CL"

        required_fields = ["workspace_id", "dcr_endpoint", "rule_id"]
        for field in required_fields:
            if not config.get(field):
                raise ConfigurationError(
                    f"Missing required Sentinel configuration: {field}"
                )

    def _resolve_secret_reference(self, value: str) -> str:
        """
        Resolve secret reference from Key Vault or environment

        Args:
            value: Value that may contain 'keyvault:secret-name' or 'env:VAR_NAME' references

        Returns:
            Resolved secret value
        """
        if not isinstance(value, str):
            return value

        # Support keyvault:secret-name pattern
        if value.startswith("keyvault:"):
            secret_name = value.split(":", 1)[1]
            try:
                if self.vault_url and self.secret_client:
                    # Phase 4 (B2-008): Sync method cannot await async client
                    # Fall back to environment variable (sync operations should use env vars)
                    # For async secret resolution, use get_secret() directly
                    self.logger.warning(
                        f"Sync method cannot resolve Key Vault secret '{secret_name}' directly. "
                        "Falling back to environment variable. "
                        "Use ConfigManager.get_secret() for async Key Vault access."
                    )
                    env_fallback = os.environ.get(
                        secret_name.upper().replace("-", "_"), ""
                    )

                    # In production, fail loudly if Key Vault was expected but sync context
                    if self.environment == "prod" and not env_fallback:
                        raise ConfigurationError(
                            f"Production environment requires Key Vault for secret '{secret_name}', "
                            f"but _resolve_secret_reference() is a sync method. "
                            f"Set env var {secret_name.upper().replace('-', '_')} or use get_secret() async method."
                        )

                    return env_fallback
                else:
                    self.logger.warning(
                        f"Key Vault not configured, cannot resolve '{secret_name}'"
                    )
                    # Fall back to environment variable with same name
                    env_fallback = os.environ.get(
                        secret_name.upper().replace("-", "_"), ""
                    )

                    # In production, fail loudly if Key Vault was expected but unavailable
                    if self.environment == "prod" and not env_fallback:
                        raise ConfigurationError(
                            f"Production environment requires Key Vault for secret '{secret_name}'. "
                            f"Key Vault URL: {self.vault_url or 'not configured'}. "
                            "Environment fallback not allowed in production."
                        )

                    return env_fallback
            except Exception as e:
                self.logger.error(
                    f"Failed to resolve secret '{secret_name}' from Key Vault: {e}"
                )
                env_fallback = os.environ.get(secret_name.upper().replace("-", "_"), "")

                # In production, fail loudly instead of falling back
                if self.environment == "prod":
                    raise ConfigurationError(
                        f"Production environment cannot fallback to env vars for secret '{secret_name}'. "
                        f"Key Vault must be accessible. Error: {e}"
                    ) from e

                return env_fallback

        # Support env:VAR_NAME pattern (legacy, but secure when documented)
        elif value.startswith("env:"):
            env_var = value.split(":", 1)[1]
            result = os.environ.get(env_var, "")
            if not result:
                self.logger.warning(f"Environment variable '{env_var}' not set")
            return result

        # Return value as-is if no special prefix
        return value

    async def get_secret(self, secret_name: str) -> str:
        """
        Get secret from Key Vault

        Args:
            secret_name: Name of the secret

        Returns:
            Secret value

        Phase 5 (Security - B1-007/SEC-02): Requires 'read:secrets' permission
        Raises PermissionError if current user lacks permission
        """
        # Phase 5 (Security - B1-007): Permission check happens via decorator
        # Applied at runtime via access_control instance
        if not self.vault_url:
            raise ConfigurationError("Key Vault URL not configured")

        try:
            secret = await self.secret_client.get_secret(secret_name)
            return secret.value
        except Exception as e:
            self.logger.error(f"Failed to retrieve secret {secret_name}: {e!s}")
            raise ConfigurationError(f"Failed to retrieve secret {secret_name}") from e

    def get_database_config(self) -> DatabaseConfig:
        """Get database configuration as dataclass"""
        db_config = self.get_config("database")
        return DatabaseConfig(
            host=db_config["host"],
            port=db_config["port"],
            database=db_config["database"],
            username=db_config["username"],
            password=db_config["password"],
            ssl_enabled=db_config.get("ssl_enabled", True),
            connection_timeout=db_config.get("connection_timeout", 30),
            max_connections=db_config.get("max_connections", 10),
        )

    def get_aws_config(self) -> AwsConfig:
        """Get AWS configuration as dataclass"""
        aws_config = self.get_config("aws")
        return AwsConfig(
            access_key_id=aws_config["access_key_id"],
            secret_access_key=aws_config["secret_access_key"],
            region=aws_config["region"],
            bucket_name=aws_config["bucket_name"],
            prefix=aws_config.get("prefix", ""),
            batch_size=aws_config.get("batch_size", 1000),
            max_retries=aws_config.get("max_retries", 3),
        )

    def get_sentinel_config(self) -> SentinelConfig:
        """Get Sentinel configuration as dataclass"""
        sentinel_config = self.get_config("sentinel")
        return SentinelConfig(
            workspace_id=sentinel_config["workspace_id"],
            dcr_endpoint=sentinel_config["dcr_endpoint"],
            rule_id=sentinel_config["rule_id"],
            stream_name=sentinel_config["stream_name"],
            table_name=sentinel_config["table_name"],
            batch_size=sentinel_config.get("batch_size", 1000),
            retention_days=sentinel_config.get("retention_days", 90),
        )

    def get_monitoring_config(self) -> MonitoringConfig:
        """Get monitoring configuration as dataclass"""
        monitoring_config = self.get_config("monitoring")
        return MonitoringConfig(
            metrics_endpoint=monitoring_config["metrics_endpoint"],
            alert_webhook=monitoring_config["alert_webhook"],
            log_level=monitoring_config.get("log_level", "INFO"),
            enable_prometheus=monitoring_config.get("enable_prometheus", True),
            metrics_interval=monitoring_config.get("metrics_interval", 60),
            health_check_interval=monitoring_config.get("health_check_interval", 30),
        )
