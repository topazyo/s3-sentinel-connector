# src/security/__init__.py

from typing import Optional, Dict, Any
import logging
import yaml
from pathlib import Path
from .credential_manager import CredentialManager
from .config_validator import ConfigurationValidator
from .rotation_manager import RotationManager
from .encryption import EncryptionManager
from .audit import AuditLogger
from .access_control import AccessControl

class SecurityManager:
    """Central security management class"""
    
    def __init__(self, config_path: str):
        """
        Initialize security components
        
        Args:
            config_path: Path to security configuration
        """
        self.config = self._load_config(config_path)
        self.logger = logging.getLogger(__name__)
        
        # Initialize security components
        self._initialize_components()

    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Load security configuration"""
        try:
            with open(config_path) as f:
                return yaml.safe_load(f)
        except Exception as e:
            raise RuntimeError(f"Failed to load security config: {str(e)}")

    def _initialize_components(self):
        """Initialize all security components"""
        try:
            # Initialize credential management
            self.credential_manager = CredentialManager(
                vault_url=self.config['azure']['key_vault_url'],
                cache_duration=self.config['credentials']['cache_duration'],
                enable_encryption=self.config['credentials']['enable_encryption']
            )
            
            # Initialize configuration validation
            self.config_validator = ConfigurationValidator(
                policy=self.config['security_policy']
            )
            
            # Initialize credential rotation
            self.rotation_manager = RotationManager(
                credential_manager=self.credential_manager,
                rotation_config=self.config['rotation']
            )
            
            # Initialize encryption
            self.encryption_manager = EncryptionManager(
                key_store_path=self.config['encryption']['key_store_path']
            )
            
            # Initialize audit logging
            self.audit_logger = AuditLogger(
                log_path=self.config['audit']['log_path']
            )
            
            # Initialize access control
            self.access_control = AccessControl(
                jwt_secret=self.config['access_control']['jwt_secret']
            )
            
            self.logger.info("Security components initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize security components: {str(e)}")
            raise

    async def validate_security_config(self) -> Dict[str, Any]:
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

    async def verify_access(self, token: str, required_permission: str) -> bool:
        """Verify access permission"""
        try:
            payload = self.access_control.validate_token(token)
            return self.access_control.has_permission(
                payload['username'],
                required_permission
            )
        except Exception:
            return False