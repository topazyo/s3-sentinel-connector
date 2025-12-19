# src/security/credential_manager.py

from typing import Optional, Dict, Any
import logging
from datetime import datetime
from azure.keyvault.secrets.aio import SecretClient
from azure.identity.aio import (
    DefaultAzureCredential,
    ChainedTokenCredential,
    ManagedIdentityCredential,
)
from cryptography.fernet import Fernet

class CredentialManager:
    def __init__(self, 
                 vault_url: str,
                 cache_duration: int = 3600,
                 enable_encryption: bool = True,
                 encryption_secret_name: str = "credential-encryption-key"):
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

        # Initialize encryption placeholders (key fetched lazily from Key Vault)
        self.fernet: Optional[Fernet] = None
        self._encryption_ready = False

    def _setup_logging(self):
        """Configure secure logging"""
        self.logger = logging.getLogger('SecurityManager')
        self.logger.setLevel(logging.INFO)
        
        # Ensure sensitive data isn't logged
        logging.getLogger('azure').setLevel(logging.WARNING)

    def _initialize_azure_clients(self):
        """Initialize Azure clients with fallback authentication"""
        try:
            # Chain different credential options
            credential = ChainedTokenCredential(
                ManagedIdentityCredential(),
                DefaultAzureCredential()
            )
            
            self.secret_client = SecretClient(
                vault_url=self.vault_url,
                credential=credential
            )
            
            self.logger.info("Successfully initialized Azure Key Vault client")
            
        except Exception as e:
            self.logger.error("Failed to initialize Azure clients: %s", self._safe_error(e))
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
            self.logger.error("Failed to initialize cache encryption: %s", self._safe_error(e))
            self.enable_encryption = False

    async def get_credential(self, 
                           credential_name: str, 
                           force_refresh: bool = False) -> str:
        """
        Get credential from cache or Key Vault
        
        Args:
            credential_name: Name of the credential
            force_refresh: Force refresh from Key Vault
            
        Returns:
            Credential value
        """
        try:
            # Check cache first
            if not force_refresh and self._is_cache_valid(credential_name):
                cached = await self._get_from_cache(credential_name)
                if cached is not None:
                    return cached

            # Get from Key Vault
            secret = await self.secret_client.get_secret(credential_name)
            value = secret.value

            # Update cache
            await self._ensure_encryption()
            self._update_cache(credential_name, value)

            return value

        except Exception as e:
            self.logger.error(
                "Failed to get credential %s: %s",
                credential_name,
                self._safe_error(e)
            )
            raise

    def _is_cache_valid(self, credential_name: str) -> bool:
        """Check if cached credential is still valid"""
        if credential_name not in self._cache_times:
            return False
            
        age = datetime.utcnow() - self._cache_times[credential_name]
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
                    self._safe_error(e)
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
                self.logger.error("Failed to encrypt credential %s: %s", credential_name, self._safe_error(e))
                self._cache[credential_name] = value
        else:
            self._cache[credential_name] = value
            
        self._cache_times[credential_name] = datetime.utcnow()

    async def rotate_credential(self, 
                              credential_name: str, 
                              new_value: Optional[str] = None) -> str:
        """
        Rotate credential in Key Vault
        
        Args:
            credential_name: Name of the credential
            new_value: Optional new value (auto-generated if not provided)
            
        Returns:
            New credential value
        """
        try:
            if new_value is None:
                new_value = self._generate_secure_credential()
            
            # Update in Key Vault
            await self.secret_client.set_secret(credential_name, new_value)
            
            # Update cache
            await self._ensure_encryption()
            self._update_cache(credential_name, new_value)
            
            self.logger.info("Successfully rotated credential %s", credential_name)
            return new_value
            
        except Exception as e:
            self.logger.error(
                "Failed to rotate credential %s: %s",
                credential_name,
                self._safe_error(e)
            )
            raise

    def _generate_secure_credential(self, length: int = 32) -> str:
        """Generate secure random credential"""
        import secrets
        import string
        
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        return ''.join(secrets.choice(alphabet) for _ in range(length))

    async def validate_credentials(self) -> Dict[str, Any]:
        """Validate all cached credentials"""
        validation_results = {
            'valid': [],
            'invalid': [],
            'errors': []
        }
        
        for credential_name in self._cache:
            try:
                # Attempt to get credential from Key Vault
                vault_value = await self.secret_client.get_secret(credential_name)
                cached_value = await self._get_from_cache(credential_name)
                
                if cached_value is not None and vault_value.value == cached_value:
                    validation_results['valid'].append(credential_name)
                else:
                    validation_results['invalid'].append(credential_name)
                    
            except Exception as e:
                validation_results['errors'].append({
                    'credential': credential_name,
                    'error': self._safe_error(e)
                })
                
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
                self._safe_error(e)
            )
            key = Fernet.generate_key()
            try:
                await self.secret_client.set_secret(self._encryption_secret_name, key.decode())
            except Exception as write_error:
                self.logger.error(
                    "Failed to persist generated encryption key to Key Vault: %s",
                    self._safe_error(write_error)
                )
                raise
            return key

    def _safe_error(self, err: Exception) -> str:
        """Redact potentially sensitive content from error messages."""
        msg = str(err)
        if len(msg) > 500:
            return msg[:500] + "..."
        return msg