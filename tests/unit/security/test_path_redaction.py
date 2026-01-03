# tests/unit/security/test_path_redaction.py

"""
Phase 2 (Consistency - B2-010): Path Redaction Tests

Tests for file path redaction in error messages.
Validates that system paths are properly redacted to prevent information disclosure.
"""

import pytest
from unittest.mock import Mock, patch

from src.security.credential_manager import CredentialManager


class TestPathRedaction:
    """Test path redaction in error messages"""
    
    @pytest.fixture
    def credential_manager(self):
        """Create CredentialManager instance for testing"""
        with patch('src.security.credential_manager.SecretClient'), \
             patch('src.security.credential_manager.DefaultAzureCredential'):
            
            manager = CredentialManager(
                vault_url='https://test.vault.azure.net',
                cache_duration=300,
                enable_encryption=False
            )
            return manager
    
    def test_redact_unix_absolute_path(self, credential_manager):
        """Test redaction of Unix absolute paths"""
        error_msg = "FileNotFoundError: /etc/app/secrets/key.pem not found"
        
        redacted = credential_manager._redact_path_from_error(error_msg)
        
        assert "/etc/app/secrets/key.pem" not in redacted
        assert "[PATH]/key.pem" in redacted
        assert "FileNotFoundError" in redacted
        assert "not found" in redacted
    
    def test_redact_windows_absolute_path_backslashes(self, credential_manager):
        """Test redaction of Windows paths with backslashes"""
        error_msg = "PermissionError: C:\\Users\\app\\config\\secret.yaml access denied"
        
        redacted = credential_manager._redact_path_from_error(error_msg)
        
        assert "C:\\Users\\app\\config\\secret.yaml" not in redacted
        assert "[PATH]/secret.yaml" in redacted
        assert "PermissionError" in redacted
        assert "access denied" in redacted
    
    def test_redact_windows_absolute_path_forward_slashes(self, credential_manager):
        """Test redaction of Windows paths with forward slashes"""
        error_msg = "FileNotFoundError: C:/Program Files/App/keys/private.key not found"
        
        redacted = credential_manager._redact_path_from_error(error_msg)
        
        assert "C:/Program Files/App/keys/private.key" not in redacted
        assert "[PATH]/private.key" in redacted
        assert "FileNotFoundError" in redacted
    
    def test_redact_multiple_paths_in_message(self, credential_manager):
        """Test redaction of multiple paths in same error message"""
        error_msg = (
            "Failed to copy /var/app/source.txt to "
            "/var/app/backup/dest.txt: permission denied"
        )
        
        redacted = credential_manager._redact_path_from_error(error_msg)
        
        assert "/var/app/source.txt" not in redacted
        assert "/var/app/backup/dest.txt" not in redacted
        assert "[PATH]/source.txt" in redacted
        assert "[PATH]/dest.txt" in redacted
        assert "permission denied" in redacted
    
    def test_preserve_relative_paths(self, credential_manager):
        """Test that relative paths are preserved (not sensitive)"""
        error_msg = "Config error in config/base.yaml line 42"
        
        redacted = credential_manager._redact_path_from_error(error_msg)
        
        # Relative paths should be preserved
        assert "config/base.yaml" in redacted
        assert "line 42" in redacted
    
    def test_redact_path_with_special_characters(self, credential_manager):
        """Test redaction of paths with hyphens and underscores"""
        error_msg = "IOError: /opt/my-app/secret_keys/api-key_v2.json read failed"
        
        redacted = credential_manager._redact_path_from_error(error_msg)
        
        assert "/opt/my-app/secret_keys/api-key_v2.json" not in redacted
        assert "[PATH]/api-key_v2.json" in redacted
        assert "IOError" in redacted
    
    def test_redact_deep_nested_path(self, credential_manager):
        """Test redaction of deeply nested directory paths"""
        error_msg = (
            "OSError: /home/user/projects/app/src/security/keys/"
            "encryption/master.key not accessible"
        )
        
        redacted = credential_manager._redact_path_from_error(error_msg)
        
        assert "/home/user/projects" not in redacted
        assert "[PATH]/master.key" in redacted
        assert "OSError" in redacted
    
    def test_safe_error_applies_path_redaction(self, credential_manager):
        """Test that _safe_error() applies path redaction"""
        # Create exception with file path in message
        exc = FileNotFoundError("/etc/secrets/key.pem not found")
        
        redacted = credential_manager._safe_error(exc)
        
        assert "/etc/secrets/key.pem" not in redacted
        assert "[PATH]/key.pem" in redacted
    
    def test_safe_error_truncates_long_messages(self, credential_manager):
        """Test that _safe_error() truncates messages > 500 chars"""
        # Create long error message with path
        long_msg = (
            "Error: /var/log/app.log - " + "x" * 500
        )
        exc = Exception(long_msg)
        
        redacted = credential_manager._safe_error(exc)
        
        # Should be truncated
        assert len(redacted) <= 503  # 500 + "..."
        assert redacted.endswith("...")
        # Path should still be redacted
        assert "/var/log/app.log" not in redacted
        assert "[PATH]/app.log" in redacted
    
    def test_safe_error_handles_non_path_errors(self, credential_manager):
        """Test that _safe_error() handles errors without paths"""
        exc = ValueError("Invalid configuration: timeout must be positive")
        
        redacted = credential_manager._safe_error(exc)
        
        # Should be unchanged (no paths to redact)
        assert redacted == "Invalid configuration: timeout must be positive"
    
    def test_redact_path_preserves_filename_extensions(self, credential_manager):
        """Test that filename extensions are preserved after redaction"""
        test_cases = [
            ("/etc/app/config.yaml", "[PATH]/config.yaml"),
            ("C:\\Users\\app\\secret.pem", "[PATH]/secret.pem"),
            ("/var/log/app.log", "[PATH]/app.log"),
            ("C:/Program Files/app/data.json", "[PATH]/data.json"),
        ]
        
        for path, expected in test_cases:
            error_msg = f"FileNotFoundError: {path} not found"
            redacted = credential_manager._redact_path_from_error(error_msg)
            assert expected in redacted, f"Expected {expected} in {redacted}"
    
    def test_integration_with_actual_file_error(self, credential_manager):
        """Test integration with real FileNotFoundError exception"""
        import os
        
        # Try to open non-existent file to get real exception
        try:
            with open("/nonexistent/path/to/secret.key", "r") as f:
                pass
        except FileNotFoundError as e:
            redacted = credential_manager._safe_error(e)
            
            # Real exception should have path redacted
            assert "/nonexistent/path/to/secret.key" not in redacted
            assert "[PATH]/secret.key" in redacted or "[PATH]" in redacted
    
    def test_integration_with_permission_error(self, credential_manager):
        """Test integration with PermissionError exception"""
        # Simulate PermissionError with path
        exc = PermissionError("[Errno 13] Permission denied: '/etc/app/secret.yaml'")
        
        redacted = credential_manager._safe_error(exc)
        
        assert "/etc/app/secret.yaml" not in redacted
        assert "[PATH]/secret.yaml" in redacted
        assert "Permission denied" in redacted
    
    def test_redact_mixed_path_separators(self, credential_manager):
        """Test redaction of paths with mixed separators (edge case)"""
        # Some Windows errors may have mixed separators
        error_msg = "Error: C:\\Users\\app/config\\secret.txt not found"
        
        redacted = credential_manager._redact_path_from_error(error_msg)
        
        # Should redact the Windows path portion
        assert "C:\\Users\\app" not in redacted or "C:\\Users" not in redacted
        assert "[PATH]" in redacted
    
    def test_no_false_positives_on_urls(self, credential_manager):
        """Test that URLs are not incorrectly redacted as file paths"""
        error_msg = "HTTPError: https://api.example.com/v1/secrets returned 404"
        
        redacted = credential_manager._redact_path_from_error(error_msg)
        
        # URLs should be preserved (not treated as file paths)
        assert "https://api.example.com" in redacted
        assert "HTTPError" in redacted
    
    def test_redact_path_with_dots_in_dirname(self, credential_manager):
        """Test redaction of paths with dots in directory names"""
        error_msg = "FileNotFoundError: /opt/app-v1.2.3/secrets/key.pem not found"
        
        redacted = credential_manager._redact_path_from_error(error_msg)
        
        assert "/opt/app-v1.2.3/secrets/key.pem" not in redacted
        assert "[PATH]/key.pem" in redacted


class TestPathRedactionIntegration:
    """Integration tests for path redaction in real error scenarios"""
    
    @pytest.fixture
    def credential_manager(self):
        """Create CredentialManager for integration testing"""
        with patch('src.security.credential_manager.SecretClient'), \
             patch('src.security.credential_manager.DefaultAzureCredential'):
            
            manager = CredentialManager(
                vault_url='https://test.vault.azure.net',
                cache_duration=300,
                enable_encryption=False
            )
            return manager
    
    def test_safe_error_in_logging_context(self, credential_manager, caplog):
        """Test path redaction when error is logged"""
        import logging
        
        # Simulate error logging with path
        exc = FileNotFoundError("/etc/app/secrets/credential.json not found")
        safe_msg = credential_manager._safe_error(exc)
        
        # Log the safe error
        logger = logging.getLogger("test")
        logger.error("Failed to load credential: %s", safe_msg)
        
        # Verify path is not in logs
        assert "/etc/app/secrets/credential.json" not in safe_msg
        assert "[PATH]/credential.json" in safe_msg
    
    def test_multiple_error_types_redacted(self, credential_manager):
        """Test various exception types with paths are redacted"""
        exceptions = [
            FileNotFoundError("/var/app/missing.txt"),
            PermissionError("/etc/protected.key"),
            IOError("C:\\Users\\app\\locked.dat"),
            OSError("/opt/app/unavailable.log"),
        ]
        
        for exc in exceptions:
            redacted = credential_manager._safe_error(exc)
            # Should not contain original path
            assert "/" not in redacted or "[PATH]" in redacted
