# src/security/credential_manager.py

from typing import Optional, Dict, Any
import base64
import os
import json
from datetime import datetime, timedelta
from azure.keyvault.secrets import SecretClient
from azure.identity import DefaultAzureCredential, ChainedTokenCredential, ManagedIdentityCredential
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import logging

class CredentialManager:
    def __init__(self, 
                 vault_url: str,
                 cache_duration: int = 3600,
                 enable_encryption: bool = True):
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
        
        # Initialize credential cache
        self._cache = {}
        self._cache_times = {}
        
        # Set up logging
        self._setup_logging()
        
        # Initialize Azure clients
        self._initialize_azure_clients()
        
        # Initialize encryption
        if enable_encryption:
            self._initialize_encryption()

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
            self.logger.error(f"Failed to initialize Azure clients: {str(e)}")
            raise

    def _initialize_encryption(self):
        """Initialize local encryption for credential cache"""
        try:
            # Generate encryption key from environment or create new one
            encryption_key = os.getenv('CREDENTIAL_ENCRYPTION_KEY')
            if not encryption_key:
                salt = os.urandom(16)
                kdf = PBKDF2HMAC(
                    algorithm=hashes.SHA256(),
                    length=32,
                    salt=salt,
                    iterations=100000
                )
                encryption_key = base64.urlsafe_b64encode(kdf.derive(os.urandom(32)))
            
            self.fernet = Fernet(encryption_key)
            
        except Exception as e:
            self.logger.error(f"Failed to initialize encryption: {str(e)}")
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
                return self._get_from_cache(credential_name)
            
            # Get from Key Vault
            secret = await self.secret_client.get_secret(credential_name)
            
            # Update cache
            self._update_cache(credential_name, secret.value)
            
            return secret.value
            
        except Exception as e:
            self.logger.error(f"Failed to get credential {credential_name}: {str(e)}")
            raise

    def _is_cache_valid(self, credential_name: str) -> bool:
        """Check if cached credential is still valid"""
        if credential_name not in self._cache_times:
            return False
            
        age = datetime.utcnow() - self._cache_times[credential_name]
        return age.total_seconds() < self.cache_duration

    def _get_from_cache(self, credential_name: str) -> str:
        """Get credential from cache with decryption if enabled"""
        cached_value = self._cache.get(credential_name)
        
        if self.enable_encryption:
            try:
                return self.fernet.decrypt(cached_value.encode()).decode()
            except Exception as e:
                self.logger.error(f"Failed to decrypt cached credential: {str(e)}")
                return self._cache[credential_name]
        
        return cached_value

    def _update_cache(self, credential_name: str, value: str):
        """Update cache with encryption if enabled"""
        if self.enable_encryption:
            try:
                encrypted_value = self.fernet.encrypt(value.encode()).decode()
                self._cache[credential_name] = encrypted_value
            except Exception as e:
                self.logger.error(f"Failed to encrypt credential: {str(e)}")
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
            self._update_cache(credential_name, new_value)
            
            self.logger.info(f"Successfully rotated credential {credential_name}")
            return new_value
            
        except Exception as e:
            self.logger.error(f"Failed to rotate credential {credential_name}: {str(e)}")
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
                cached_value = self._get_from_cache(credential_name)
                
                if vault_value.value == cached_value:
                    validation_results['valid'].append(credential_name)
                else:
                    validation_results['invalid'].append(credential_name)
                    
            except Exception as e:
                validation_results['errors'].append({
                    'credential': credential_name,
                    'error': str(e)
                })
                
        return validation_results