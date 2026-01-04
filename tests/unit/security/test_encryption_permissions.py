# tests/unit/security/test_encryption_permissions.py
"""
Unit tests for encryption key file permissions (B1-003/SEC-04).

Phase 5 (Security): Validates that encryption keys have secure filesystem permissions.
Phase 7 (Testing): Comprehensive coverage of permission scenarios.
"""

import os
import platform
import shutil
import stat
import tempfile

import pytest

from src.security.encryption import EncryptionConfig, EncryptionManager


@pytest.mark.skipif(
    platform.system() == "Windows", reason="Unix permissions not applicable on Windows"
)
class TestKeyStoreDirectoryPermissions:
    """Test key store directory permission enforcement."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.key_store = os.path.join(self.temp_dir, "keys")

    def teardown_method(self):
        """Clean up test fixtures."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_new_key_store_has_700_permissions(self):
        """Phase 5 (B1-003): New key store directory should have 700 permissions."""
        # Create EncryptionManager (should create directory with 700)
        EncryptionManager(key_store_path=self.key_store)

        # Check directory permissions
        dir_stat = os.stat(self.key_store)
        dir_mode = stat.S_IMODE(dir_stat.st_mode)
        expected_mode = stat.S_IRWXU  # 0o700

        assert (
            dir_mode == expected_mode
        ), f"Directory has mode {oct(dir_mode)}, expected {oct(expected_mode)}"

    def test_insecure_directory_permissions_detected(self):
        """Phase 5 (B1-003): Should detect and reject insecure directory permissions."""
        # Create directory with insecure permissions (777 - world accessible)
        os.makedirs(self.key_store)
        os.chmod(self.key_store, 0o777)

        # Try to initialize EncryptionManager
        with pytest.raises(RuntimeError) as exc_info:
            EncryptionManager(key_store_path=self.key_store)

        error_msg = str(exc_info.value)
        assert "Insecure key store permissions" in error_msg
        assert "chmod 700" in error_msg

    def test_group_readable_directory_rejected(self):
        """Phase 5 (B1-003): Directory with group read should be rejected."""
        # Create directory with group read permission (750)
        os.makedirs(self.key_store)
        os.chmod(self.key_store, 0o750)

        with pytest.raises(RuntimeError) as exc_info:
            EncryptionManager(key_store_path=self.key_store)

        assert "Insecure key store permissions" in str(exc_info.value)

    def test_other_readable_directory_rejected(self):
        """Phase 5 (B1-003): Directory with other read should be rejected."""
        # Create directory with other read permission (705)
        os.makedirs(self.key_store)
        os.chmod(self.key_store, 0o705)

        with pytest.raises(RuntimeError) as exc_info:
            EncryptionManager(key_store_path=self.key_store)

        assert "Insecure key store permissions" in str(exc_info.value)

    def test_secure_directory_accepted(self):
        """Phase 5 (B1-003): Directory with 700 permissions should be accepted."""
        # Create directory with secure permissions
        os.makedirs(self.key_store)
        os.chmod(self.key_store, 0o700)

        # Should initialize without error
        manager = EncryptionManager(key_store_path=self.key_store)
        assert manager is not None


@pytest.mark.skipif(
    platform.system() == "Windows", reason="Unix permissions not applicable on Windows"
)
class TestKeyFilePermissions:
    """Test key file permission enforcement."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.key_store = os.path.join(self.temp_dir, "keys")

    def teardown_method(self):
        """Clean up test fixtures."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_new_key_file_has_600_permissions(self):
        """Phase 5 (B1-003): New key file should have 600 permissions."""
        # Create EncryptionManager (generates key with 600)
        EncryptionManager(key_store_path=self.key_store)

        # Check key file permissions
        key_file = os.path.join(self.key_store, "current.key")
        file_stat = os.stat(key_file)
        file_mode = stat.S_IMODE(file_stat.st_mode)
        expected_mode = stat.S_IRUSR | stat.S_IWUSR  # 0o600

        assert (
            file_mode == expected_mode
        ), f"Key file has mode {oct(file_mode)}, expected {oct(expected_mode)}"

    def test_insecure_key_file_permissions_detected(self):
        """Phase 5 (B1-003): Should detect and reject insecure key file permissions."""
        # Create directory and key file with insecure permissions
        os.makedirs(self.key_store)
        os.chmod(self.key_store, 0o700)

        key_file = os.path.join(self.key_store, "current.key")
        with open(key_file, "wb") as f:
            f.write(b"test_key_data_32_bytes_length!!")
        os.chmod(key_file, 0o644)  # World readable

        # Try to initialize EncryptionManager
        with pytest.raises(RuntimeError) as exc_info:
            EncryptionManager(key_store_path=self.key_store)

        error_msg = str(exc_info.value)
        assert "Insecure key file permissions" in error_msg
        assert "chmod 600" in error_msg

    def test_group_readable_key_file_rejected(self):
        """Phase 5 (B1-003): Key file with group read should be rejected."""
        os.makedirs(self.key_store)
        os.chmod(self.key_store, 0o700)

        key_file = os.path.join(self.key_store, "current.key")
        with open(key_file, "wb") as f:
            f.write(b"test_key_data_32_bytes_length!!")
        os.chmod(key_file, 0o640)  # Group readable

        with pytest.raises(RuntimeError) as exc_info:
            EncryptionManager(key_store_path=self.key_store)

        assert "Insecure key file permissions" in str(exc_info.value)

    def test_other_readable_key_file_rejected(self):
        """Phase 5 (B1-003): Key file with other read should be rejected."""
        os.makedirs(self.key_store)
        os.chmod(self.key_store, 0o700)

        key_file = os.path.join(self.key_store, "current.key")
        with open(key_file, "wb") as f:
            f.write(b"test_key_data_32_bytes_length!!")
        os.chmod(key_file, 0o604)  # Other readable

        with pytest.raises(RuntimeError) as exc_info:
            EncryptionManager(key_store_path=self.key_store)

        assert "Insecure key file permissions" in str(exc_info.value)

    def test_executable_key_file_rejected(self):
        """Phase 5 (B1-003): Key file with execute permission should be rejected."""
        os.makedirs(self.key_store)
        os.chmod(self.key_store, 0o700)

        key_file = os.path.join(self.key_store, "current.key")
        with open(key_file, "wb") as f:
            f.write(b"test_key_data_32_bytes_length!!")
        os.chmod(key_file, 0o700)  # Executable

        with pytest.raises(RuntimeError) as exc_info:
            EncryptionManager(key_store_path=self.key_store)

        assert "Insecure key file permissions" in str(exc_info.value)

    def test_secure_key_file_accepted(self):
        """Phase 5 (B1-003): Key file with 600 permissions should be accepted."""
        os.makedirs(self.key_store)
        os.chmod(self.key_store, 0o700)

        key_file = os.path.join(self.key_store, "current.key")
        with open(key_file, "wb") as f:
            f.write(b"test_key_data_32_bytes_length!!")
        os.chmod(key_file, 0o600)

        # Should initialize without error
        manager = EncryptionManager(key_store_path=self.key_store)
        assert manager is not None


@pytest.mark.skipif(
    platform.system() == "Windows", reason="Unix permissions not applicable on Windows"
)
class TestKeyRotationPermissions:
    """Test that key rotation maintains secure permissions."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.key_store = os.path.join(self.temp_dir, "keys")

    def teardown_method(self):
        """Clean up test fixtures."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_rotated_key_has_600_permissions(self):
        """Phase 5 (B1-003): Rotated key should have 600 permissions."""
        # Create manager and generate initial key
        manager = EncryptionManager(
            key_store_path=self.key_store,
            config=EncryptionConfig(key_rotation_days=0),  # Force rotation
        )

        # Trigger key rotation
        manager._rotate_key(manager.current_key)

        # Check new key file permissions
        key_file = os.path.join(self.key_store, "current.key")
        file_stat = os.stat(key_file)
        file_mode = stat.S_IMODE(file_stat.st_mode)
        expected_mode = stat.S_IRUSR | stat.S_IWUSR  # 0o600

        assert file_mode == expected_mode

    def test_backup_key_has_600_permissions(self):
        """Phase 5 (B1-003): Backup key should have 600 permissions."""
        # Create manager
        manager = EncryptionManager(key_store_path=self.key_store)

        # Rotate key (creates backup)
        manager._rotate_key(manager.current_key)

        # Find backup file
        backup_files = [f for f in os.listdir(self.key_store) if "current.key." in f]
        assert len(backup_files) > 0, "Backup file should exist"

        # Check backup permissions
        backup_file = os.path.join(self.key_store, backup_files[0])
        file_stat = os.stat(backup_file)
        file_mode = stat.S_IMODE(file_stat.st_mode)
        expected_mode = stat.S_IRUSR | stat.S_IWUSR  # 0o600

        assert file_mode == expected_mode


@pytest.mark.skipif(
    platform.system() == "Windows", reason="Unix permissions not applicable on Windows"
)
class TestPermissionErrorMessages:
    """Test that permission error messages are informative."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.key_store = os.path.join(self.temp_dir, "keys")

    def teardown_method(self):
        """Clean up test fixtures."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_error_includes_file_path(self):
        """Phase 4 (Observability): Error should include file path."""
        os.makedirs(self.key_store)
        os.chmod(self.key_store, 0o777)

        with pytest.raises(RuntimeError) as exc_info:
            EncryptionManager(key_store_path=self.key_store)

        error_msg = str(exc_info.value)
        assert self.key_store in error_msg

    def test_error_includes_actual_permissions(self):
        """Phase 4: Error should show actual permissions."""
        os.makedirs(self.key_store)
        os.chmod(self.key_store, 0o755)

        with pytest.raises(RuntimeError) as exc_info:
            EncryptionManager(key_store_path=self.key_store)

        error_msg = str(exc_info.value)
        assert "0o755" in error_msg or "755" in error_msg

    def test_error_includes_expected_permissions(self):
        """Phase 4: Error should show expected permissions."""
        os.makedirs(self.key_store)
        os.chmod(self.key_store, 0o777)

        with pytest.raises(RuntimeError) as exc_info:
            EncryptionManager(key_store_path=self.key_store)

        error_msg = str(exc_info.value)
        assert "0o700" in error_msg or "700" in error_msg

    def test_error_includes_fix_command(self):
        """Phase 4: Error should provide fix command."""
        os.makedirs(self.key_store)
        os.chmod(self.key_store, 0o777)

        with pytest.raises(RuntimeError) as exc_info:
            EncryptionManager(key_store_path=self.key_store)

        error_msg = str(exc_info.value)
        assert "chmod" in error_msg


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows-specific test")
class TestWindowsPermissions:
    """Test that permission validation is skipped on Windows."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.key_store = os.path.join(self.temp_dir, "keys")

    def teardown_method(self):
        """Clean up test fixtures."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_windows_skips_permission_validation(self):
        """Phase 5: Windows should skip Unix permission checks."""
        # On Windows, this should succeed regardless of permissions
        manager = EncryptionManager(key_store_path=self.key_store)
        assert manager is not None


class TestEncryptionWithPermissions:
    """Test that encryption/decryption works correctly with permission enforcement."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.key_store = os.path.join(self.temp_dir, "keys")

    def teardown_method(self):
        """Clean up test fixtures."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_encryption_works_with_secure_permissions(self):
        """Phase 5: Encryption should work normally with secure permissions."""
        manager = EncryptionManager(key_store_path=self.key_store)

        # Test encryption
        plaintext = b"sensitive data"
        encrypted = manager.encrypt(plaintext)

        # Test decryption
        decrypted = manager.decrypt(encrypted)

        assert decrypted == plaintext

    def test_multiple_encrypt_decrypt_cycles(self):
        """Phase 6 (Performance): Multiple cycles should work efficiently."""
        manager = EncryptionManager(key_store_path=self.key_store)

        test_data = [b"data1", b"data2", b"data3"]

        for data in test_data:
            encrypted = manager.encrypt(data)
            decrypted = manager.decrypt(encrypted)
            assert decrypted == data
