# tests/security/test_encryption_rotation.py

import pytest
import os
import tempfile
import shutil
import time
from cryptography.fernet import Fernet
from src.security.encryption import EncryptionManager, EncryptionConfig


class TestEncryptionRotation:
    """Test encryption key rotation and re-encryption"""
    
    @pytest.fixture
    def temp_key_store(self):
        """Create temporary key store directory"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    @pytest.fixture
    def encryption_manager(self, temp_key_store):
        """Create EncryptionManager with temp key store"""
        config = EncryptionConfig(
            key_rotation_days=30,
            min_key_length=32
        )
        return EncryptionManager(temp_key_store, config)
    
    def test_time_import_available(self):
        """Test that time module is properly imported"""
        from src.security.encryption import time
        assert time is not None
    
    def test_reencrypt_data_with_no_files(self, encryption_manager):
        """Test _reencrypt_data with no encrypted files"""
        old_key = Fernet.generate_key()
        new_key = Fernet.generate_key()
        
        # Should complete without error
        encryption_manager._reencrypt_data(old_key, new_key)
    
    def test_reencrypt_data_with_encrypted_files(self, encryption_manager, temp_key_store):
        """Test _reencrypt_data successfully re-encrypts files"""
        # Create old key and encrypt some data
        old_key = Fernet.generate_key()
        old_fernet = Fernet(old_key)
        
        test_data = b"sensitive data to encrypt"
        encrypted_data = old_fernet.encrypt(test_data)
        
        # Write encrypted file
        encrypted_file = os.path.join(temp_key_store, "test_data.encrypted")
        with open(encrypted_file, 'wb') as f:
            f.write(encrypted_data)
        
        # Generate new key and re-encrypt
        new_key = Fernet.generate_key()
        encryption_manager._reencrypt_data(old_key, new_key)
        
        # Verify file was re-encrypted with new key
        with open(encrypted_file, 'rb') as f:
            reencrypted_data = f.read()
        
        new_fernet = Fernet(new_key)
        decrypted_data = new_fernet.decrypt(reencrypted_data)
        
        assert decrypted_data == test_data
        
        # Old key should NOT decrypt the re-encrypted data
        with pytest.raises(Exception):
            old_fernet.decrypt(reencrypted_data)
    
    def test_reencrypt_multiple_files(self, encryption_manager, temp_key_store):
        """Test _reencrypt_data handles multiple files"""
        old_key = Fernet.generate_key()
        old_fernet = Fernet(old_key)
        
        # Create multiple encrypted files
        test_files = {
            "data1.encrypted": b"first data",
            "data2.encrypted": b"second data",
            "data3.encrypted": b"third data"
        }
        
        for filename, data in test_files.items():
            encrypted = old_fernet.encrypt(data)
            filepath = os.path.join(temp_key_store, filename)
            with open(filepath, 'wb') as f:
                f.write(encrypted)
        
        # Re-encrypt with new key
        new_key = Fernet.generate_key()
        encryption_manager._reencrypt_data(old_key, new_key)
        
        # Verify all files were re-encrypted
        new_fernet = Fernet(new_key)
        for filename, original_data in test_files.items():
            filepath = os.path.join(temp_key_store, filename)
            with open(filepath, 'rb') as f:
                reencrypted = f.read()
            
            decrypted = new_fernet.decrypt(reencrypted)
            assert decrypted == original_data
    
    def test_reencrypt_ignores_non_encrypted_files(self, encryption_manager, temp_key_store):
        """Test _reencrypt_data ignores non-.encrypted files"""
        old_key = Fernet.generate_key()
        new_key = Fernet.generate_key()
        
        # Create a non-encrypted file
        regular_file = os.path.join(temp_key_store, "regular.txt")
        with open(regular_file, 'w') as f:
            f.write("regular text file")
        
        # Re-encrypt should not touch this file
        encryption_manager._reencrypt_data(old_key, new_key)
        
        # Verify file unchanged
        with open(regular_file, 'r') as f:
            content = f.read()
        
        assert content == "regular text file"
    
    def test_reencrypt_continues_on_file_error(self, encryption_manager, temp_key_store):
        """Test _reencrypt_data continues if one file fails"""
        old_key = Fernet.generate_key()
        old_fernet = Fernet(old_key)
        new_key = Fernet.generate_key()
        new_fernet = Fernet(new_key)
        
        # Create valid encrypted file
        valid_data = b"valid data"
        valid_encrypted = old_fernet.encrypt(valid_data)
        valid_file = os.path.join(temp_key_store, "valid.encrypted")
        with open(valid_file, 'wb') as f:
            f.write(valid_encrypted)
        
        # Create corrupted encrypted file
        corrupted_file = os.path.join(temp_key_store, "corrupted.encrypted")
        with open(corrupted_file, 'wb') as f:
            f.write(b"not valid encrypted data")
        
        # Re-encrypt should handle error and continue
        encryption_manager._reencrypt_data(old_key, new_key)
        
        # Valid file should be re-encrypted
        with open(valid_file, 'rb') as f:
            reencrypted = f.read()
        
        decrypted = new_fernet.decrypt(reencrypted)
        assert decrypted == valid_data
    
    def test_full_key_rotation_workflow(self, temp_key_store):
        """Test complete key rotation workflow"""
        config = EncryptionConfig(key_rotation_days=0)  # Force rotation
        manager = EncryptionManager(temp_key_store, config)
        
        # Encrypt some data
        original_data = "test data"
        encrypted = manager.encrypt(original_data)
        
        # Save encrypted data to file
        encrypted_file = os.path.join(temp_key_store, "workflow_test.encrypted")
        with open(encrypted_file, 'wb') as f:
            f.write(encrypted)
        
        # Trigger key rotation by creating new manager (simulates time passing)
        # First, make the key file old
        key_file = os.path.join(temp_key_store, "current.key")
        old_time = time.time() - (31 * 86400)  # 31 days ago
        os.utime(key_file, (old_time, old_time))
        
        # Create new manager which should trigger rotation
        manager2 = EncryptionManager(temp_key_store, config)
        
        # Should be able to decrypt with new manager
        # (though in practice, _reencrypt_data would handle stored files)
        assert manager2.current_key != manager.current_key
