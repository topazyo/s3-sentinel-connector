# src/security/__init__.py
"""Security subsystem composition for auth, secrets, validation, and encryption."""

import logging
from typing import Any, Dict

import yaml

from .access_control import AccessControl
from .audit import AuditLogger
from .config_validator import ConfigurationValidator
from .credential_manager import CredentialManager
from .encryption import EncryptionManager
from .permission_enforcer import PermissionEnforcer
from .rotation_manager import RotationManager

__all__ = [
    "AccessControl",
    "AuditLogger",
    "ConfigurationValidator",
    "CredentialManager",
    "EncryptionManager",
    "PermissionEnforcer",
    "RotationManager",
    "SecurityManager",
]


class SecurityManager:
    """Central security management class"""

    def __init__(self, config_path: str | Dict[str, Any]) -> None:
        """
        Initialize security components (sync init only - JWT from env)

        For Key Vault JWT secrets, use SecurityManager.create() instead.

        Args:
            config_path: Path to security configuration file OR dict with config (for testing)
        """
        # Support both config dict (for tests) and path (for production)
        if isinstance(config_path, dict):
            self.config = config_path
        else:
            self.config = self._load_config(config_path)
        self.logger = logging.getLogger(__name__)

        # Initialize security components (will use env vars for secrets)
        self._initialize_components()

    @classmethod
    async def create(cls, config_path: str) -> "SecurityManager":
        """
        Async factory method to create SecurityManager with Key Vault support

        This method should be used when JWT secrets are stored in Key Vault.

        Args:
            config_path: Path to security configuration

        Returns:
            Initialized SecurityManager instance

        Example:
            security_manager = await SecurityManager.create('config/security.yaml')
        """
        instance = cls.__new__(cls)
        instance.config = instance._load_config(config_path)
        instance.logger = logging.getLogger(__name__)

        # Initialize components with async credential resolution
        await instance._initialize_components_async()

        return instance

    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Load security configuration"""
        try:
            with open(config_path) as f:
                return yaml.safe_load(f)
        except Exception as e:
            raise RuntimeError(f"Failed to load security config: {e!s}") from e

    def _initialize_components(self):
        """
        Initialize all security components (sync version - env vars only)

        This method does NOT support Key Vault JWT secrets.
        Use create() factory method for Key Vault support.
        """
        try:
            # Initialize credential management
            self.credential_manager = CredentialManager(
                vault_url=self.config["azure"]["key_vault_url"],
                cache_duration=self.config["credentials"]["cache_duration"],
                enable_encryption=self.config["credentials"]["enable_encryption"],
            )

            # Initialize configuration validation
            self.config_validator = ConfigurationValidator(
                policy=self.config["security_policy"]
            )

            # Initialize credential rotation
            self.rotation_manager = RotationManager(
                credential_manager=self.credential_manager,
                rotation_config=self.config["rotation"],
            )

            # Initialize encryption
            self.encryption_manager = EncryptionManager(
                key_store_path=self.config["encryption"]["key_store_path"]
            )

            # Initialize audit logging
            self.audit_logger = AuditLogger(log_path=self.config["audit"]["log_path"])

            # Initialize access control - sync init only supports env vars
            jwt_secret_ref = self.config["access_control"].get(
                "jwt_secret", "env:JWT_SECRET"
            )

            if jwt_secret_ref.startswith("keyvault:"):
                raise RuntimeError(
                    "SecurityManager.__init__() does not support Key Vault JWT secrets. "
                    "Use await SecurityManager.create() factory method instead, or use 'env:JWT_SECRET'."
                )

            # Resolve from environment variable
            if jwt_secret_ref.startswith("env:"):
                import os

                env_var = jwt_secret_ref.split(":", 1)[1]
                resolved_jwt_secret = os.environ.get(env_var)
                if not resolved_jwt_secret:
                    raise RuntimeError(
                        f"Environment variable '{env_var}' not set. "
                        "JWT secret is required for access control initialization."
                    )
            else:
                # Phase 5 (Security - B1-005/SEC-06): Block plain-text JWT in production
                import os

                app_env = os.environ.get("APP_ENV", "development").lower()

                if app_env == "production":
                    raise RuntimeError(
                        "Plain-text JWT secrets are not allowed in production. "
                        "Use 'env:JWT_SECRET' or 'keyvault:jwt-secret' format. "
                        "Current format is insecure and exposes credentials in config files."
                    )

                # Plain text allowed in dev/test (with warning)
                self.logger.warning(
                    "JWT secret is stored in plain text in config file. "
                    "This is insecure and only allowed in non-production environments. "
                    "Use 'keyvault:jwt-secret' or 'env:JWT_SECRET' instead."
                )
                resolved_jwt_secret = jwt_secret_ref

            self.access_control = AccessControl(jwt_secret=resolved_jwt_secret)

            # Phase 5 (Security - B1-007/SEC-02): Initialize permission enforcer
            self.permission_enforcer = PermissionEnforcer(self.access_control)

            # Apply permission checks to sensitive operations
            self.permission_enforcer.enforce_permissions(
                config_manager=None,  # Will be applied when ConfigManager is created
                encryption_manager=self.encryption_manager,
                s3_handler=None,  # Will be applied when S3Handler is created
                credential_manager=self.credential_manager,
            )

            self.logger.info("Security components initialized successfully")

        except Exception as e:
            self.logger.error(f"Failed to initialize security components: {e!s}")
            raise

    async def _initialize_components_async(self):
        """Initialize all security components (async version - supports Key Vault)"""
        try:
            # Initialize credential management
            self.credential_manager = CredentialManager(
                vault_url=self.config["azure"]["key_vault_url"],
                cache_duration=self.config["credentials"]["cache_duration"],
                enable_encryption=self.config["credentials"]["enable_encryption"],
            )

            # Initialize configuration validation
            self.config_validator = ConfigurationValidator(
                policy=self.config["security_policy"]
            )

            # Initialize credential rotation
            self.rotation_manager = RotationManager(
                credential_manager=self.credential_manager,
                rotation_config=self.config["rotation"],
            )

            # Initialize encryption
            self.encryption_manager = EncryptionManager(
                key_store_path=self.config["encryption"]["key_store_path"]
            )

            # Initialize audit logging
            self.audit_logger = AuditLogger(log_path=self.config["audit"]["log_path"])

            # Initialize access control with async JWT secret resolution
            jwt_secret_ref = self.config["access_control"].get(
                "jwt_secret", "keyvault:jwt-secret"
            )

            # Resolve the secret
            resolved_jwt_secret = jwt_secret_ref
            if jwt_secret_ref.startswith("keyvault:"):
                secret_name = jwt_secret_ref.split(":", 1)[1]
                try:
                    resolved_jwt_secret = await self.credential_manager.get_credential(
                        secret_name
                    )
                except Exception as e:
                    self.logger.error(f"Failed to load JWT secret from Key Vault: {e}")
                    raise RuntimeError(
                        f"Cannot initialize SecurityManager: {e}. "
                        "Ensure JWT secret is accessible via Key Vault."
                    ) from e
            elif jwt_secret_ref.startswith("env:"):
                import os

                env_var = jwt_secret_ref.split(":", 1)[1]
                resolved_jwt_secret = os.environ.get(env_var)
                if not resolved_jwt_secret:
                    raise RuntimeError(
                        f"Environment variable '{env_var}' not set. "
                        "JWT secret is required for access control initialization."
                    )
            else:
                # Plain text (insecure but allowed)
                self.logger.warning(
                    "JWT secret is stored in plain text in config file. "
                    "Use 'keyvault:jwt-secret' or 'env:JWT_SECRET' instead."
                )

            self.access_control = AccessControl(jwt_secret=resolved_jwt_secret)

            # Phase 5 (Security - B1-007/SEC-02): Initialize permission enforcer
            self.permission_enforcer = PermissionEnforcer(self.access_control)

            # Apply permission checks to sensitive operations
            self.permission_enforcer.enforce_permissions(
                config_manager=None,  # Will be applied when ConfigManager is created
                encryption_manager=self.encryption_manager,
                s3_handler=None,  # Will be applied when S3Handler is created
                credential_manager=self.credential_manager,
            )

            self.logger.info("Security components initialized successfully (async)")

        except Exception as e:
            self.logger.error(f"Failed to initialize security components: {e!s}")
            raise

    def validate_security_config(self) -> Dict[str, Any]:
        """Validate current security configuration"""
        return self.config_validator.validate_configuration(self.config)

    async def rotate_credentials(self) -> Dict[str, Any]:
        """Perform credential rotation"""
        return await self.rotation_manager.rotate_credentials()

    def encrypt_data(self, data: bytes) -> bytes:
        """Encrypt data using current encryption configuration"""
        return self.encryption_manager.encrypt(data)

    def decrypt_data(self, encrypted_data: bytes) -> bytes:
        """Decrypt data using current encryption configuration"""
        return self.encryption_manager.decrypt(encrypted_data)

    def verify_access(self, token: str, required_permission: str) -> bool:
        """Verify access permission"""
        try:
            payload = self.access_control.validate_token(token)
            return self.access_control.has_permission(
                payload["username"], required_permission
            )
        except Exception:
            return False
