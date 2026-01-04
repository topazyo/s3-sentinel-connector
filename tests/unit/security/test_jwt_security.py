# tests/unit/security/test_jwt_security.py
"""
Unit tests for JWT security (B1-005/SEC-06 and B1-006/SEC-01).

Phase 5 (Security): Validates JWT secret handling and security requirements.
Phase 7 (Testing): Comprehensive coverage of security scenarios.
"""

import os
from unittest.mock import patch

import pytest

from src.security import SecurityManager
from src.security.access_control import AccessControl


def get_test_config(jwt_secret="my-plain-text-secret"):
    """Helper to create minimal test config."""
    return {
        "access_control": {"jwt_secret": jwt_secret},
        "encryption": {"key_store_path": "/tmp/keys"},
        "audit": {"log_path": "/tmp/audit.log"},
        "credentials": {"cache_duration": 300, "enable_encryption": True},
        "azure": {"key_vault_url": "https://vault.azure.net"},
        "security_policy": {},
        "rotation": {  # Required by SecurityManager
            "enabled": True,
            "max_age_days": 90,
            "min_rotation_interval_hours": 24,
        },
    }


class TestPlainTextJWTBlocking:
    """Test B1-005: Plain-text JWT blocking in production."""

    @patch.dict(os.environ, {"APP_ENV": "production"}, clear=False)
    def test_plain_text_jwt_blocked_in_production(self):
        """Phase 5 (B1-005): Plain-text JWT should be rejected in production."""
        config = get_test_config("my-plain-text-secret")

        with pytest.raises(RuntimeError) as exc_info:
            SecurityManager(config)

        error_msg = str(exc_info.value)
        assert "Plain-text JWT secrets are not allowed in production" in error_msg
        assert "env:JWT_SECRET" in error_msg
        assert "keyvault:jwt-secret" in error_msg

    @patch.dict(os.environ, {"APP_ENV": "development"}, clear=False)
    def test_plain_text_jwt_allowed_in_development(self):
        """Phase 5 (B1-005): Plain-text JWT allowed in dev with warning."""
        config = get_test_config("dev-secret-key-12345678901234567890")

        # Should not raise
        manager = SecurityManager(config)

        # Verify access control initialized
        assert manager.access_control is not None
        assert (
            manager.access_control.jwt_secret == "dev-secret-key-12345678901234567890"
        )

    @patch.dict(os.environ, {"APP_ENV": "test"}, clear=False)
    def test_plain_text_jwt_allowed_in_test(self):
        """Phase 5: Plain-text JWT allowed in test environment."""
        config = get_test_config("test-secret-key-12345678901234567890")

        # Should not raise
        manager = SecurityManager(config)
        assert manager.access_control is not None

    @patch.dict(os.environ, {}, clear=True)
    def test_plain_text_jwt_allowed_when_no_app_env(self):
        """Phase 5: Default to development when APP_ENV not set."""
        config = get_test_config("default-secret-key-12345678901234567890")

        # Should default to development and allow
        manager = SecurityManager(config)
        assert manager.access_control is not None

    @patch.dict(os.environ, {"APP_ENV": "PRODUCTION"}, clear=False)
    def test_production_case_insensitive(self):
        """Phase 5: Production check should be case-insensitive."""
        config = get_test_config("my-plain-text-secret")

        with pytest.raises(RuntimeError) as exc_info:
            SecurityManager(config)

        assert "Plain-text JWT secrets are not allowed in production" in str(
            exc_info.value
        )


class TestSecureJWTFormats:
    """Test secure JWT format acceptance."""

    @patch.dict(
        os.environ,
        {"APP_ENV": "production", "JWT_SECRET": "secure-prod-secret-1234567890123456"},
        clear=False,
    )
    def test_env_var_format_accepted_in_production(self):
        """Phase 5 (B1-005): env: format should be accepted in production."""
        config = get_test_config("env:JWT_SECRET")

        # Should not raise
        manager = SecurityManager(config)
        assert manager.access_control is not None
        assert (
            manager.access_control.jwt_secret == "secure-prod-secret-1234567890123456"
        )

    @patch.dict(os.environ, {"APP_ENV": "production"}, clear=False)
    def test_keyvault_format_rejected_in_sync_init(self):
        """Phase 5: keyvault: format requires async factory method."""
        config = get_test_config("keyvault:jwt-secret")

        with pytest.raises(RuntimeError) as exc_info:
            SecurityManager(config)

        error_msg = str(exc_info.value)
        assert "does not support Key Vault JWT secrets" in error_msg
        assert "await SecurityManager.create()" in error_msg

    @patch.dict(
        os.environ,
        {"APP_ENV": "production", "MY_JWT": "prod-jwt-secret-12345678901234567890"},
        clear=False,
    )
    def test_custom_env_var_name(self):
        """Phase 5: Custom environment variable names should work."""
        config = get_test_config("env:MY_JWT")

        manager = SecurityManager(config)
        assert (
            manager.access_control.jwt_secret == "prod-jwt-secret-12345678901234567890"
        )

    @patch.dict(os.environ, {"APP_ENV": "production"}, clear=False)
    def test_missing_env_var_raises_error(self):
        """Phase 5: Missing environment variable should raise clear error."""
        config = get_test_config("env:MISSING_JWT")

        with pytest.raises(RuntimeError) as exc_info:
            SecurityManager(config)

        error_msg = str(exc_info.value)
        assert "MISSING_JWT" in error_msg
        assert "not set" in error_msg


class TestJWTSecretLengthValidation:
    """Test B1-006: JWT secret length validation."""

    def test_short_jwt_secret_rejected(self):
        """Phase 5 (B1-006): JWT secrets shorter than 32 bytes should be rejected."""
        short_secret = "short"  # Only 5 bytes

        with pytest.raises(ValueError) as exc_info:
            AccessControl(jwt_secret=short_secret)

        error_msg = str(exc_info.value)
        assert "at least 32 bytes" in error_msg or "JWT secret must be" in error_msg

    def test_32_byte_jwt_secret_accepted(self):
        """Phase 5 (B1-006): Exactly 32 byte secret should be accepted."""
        valid_secret = "a" * 32  # Exactly 32 bytes

        # Should not raise
        access_control = AccessControl(jwt_secret=valid_secret)
        assert access_control.jwt_secret == valid_secret

    def test_long_jwt_secret_accepted(self):
        """Phase 5 (B1-006): Secrets longer than 32 bytes should be accepted."""
        long_secret = "a" * 64  # 64 bytes

        access_control = AccessControl(jwt_secret=long_secret)
        assert access_control.jwt_secret == long_secret

    def test_31_byte_jwt_secret_rejected(self):
        """Phase 5 (B1-006): 31 byte secret (just under limit) should be rejected."""
        almost_valid = "a" * 31  # Just under 32 bytes

        with pytest.raises(ValueError) as exc_info:
            AccessControl(jwt_secret=almost_valid)

        assert "32 bytes" in str(exc_info.value)


class TestJWTAlgorithmSecurity:
    """Test JWT algorithm security (SEC-01)."""

    def test_hs256_algorithm_enforced(self):
        """Phase 5 (SEC-01): HS256 algorithm should be used for JWT."""
        from src.security.access_control import Role, User

        access_control = AccessControl(jwt_secret="a" * 32)

        # Add test user and role
        test_role = Role(name="test", permissions=["test:read"])
        access_control.add_role(test_role)
        test_user = User(username="testuser", roles=["test"], active=True)
        access_control.add_user(test_user)

        # Generate token
        token = access_control.generate_token("testuser", expiry=300)

        # Decode and verify algorithm
        import jwt

        header = jwt.get_unverified_header(token)
        assert header["alg"] == "HS256"

    def test_token_validation_requires_hs256(self):
        """Phase 5: Token validation should only accept HS256."""
        access_control = AccessControl(jwt_secret="a" * 32)

        # Try to create token with different algorithm (simulated)
        import jwt

        # Create token with 'none' algorithm (algorithm confusion attack)
        # Note: For 'none' algorithm, key must be None per PyJWT requirements
        malicious_token = jwt.encode(
            {"username": "attacker", "exp": 9999999999},
            None,  # Key must be None for algorithm='none'
            algorithm="none",  # Algorithm confusion attack
        )

        # Should raise ValueError when validating with HS256-only policy
        with pytest.raises((ValueError, jwt.exceptions.InvalidAlgorithmError)):
            access_control.validate_token(malicious_token)


class TestSecurityErrorMessages:
    """Test that security error messages are informative but don't leak secrets."""

    @patch.dict(os.environ, {"APP_ENV": "production"}, clear=False)
    def test_error_message_does_not_leak_secret(self):
        """Phase 5: Error messages should not contain the actual secret."""
        plain_secret = "super-secret-key-do-not-leak-this"
        config = get_test_config(plain_secret)

        with pytest.raises(RuntimeError) as exc_info:
            SecurityManager(config)

        error_msg = str(exc_info.value)
        # Error should not contain the actual secret
        assert plain_secret not in error_msg
        assert "Plain-text JWT secrets are not allowed" in error_msg

    @patch.dict(os.environ, {"APP_ENV": "production"}, clear=False)
    def test_error_provides_migration_guidance(self):
        """Phase 4 (Observability): Errors should guide users to correct format."""
        config = get_test_config("plain-secret")

        with pytest.raises(RuntimeError) as exc_info:
            SecurityManager(config)

        error_msg = str(exc_info.value)
        # Should provide actionable guidance
        assert "env:JWT_SECRET" in error_msg
        assert "keyvault:jwt-secret" in error_msg


class TestBackwardsCompatibility:
    """Test backwards compatibility and migration path."""

    @patch.dict(os.environ, {"APP_ENV": "development"}, clear=False)
    def test_existing_dev_setups_continue_working(self):
        """Phase 2 (Consistency): Existing dev setups should continue working."""
        # Simulates legacy config that was working before
        config = get_test_config("legacy-dev-secret-key-12345678901234")

        # Should work with warning
        manager = SecurityManager(config)
        assert manager.access_control is not None

    @patch.dict(
        os.environ,
        {"APP_ENV": "staging", "JWT_SECRET": "staging-secret-key-1234567890123456"},
        clear=False,
    )
    def test_staging_environment_secure_format(self):
        """Phase 5: Staging should use secure format (treat as production-like)."""
        config = get_test_config("env:JWT_SECRET")

        # Should work (staging allowed, but encourage secure format)
        manager = SecurityManager(config)
        assert (
            manager.access_control.jwt_secret == "staging-secret-key-1234567890123456"
        )
