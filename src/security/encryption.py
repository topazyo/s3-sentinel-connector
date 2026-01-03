# src/security/encryption.py

from cryptography.fernet import Fernet
import base64
import os
import stat
import time
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
    max_backup_age_days: int = 90  # Phase 5 (B1-004/SEC-04): Cleanup old backups

class EncryptionManager:
    def __init__(self, key_store_path: str, config: Optional[EncryptionConfig] = None) -> None:
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
        """
        Initialize or load encryption keys.
        
        Phase 5 (Security - B1-003/SEC-04): Enforces secure file permissions:
        - Key store directory: 700 (owner read/write/execute only)
        - Key files: 600 (owner read/write only)
        
        Raises:
            RuntimeError: If key store has insecure permissions
        """
        try:
            if not os.path.exists(self.key_store_path):
                os.makedirs(self.key_store_path)
                # Phase 5 (B1-003): Set secure directory permissions (700)
                os.chmod(self.key_store_path, stat.S_IRWXU)  # 0o700
                self.logger.info(f"Created key store with secure permissions: {self.key_store_path}")
            
            # Phase 5 (B1-003): Validate directory permissions on startup
            self._validate_key_store_permissions()
            
            self.current_key = self._load_or_generate_key()
            self.logger.info("Encryption keys initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize encryption keys: {str(e)}")
            raise

    def _validate_key_store_permissions(self) -> None:
        """
        Validate that key store has secure permissions.
        
        Phase 5 (Security - B1-003/SEC-04): Fail fast if permissions are insecure.
        
        Required permissions:
        - Directory: 700 (drwx------) - owner only
        - Key files: 600 (-rw-------) - owner read/write only
        
        Raises:
            RuntimeError: If permissions are insecure
        """
        import platform
        
        # Skip permission checks on Windows (different permission model)
        if platform.system() == 'Windows':
            self.logger.debug("Skipping permission validation on Windows")
            return
        
        # Check directory permissions (must be 700)
        dir_stat = os.stat(self.key_store_path)
        dir_mode = stat.S_IMODE(dir_stat.st_mode)
        
        # Expected: 0o700 (rwx for owner only)
        expected_dir_mode = stat.S_IRWXU  # 0o700
        
        if dir_mode != expected_dir_mode:
            # Check if permissions are too permissive (group/other can access)
            if dir_mode & (stat.S_IRWXG | stat.S_IRWXO):
                raise RuntimeError(
                    f"Insecure key store permissions detected. "
                    f"Directory '{self.key_store_path}' has mode {oct(dir_mode)}, "
                    f"expected {oct(expected_dir_mode)} (700). "
                    f"Run: chmod 700 {self.key_store_path}"
                )
            else:
                # Permissions are restrictive enough, just warn
                self.logger.warning(
                    f"Key store directory has non-standard permissions: {oct(dir_mode)}. "
                    f"Expected {oct(expected_dir_mode)} (700)."
                )
        
        # Check key file permissions if they exist
        for filename in os.listdir(self.key_store_path):
            if filename.endswith('.key') or filename.endswith('.encrypted'):
                filepath = os.path.join(self.key_store_path, filename)
                file_stat = os.stat(filepath)
                file_mode = stat.S_IMODE(file_stat.st_mode)
                
                # Expected: 0o600 (rw for owner only)
                expected_file_mode = stat.S_IRUSR | stat.S_IWUSR  # 0o600
                
                if file_mode != expected_file_mode:
                    # Check if permissions are too permissive
                    if file_mode & (stat.S_IRWXG | stat.S_IRWXO | stat.S_IXUSR):
                        raise RuntimeError(
                            f"Insecure key file permissions detected. "
                            f"File '{filepath}' has mode {oct(file_mode)}, "
                            f"expected {oct(expected_file_mode)} (600). "
                            f"Run: chmod 600 {filepath}"
                        )
                    else:
                        self.logger.warning(
                            f"Key file has non-standard permissions: {filepath} - {oct(file_mode)}"
                        )
    
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
        """
        Save encryption key with secure permissions.
        
        Phase 5 (Security - B1-003/SEC-04): Sets file permissions to 600 (owner read/write only).
        """
        key_file = os.path.join(self.key_store_path, 'current.key')
        
        # Backup existing key if present
        if os.path.exists(key_file):
            backup_file = f"{key_file}.{int(os.path.getmtime(key_file))}"
            # Windows: Remove existing backup if it exists (os.rename fails if target exists)
            if os.path.exists(backup_file):
                os.remove(backup_file)
            os.rename(key_file, backup_file)
            # Phase 5 (B1-003): Ensure backup also has secure permissions
            import platform
            if platform.system() != 'Windows':
                os.chmod(backup_file, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
        
        # Save new key
        with open(key_file, 'wb') as f:
            f.write(key)
        
        # Phase 5 (B1-003): Set secure file permissions (600) - owner read/write only
        import platform
        if platform.system() != 'Windows':
            os.chmod(key_file, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
            self.logger.debug(f"Set secure permissions (600) on key file: {key_file}")
        
        # Phase 5 (B1-004): Cleanup old backups after saving new key
        self._cleanup_old_backups()

    def _cleanup_old_backups(self) -> None:
        """
        Remove old key backups that exceed retention period.
        
        Phase 5 (Security - B1-004/SEC-04): Prevents disk bloat and reduces attack surface
        by removing backups older than max_backup_age_days.
        
        Security rationale:
        - Old keys should be removed after rotation period to limit exposure
        - Retains backups for emergency recovery (default: 90 days)
        - Complements B1-003 (encryption permissions) by reducing key sprawl
        
        Behavior:
        - Scans key_store_path for backup files (*.key.<timestamp>)
        - Calculates age from timestamp in filename
        - Removes backups older than config.max_backup_age_days
        - Logs cleanup activity for audit trail
        """
        try:
            cutoff_timestamp = int(time.time()) - (self.config.max_backup_age_days * 86400)
            removed_count = 0
            
            for filename in os.listdir(self.key_store_path):
                # Match backup files: current.key.<timestamp>
                if '.key.' in filename and filename.startswith('current.key.'):
                    filepath = os.path.join(self.key_store_path, filename)
                    
                    try:
                        # Extract timestamp from filename (format: current.key.<timestamp>)
                        timestamp_str = filename.split('.')[-1]
                        backup_timestamp = int(timestamp_str)
                        
                        # Remove if older than cutoff
                        if backup_timestamp < cutoff_timestamp:
                            os.remove(filepath)
                            removed_count += 1
                            backup_age_days = (int(time.time()) - backup_timestamp) // 86400
                            self.logger.info(
                                f"Removed old key backup: {filename} "
                                f"(age: {backup_age_days} days, "
                                f"retention: {self.config.max_backup_age_days} days)"
                            )
                    
                    except (ValueError, IndexError) as e:
                        # Skip files with malformed names
                        self.logger.warning(
                            f"Skipping backup file with invalid timestamp: {filename} ({str(e)})"
                        )
                        continue
                    
                    except OSError as e:
                        # Log but don't abort cleanup for other files
                        self.logger.error(
                            f"Failed to remove backup {filename}: {str(e)}"
                        )
                        continue
            
            if removed_count > 0:
                self.logger.info(
                    f"Backup cleanup complete: removed {removed_count} old key backup(s) "
                    f"(retention: {self.config.max_backup_age_days} days)"
                )
        
        except Exception as e:
            # Don't fail key save operation if cleanup fails
            self.logger.error(
                f"Key backup cleanup failed (non-fatal): {str(e)}"
            )

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
    
    def _reencrypt_data(self, old_key: bytes, new_key: bytes) -> None:
        """
        Re-encrypt data with new key after key rotation.
        
        Args:
            old_key: Previous encryption key
            new_key: New encryption key
            
        Note:
            This method scans the key store directory for .encrypted files
            and re-encrypts them with the new key. If you have encrypted
            data stored elsewhere (database, etc), you should override
            this method or extend it to handle those cases.
        """
        try:
            old_fernet = Fernet(old_key)
            new_fernet = Fernet(new_key)
            
            # Look for encrypted files in key store directory
            encrypted_files = [
                f for f in os.listdir(self.key_store_path)
                if f.endswith('.encrypted')
            ]
            
            reencrypted_count = 0
            for filename in encrypted_files:
                filepath = os.path.join(self.key_store_path, filename)
                
                try:
                    # Read encrypted data
                    with open(filepath, 'rb') as f:
                        encrypted_data = f.read()
                    
                    # Decrypt with old key
                    decrypted_data = old_fernet.decrypt(encrypted_data)
                    
                    # Re-encrypt with new key
                    reencrypted_data = new_fernet.encrypt(decrypted_data)
                    
                    # Write back to file
                    with open(filepath, 'wb') as f:
                        f.write(reencrypted_data)
                    
                    reencrypted_count += 1
                    self.logger.debug(f"Re-encrypted file: {filename}")
                    
                except Exception as e:
                    self.logger.error(
                        f"Failed to re-encrypt {filename}: {str(e)}"
                    )
                    # Continue with other files, don't abort entire rotation
                    
            self.logger.info(
                f"Key rotation complete. Re-encrypted {reencrypted_count} files."
            )
            
        except Exception as e:
            self.logger.error(f"Re-encryption process failed: {str(e)}")
            raise

    def encrypt(self, data: Union[str, bytes]) -> bytes:
        """
        Encrypt data
        
        Args:
            data: Data to encrypt
            
        Returns:
            Encrypted data
            
        Phase 5 (Security - B1-007/SEC-02): Requires 'manage:encryption' permission
        Raises PermissionError if current user lacks permission
        """
        # Phase 5 (Security - B1-007): Permission check happens via decorator
        # Applied at runtime via access_control instance
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
            
        Phase 5 (Security - B1-007/SEC-02): Requires 'manage:encryption' permission
        Raises PermissionError if current user lacks permission
        """
        # Phase 5 (Security - B1-007): Permission check happens via decorator
        # Applied at runtime via access_control instance
        try:
            f = Fernet(self.current_key)
            return f.decrypt(encrypted_data)
            
        except Exception as e:
            self.logger.error(f"Decryption failed: {str(e)}")
            raise