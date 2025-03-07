# src/config/config_manager.py

import yaml
import os
import json
from typing import Dict, Any, Optional, Union
from pathlib import Path
from dataclasses import dataclass
from azure.keyvault.secrets import SecretClient
from azure.identity import DefaultAzureCredential
import logging
from functools import lru_cache
import threading
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

@dataclass
class DatabaseConfig:
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
    access_key_id: str
    secret_access_key: str
    region: str
    bucket_name: str
    prefix: str
    batch_size: int = 1000
    max_retries: int = 3

@dataclass
class SentinelConfig:
    workspace_id: str
    dcr_endpoint: str
    rule_id: str
    stream_name: str
    table_name: str
    batch_size: int = 1000
    retention_days: int = 90

@dataclass
class MonitoringConfig:
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
    def __init__(self, 
                 config_path: str,
                 environment: str,
                 vault_url: Optional[str] = None,
                 enable_hot_reload: bool = True):
        """
        Initialize configuration manager
        
        Args:
            config_path: Path to configuration files
            environment: Deployment environment (dev/staging/prod)
            vault_url: Azure Key Vault URL for secrets
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
        
        # Set up logging
        self._setup_logging()
        
        # Load initial configuration
        self.reload_config()
        
        # Initialize secrets client if vault URL provided
        self._init_secrets_client()
        
        # Start configuration file watcher if hot reload is enabled
        if enable_hot_reload:
            self._start_config_watcher()

    def _setup_logging(self) -> None:
        """Configure logging for configuration management"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger('ConfigManager')

    def _init_secrets_client(self) -> None:
        """Initialize Azure Key Vault client"""
        if self.vault_url:
            try:
                credential = DefaultAzureCredential()
                self.secret_client = SecretClient(
                    vault_url=self.vault_url,
                    credential=credential
                )
                self.logger.info("Successfully initialized Azure Key Vault client")
            except Exception as e:
                self.logger.error(f"Failed to initialize Key Vault client: {str(e)}")
                raise ConfigurationError("Failed to initialize secrets management")

    def _start_config_watcher(self) -> None:
        """Start watching configuration files for changes"""
        class ConfigFileHandler(FileSystemEventHandler):
            def __init__(self, config_manager):
                self.config_manager = config_manager

            def on_modified(self, event):
                if event.src_path.endswith('.yaml') or event.src_path.endswith('.yml'):
                    self.config_manager.reload_config()

        observer = Observer()
        observer.schedule(ConfigFileHandler(self), self.config_path, recursive=False)
        observer.start()
        self.logger.info("Started configuration file watcher")

    @lru_cache(maxsize=1)
    def get_config(self, component: str) -> Dict[str, Any]:
        """
        Get configuration for a specific component
        
        Args:
            component: Component name (e.g., 'aws', 'sentinel', 'monitoring')
            
        Returns:
            Dictionary containing component configuration
        """
        with self._config_lock:
            if component not in self._config_cache:
                self.reload_config()
            return self._config_cache.get(component, {})

    def reload_config(self) -> None:
        """Reload configuration from files and environment"""
        with self._config_lock:
            try:
                # Load base configuration
                base_config = self._load_yaml_config('base')
                
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
                self.logger.error(f"Failed to reload configuration: {str(e)}")
                raise ConfigurationError(f"Configuration reload failed: {str(e)}")

    def _load_yaml_config(self, config_name: str) -> Dict[str, Any]:
        """Load YAML configuration file"""
        config_file = self.config_path / f"{config_name}.yaml"
        try:
            if config_file.exists():
                with open(config_file, 'r') as f:
                    return yaml.safe_load(f)
            return {}
        except Exception as e:
            self.logger.error(f"Failed to load {config_name} configuration: {str(e)}")
            raise ConfigurationError(f"Failed to load {config_name} configuration")

    def _merge_configs(self, base: Dict[str, Any], 
                      override: Dict[str, Any]) -> Dict[str, Any]:
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
            if key.startswith('APP_'):
                config_path = key[4:].lower().split('_')
                self._set_nested_value(self._config_cache, config_path, value)

    def _set_nested_value(self, config: Dict[str, Any], 
                         path: list, value: Any) -> None:
        """Set nested dictionary value using path list"""
        current = config
        for part in path[:-1]:
            current = current.setdefault(part, {})
        current[path[-1]] = value

    def _validate_config(self) -> None:
        """Validate configuration completeness and types"""
        required_components = ['aws', 'sentinel', 'monitoring']
        for component in required_components:
            if component not in self._config_cache:
                raise ConfigurationError(f"Missing configuration for {component}")
            
        # Validate AWS configuration
        self._validate_aws_config(self._config_cache.get('aws', {}))
        
        # Validate Sentinel configuration
        self._validate_sentinel_config(self._config_cache.get('sentinel', {}))

    def _validate_aws_config(self, config: Dict[str, Any]) -> None:
        """Validate AWS configuration"""
        required_fields = ['access_key_id', 'secret_access_key', 'region', 'bucket_name']
        for field in required_fields:
            if not config.get(field):
                raise ConfigurationError(f"Missing required AWS configuration: {field}")

    def _validate_sentinel_config(self, config: Dict[str, Any]) -> None:
        """Validate Sentinel configuration"""
        required_fields = ['workspace_id', 'dcr_endpoint', 'rule_id']
        for field in required_fields:
            if not config.get(field):
                raise ConfigurationError(f"Missing required Sentinel configuration: {field}")

    async def get_secret(self, secret_name: str) -> str:
        """
        Get secret from Key Vault
        
        Args:
            secret_name: Name of the secret
            
        Returns:
            Secret value
        """
        if not self.vault_url:
            raise ConfigurationError("Key Vault URL not configured")
            
        try:
            secret = await self.secret_client.get_secret(secret_name)
            return secret.value
        except Exception as e:
            self.logger.error(f"Failed to retrieve secret {secret_name}: {str(e)}")
            raise ConfigurationError(f"Failed to retrieve secret {secret_name}")

    def get_database_config(self) -> DatabaseConfig:
        """Get database configuration as dataclass"""
        db_config = self.get_config('database')
        return DatabaseConfig(
            host=db_config['host'],
            port=db_config['port'],
            database=db_config['database'],
            username=db_config['username'],
            password=db_config['password'],
            ssl_enabled=db_config.get('ssl_enabled', True),
            connection_timeout=db_config.get('connection_timeout', 30),
            max_connections=db_config.get('max_connections', 10)
        )

    def get_aws_config(self) -> AwsConfig:
        """Get AWS configuration as dataclass"""
        aws_config = self.get_config('aws')
        return AwsConfig(
            access_key_id=aws_config['access_key_id'],
            secret_access_key=aws_config['secret_access_key'],
            region=aws_config['region'],
            bucket_name=aws_config['bucket_name'],
            prefix=aws_config.get('prefix', ''),
            batch_size=aws_config.get('batch_size', 1000),
            max_retries=aws_config.get('max_retries', 3)
        )

    def get_sentinel_config(self) -> SentinelConfig:
        """Get Sentinel configuration as dataclass"""
        sentinel_config = self.get_config('sentinel')
        return SentinelConfig(
            workspace_id=sentinel_config['workspace_id'],
            dcr_endpoint=sentinel_config['dcr_endpoint'],
            rule_id=sentinel_config['rule_id'],
            stream_name=sentinel_config['stream_name'],
            table_name=sentinel_config['table_name'],
            batch_size=sentinel_config.get('batch_size', 1000),
            retention_days=sentinel_config.get('retention_days', 90)
        )

    def get_monitoring_config(self) -> MonitoringConfig:
        """Get monitoring configuration as dataclass"""
        monitoring_config = self.get_config('monitoring')
        return MonitoringConfig(
            metrics_endpoint=monitoring_config['metrics_endpoint'],
            alert_webhook=monitoring_config['alert_webhook'],
            log_level=monitoring_config.get('log_level', 'INFO'),
            enable_prometheus=monitoring_config.get('enable_prometheus', True),
            metrics_interval=monitoring_config.get('metrics_interval', 60),
            health_check_interval=monitoring_config.get('health_check_interval', 30)
        )