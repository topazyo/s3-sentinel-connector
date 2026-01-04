# tests/security/test_config_validator.py

import pytest

from src.security.config_validator import ConfigurationValidator, SecurityPolicy


class TestConfigurationValidator:
    @pytest.fixture
    def validator(self):
        return ConfigurationValidator(
            SecurityPolicy(
                min_password_length=12,
                require_special_chars=True,
                require_numbers=True,
                max_credential_age_days=90,
            )
        )

    def test_validate_credential_config(self, validator):
        config = {
            "credentials": {
                "min_length": 8,  # Too short
                "rotation_days": 120,  # Too long
                "encrypt_at_rest": False,  # Required
            }
        }

        results = validator.validate_configuration(config)
        assert not results["valid"]
        assert len(results["violations"]) == 3

    def test_validate_encryption_config(self, validator):
        config = {
            "encryption": {"algorithm": "DES", "key_bits": 128}  # Insecure  # Too weak
        }

        results = validator.validate_configuration(config)
        assert not results["valid"]
        assert len(results["violations"]) == 2

    def test_validate_network_config(self, validator):
        config = {
            "network": {
                "allowed_ips": ["256.256.256.256"],  # Invalid
                "protocols": ["http", "https"],  # Contains insecure
            }
        }

        results = validator.validate_configuration(config)
        assert not results["valid"]
        assert len(results["violations"]) == 2

    def test_sensitive_data_detection(self, validator):
        config = {
            "database": {
                "password": "secret123",  # Should be detected
                "connection_string": "Server=myserver;Password=pass123",  # Should be detected
            }
        }

        results = validator.validate_configuration(config)
        assert len(results["warnings"]) == 2
