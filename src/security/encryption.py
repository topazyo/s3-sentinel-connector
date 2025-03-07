# src/security/encryption.py

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
import base64
import os
from typing import Union, Optional
import logging
from dataclasses import dataclass

@dataclass
class EncryptionConfig:
    """Configuration for encryption operations"""
    key_rotation_days: int = 30
    min_key_length: int = 32
    iterations: int = 100000
    algorithm: str = 'AES-256-GCM'

class EncryptionManager:
    def __init__(self, key_store_path: str, config: Optional[EncryptionConfig] = None):
        """
        Initialize encryption manager
        
        Args:
            key_store_path: Path to store encryption keys
            config: Encryption configuration
        """
        self.key_store_path = key_store_path
        self.config = config or EncryptionConfig()
        self.logger = logging.getLogger(__name__)
        
        # Initialize encryption keys
        self._initialize_keys()

    def _initialize_keys(self) -> None:
        """Initialize or load encryption keys"""
        try:
            if not os.path.exists(self.key_store_path):
                os.makedirs(self.key_store_path)
            
            self.current_key = self._load_or_generate_key()
            self.logger.info("Encryption keys initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize encryption keys: {str(e)}")
            raise

    def _load_or_generate_key(self) -> bytes:
        """Load existing key or generate new one"""
        key_file = os.path.join(self.key_store_path, 'current.key')
        
        if os.path.exists(key_file):
            with open(key_file, 'rb') as f:
                key = f.read()
            
            # Check if key rotation is needed
            if self._needs_rotation(key_file):
                key = self._rotate_key(key)
        else:
            key = self._generate_key()
            self._save_key(key)
            
        return key

    def _generate_key(self) -> bytes:
        """Generate new encryption key"""
        return Fernet.generate_key()

    def _save_key(self, key: bytes) -> None:
        """Save encryption key"""
        key_file = os.path.join(self.key_store_path, 'current.key')
        
        # Backup existing key if present
        if os.path.exists(key_file):
            backup_file = f"{key_file}.{int(os.path.getmtime(key_file))}"
            os.rename(key_file, backup_file)
        
        # Save new key
        with open(key_file, 'wb') as f:
            f.write(key)

    def _needs_rotation(self, key_file: str) -> bool:
        """Check if key needs rotation"""
        key_age = int(time.time() - os.path.getmtime(key_file))
        return key_age > (self.config.key_rotation_days * 86400)

    def _rotate_key(self, old_key: bytes) -> bytes:
        """Rotate encryption key"""
        new_key = self._generate_key()
        self._save_key(new_key)
        
        # Re-encrypt existing data with new key
        self._reencrypt_data(old_key, new_key)
        
        return new_key

    def encrypt(self, data: Union[str, bytes]) -> bytes:
        """
        Encrypt data
        
        Args:
            data: Data to encrypt
            
        Returns:
            Encrypted data
        """
        try:
            if isinstance(data, str):
                data = data.encode()
            
            f = Fernet(self.current_key)
            return f.encrypt(data)
            
        except Exception as e:
            self.logger.error(f"Encryption failed: {str(e)}")
            raise

    def decrypt(self, encrypted_data: bytes) -> bytes:
        """
        Decrypt data
        
        Args:
            encrypted_data: Data to decrypt
            
        Returns:
            Decrypted data
        """
        try:
            f = Fernet(self.current_key)
            return f.decrypt(encrypted_data)
            
        except Exception as e:
            self.logger.error(f"Decryption failed: {str(e)}")
            raise