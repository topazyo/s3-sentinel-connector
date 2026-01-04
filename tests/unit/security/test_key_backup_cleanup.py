# tests/unit/security/test_key_backup_cleanup.py
"""
Phase 5 (Security - B1-004/SEC-04): Key Backup Cleanup Tests

Tests encryption key backup retention and cleanup functionality.
Validates that old key backups are removed after max_backup_age_days.
"""

import os
import shutil
import tempfile
import time

import pytest

from src.security.encryption import EncryptionConfig, EncryptionManager


class TestKeyBackupCleanup:
    """Test key backup cleanup after rotation"""

    @pytest.fixture
    def temp_key_store(self):
        """Create temporary key store directory"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.fixture
    def encryption_config(self):
        """Create encryption config with short retention for testing"""
        return EncryptionConfig(
            key_rotation_days=1, max_backup_age_days=7  # 7 days retention
        )

    def test_cleanup_removes_old_backups(self, temp_key_store, encryption_config):
        """Test that backups older than max_backup_age_days are removed"""
        # Create encryption manager
        manager = EncryptionManager(temp_key_store, encryption_config)

        # Create fake old backup (8 days old - should be removed)
        old_timestamp = int(time.time()) - (8 * 86400)
        old_backup_file = os.path.join(temp_key_store, f"current.key.{old_timestamp}")
        with open(old_backup_file, "wb") as f:
            f.write(b"old-key-data")

        # Create fake recent backup (5 days old - should be kept)
        recent_timestamp = int(time.time()) - (5 * 86400)
        recent_backup_file = os.path.join(
            temp_key_store, f"current.key.{recent_timestamp}"
        )
        with open(recent_backup_file, "wb") as f:
            f.write(b"recent-key-data")

        # Run cleanup
        manager._cleanup_old_backups()

        # Verify old backup removed
        assert not os.path.exists(old_backup_file), "Old backup should be removed"

        # Verify recent backup kept
        assert os.path.exists(recent_backup_file), "Recent backup should be kept"

    def test_cleanup_keeps_all_recent_backups(self, temp_key_store, encryption_config):
        """Test that all backups within retention period are kept"""
        manager = EncryptionManager(temp_key_store, encryption_config)

        # Create multiple recent backups (all within 7 days)
        backup_files = []
        for days_ago in [1, 3, 5, 7]:
            timestamp = int(time.time()) - (days_ago * 86400)
            backup_file = os.path.join(temp_key_store, f"current.key.{timestamp}")
            with open(backup_file, "wb") as f:
                f.write(f"backup-{days_ago}".encode())
            backup_files.append(backup_file)

        # Run cleanup
        manager._cleanup_old_backups()

        # Verify all recent backups kept
        for backup_file in backup_files:
            assert os.path.exists(
                backup_file
            ), f"Recent backup should be kept: {backup_file}"

    def test_cleanup_removes_multiple_old_backups(
        self, temp_key_store, encryption_config
    ):
        """Test that multiple old backups are removed in one cleanup"""
        manager = EncryptionManager(temp_key_store, encryption_config)

        # Create multiple old backups (all beyond 7 days)
        old_backups = []
        for days_ago in [10, 15, 20, 30]:
            timestamp = int(time.time()) - (days_ago * 86400)
            backup_file = os.path.join(temp_key_store, f"current.key.{timestamp}")
            with open(backup_file, "wb") as f:
                f.write(f"old-backup-{days_ago}".encode())
            old_backups.append(backup_file)

        # Run cleanup
        manager._cleanup_old_backups()

        # Verify all old backups removed
        for backup_file in old_backups:
            assert not os.path.exists(
                backup_file
            ), f"Old backup should be removed: {backup_file}"

    def test_cleanup_boundary_exactly_at_cutoff(
        self, temp_key_store, encryption_config
    ):
        """Test backup exactly at cutoff age (7 days) - should be kept"""
        manager = EncryptionManager(temp_key_store, encryption_config)

        # Create backup exactly at cutoff (7 days)
        cutoff_timestamp = int(time.time()) - (7 * 86400)
        boundary_backup = os.path.join(
            temp_key_store, f"current.key.{cutoff_timestamp}"
        )
        with open(boundary_backup, "wb") as f:
            f.write(b"boundary-backup")

        # Run cleanup
        manager._cleanup_old_backups()

        # Verify backup at boundary is kept (cutoff is <, not <=)
        assert os.path.exists(
            boundary_backup
        ), "Backup exactly at cutoff should be kept"

    def test_cleanup_ignores_current_key_file(self, temp_key_store, encryption_config):
        """Test that current.key (active key) is never removed"""
        manager = EncryptionManager(temp_key_store, encryption_config)

        # current.key should exist from initialization
        current_key_file = os.path.join(temp_key_store, "current.key")
        assert os.path.exists(current_key_file), "Current key should exist"

        # Create old backup
        old_timestamp = int(time.time()) - (10 * 86400)
        old_backup = os.path.join(temp_key_store, f"current.key.{old_timestamp}")
        with open(old_backup, "wb") as f:
            f.write(b"old-backup")

        # Run cleanup
        manager._cleanup_old_backups()

        # Verify current.key still exists
        assert os.path.exists(current_key_file), "Current key should never be removed"

        # Verify old backup removed
        assert not os.path.exists(old_backup), "Old backup should be removed"

    def test_cleanup_handles_malformed_backup_names(
        self, temp_key_store, encryption_config
    ):
        """Test that cleanup gracefully handles backup files with invalid timestamps"""
        manager = EncryptionManager(temp_key_store, encryption_config)

        # Create files with malformed names
        malformed_files = [
            os.path.join(temp_key_store, "current.key.not-a-timestamp"),
            os.path.join(temp_key_store, "current.key."),
            os.path.join(temp_key_store, "current.key.12345abc"),
        ]

        for malformed_file in malformed_files:
            with open(malformed_file, "wb") as f:
                f.write(b"malformed")

        # Run cleanup (should not crash)
        manager._cleanup_old_backups()

        # Verify malformed files are kept (skipped, not removed)
        for malformed_file in malformed_files:
            assert os.path.exists(
                malformed_file
            ), "Malformed backup should be skipped, not removed"

    def test_cleanup_handles_empty_key_store(self, temp_key_store, encryption_config):
        """Test cleanup with no backup files (should not crash)"""
        manager = EncryptionManager(temp_key_store, encryption_config)

        # Remove all files except current.key
        for filename in os.listdir(temp_key_store):
            if filename != "current.key":
                os.remove(os.path.join(temp_key_store, filename))

        # Run cleanup (should not crash)
        manager._cleanup_old_backups()

        # Should complete without error
        assert os.path.exists(os.path.join(temp_key_store, "current.key"))


class TestKeyBackupCleanupIntegration:
    """Test key backup cleanup integrated with key rotation"""

    @pytest.fixture
    def temp_key_store(self):
        """Create temporary key store directory"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.fixture
    def encryption_config(self):
        """Create encryption config"""
        return EncryptionConfig(key_rotation_days=1, max_backup_age_days=7)

    def test_cleanup_runs_automatically_on_key_save(
        self, temp_key_store, encryption_config
    ):
        """Test that cleanup runs automatically when saving a new key"""
        manager = EncryptionManager(temp_key_store, encryption_config)

        # Create old backup
        old_timestamp = int(time.time()) - (10 * 86400)
        old_backup = os.path.join(temp_key_store, f"current.key.{old_timestamp}")
        with open(old_backup, "wb") as f:
            f.write(b"old-backup")

        # Save new key (should trigger cleanup)
        new_key = manager._generate_key()
        manager._save_key(new_key)

        # Verify old backup was automatically removed
        assert not os.path.exists(
            old_backup
        ), "Old backup should be auto-removed on save"

    def test_cleanup_runs_on_key_rotation(self, temp_key_store, encryption_config):
        """Test that cleanup runs during key rotation workflow"""
        # Create manager with very short rotation period
        config = EncryptionConfig(key_rotation_days=0, max_backup_age_days=7)
        manager = EncryptionManager(temp_key_store, config)

        # Create old backup manually
        old_timestamp = int(time.time()) - (10 * 86400)
        old_backup = os.path.join(temp_key_store, f"current.key.{old_timestamp}")
        with open(old_backup, "wb") as f:
            f.write(b"very-old-backup")

        # Trigger rotation (which calls _save_key, which calls cleanup)
        os.path.join(temp_key_store, "current.key")
        old_key = manager.current_key
        manager._rotate_key(old_key)

        # Verify old backup removed during rotation
        assert not os.path.exists(
            old_backup
        ), "Old backup should be removed during rotation"

    def test_multiple_rotations_with_cleanup(self, temp_key_store, encryption_config):
        """Test that multiple rotations create and clean up backups correctly"""
        manager = EncryptionManager(temp_key_store, encryption_config)

        # Simulate multiple rotations
        for _i in range(5):
            # Save key (creates backup of previous)
            new_key = manager._generate_key()
            manager._save_key(new_key)
            time.sleep(0.01)  # Small delay to ensure different timestamps

        # Manually create an old backup (beyond retention)
        old_timestamp = int(time.time()) - (10 * 86400)
        old_backup = os.path.join(temp_key_store, f"current.key.{old_timestamp}")
        with open(old_backup, "wb") as f:
            f.write(b"ancient-backup")

        # Trigger one more save (should clean up old backup)
        manager._save_key(manager._generate_key())

        # Verify old backup removed
        assert not os.path.exists(old_backup), "Old backup should be cleaned up"

        # Verify current.key still exists
        assert os.path.exists(os.path.join(temp_key_store, "current.key"))


class TestKeyBackupCleanupLogging:
    """Test logging behavior of key backup cleanup"""

    @pytest.fixture
    def temp_key_store(self):
        """Create temporary key store directory"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.fixture
    def encryption_config(self):
        """Create encryption config"""
        return EncryptionConfig(key_rotation_days=1, max_backup_age_days=7)

    def test_cleanup_logs_removed_backups(
        self, temp_key_store, encryption_config, caplog
    ):
        """Test that cleanup logs each removed backup"""
        import logging

        caplog.set_level(logging.INFO)

        manager = EncryptionManager(temp_key_store, encryption_config)

        # Create old backup
        old_timestamp = int(time.time()) - (10 * 86400)
        old_backup = os.path.join(temp_key_store, f"current.key.{old_timestamp}")
        with open(old_backup, "wb") as f:
            f.write(b"old-backup")

        # Run cleanup
        manager._cleanup_old_backups()

        # Verify logging
        assert "Removed old key backup" in caplog.text
        assert f"current.key.{old_timestamp}" in caplog.text
        assert "age:" in caplog.text
        assert "retention: 7 days" in caplog.text

    def test_cleanup_logs_summary(self, temp_key_store, encryption_config, caplog):
        """Test that cleanup logs summary when backups are removed"""
        import logging

        caplog.set_level(logging.INFO)

        manager = EncryptionManager(temp_key_store, encryption_config)

        # Create multiple old backups
        for days_ago in [10, 15, 20]:
            timestamp = int(time.time()) - (days_ago * 86400)
            backup_file = os.path.join(temp_key_store, f"current.key.{timestamp}")
            with open(backup_file, "wb") as f:
                f.write(b"old-backup")

        # Run cleanup
        manager._cleanup_old_backups()

        # Verify summary logging
        assert "Backup cleanup complete" in caplog.text
        assert "removed 3 old key backup(s)" in caplog.text

    def test_cleanup_logs_malformed_names(
        self, temp_key_store, encryption_config, caplog
    ):
        """Test that cleanup logs warnings for malformed backup names"""
        import logging

        caplog.set_level(logging.WARNING)

        manager = EncryptionManager(temp_key_store, encryption_config)

        # Create malformed backup
        malformed_file = os.path.join(temp_key_store, "current.key.not-a-number")
        with open(malformed_file, "wb") as f:
            f.write(b"malformed")

        # Run cleanup
        manager._cleanup_old_backups()

        # Verify warning logged
        assert "Skipping backup file with invalid timestamp" in caplog.text
        assert "current.key.not-a-number" in caplog.text

    def test_cleanup_logs_errors_non_fatal(
        self, temp_key_store, encryption_config, caplog
    ):
        """Test that cleanup logs errors but doesn't crash"""
        import logging

        caplog.set_level(logging.ERROR)

        manager = EncryptionManager(temp_key_store, encryption_config)

        # Create old backup
        old_timestamp = int(time.time()) - (10 * 86400)
        old_backup = os.path.join(temp_key_store, f"current.key.{old_timestamp}")
        with open(old_backup, "wb") as f:
            f.write(b"old-backup")

        # Make backup read-only to trigger removal error (Unix only)
        import platform

        if platform.system() != "Windows":
            os.chmod(temp_key_store, 0o500)  # Read-only directory

            # Run cleanup (should not crash)
            manager._cleanup_old_backups()

            # Restore permissions
            os.chmod(temp_key_store, 0o700)

            # Verify error logged but no exception
            assert (
                "Failed to remove backup" in caplog.text
                or "cleanup failed" in caplog.text
            )


class TestKeyBackupCleanupConfiguration:
    """Test configuration options for key backup cleanup"""

    @pytest.fixture
    def temp_key_store(self):
        """Create temporary key store directory"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_default_retention_90_days(self, temp_key_store):
        """Test that default retention is 90 days"""
        config = EncryptionConfig()  # Use defaults
        assert config.max_backup_age_days == 90, "Default retention should be 90 days"

        manager = EncryptionManager(temp_key_store, config)

        # Create backup at 89 days (should be kept)
        recent_timestamp = int(time.time()) - (89 * 86400)
        recent_backup = os.path.join(temp_key_store, f"current.key.{recent_timestamp}")
        with open(recent_backup, "wb") as f:
            f.write(b"recent")

        # Create backup at 91 days (should be removed)
        old_timestamp = int(time.time()) - (91 * 86400)
        old_backup = os.path.join(temp_key_store, f"current.key.{old_timestamp}")
        with open(old_backup, "wb") as f:
            f.write(b"old")

        # Run cleanup
        manager._cleanup_old_backups()

        # Verify
        assert os.path.exists(recent_backup), "89-day backup should be kept"
        assert not os.path.exists(old_backup), "91-day backup should be removed"

    def test_custom_retention_period(self, temp_key_store):
        """Test that custom retention period is respected"""
        config = EncryptionConfig(max_backup_age_days=30)  # 30 days retention
        manager = EncryptionManager(temp_key_store, config)

        # Create backup at 31 days (should be removed with 30-day retention)
        old_timestamp = int(time.time()) - (31 * 86400)
        old_backup = os.path.join(temp_key_store, f"current.key.{old_timestamp}")
        with open(old_backup, "wb") as f:
            f.write(b"old")

        # Run cleanup
        manager._cleanup_old_backups()

        # Verify removal
        assert not os.path.exists(
            old_backup
        ), "31-day backup should be removed with 30-day retention"

    def test_zero_retention_keeps_nothing(self, temp_key_store):
        """Test that zero retention removes all backups immediately"""
        config = EncryptionConfig(max_backup_age_days=0)  # Remove all backups
        manager = EncryptionManager(temp_key_store, config)

        # Create backup from 1 second ago
        recent_timestamp = int(time.time()) - 1
        recent_backup = os.path.join(temp_key_store, f"current.key.{recent_timestamp}")
        with open(recent_backup, "wb") as f:
            f.write(b"recent")

        # Run cleanup
        manager._cleanup_old_backups()

        # Verify immediate removal
        assert not os.path.exists(
            recent_backup
        ), "Backup should be removed with 0-day retention"
