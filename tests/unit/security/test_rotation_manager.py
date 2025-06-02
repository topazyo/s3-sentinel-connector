# tests/security/test_rotation_manager.py

import pytest
from datetime import datetime, timedelta
from src.security.rotation_manager import RotationManager
from src.security.credential_manager import CredentialManager

class TestRotationManager:
    @pytest.fixture
    def credential_manager(self):
        return CredentialManager(
            vault_url="https://test-vault.vault.azure.net"
        )

    @pytest.fixture
    def rotation_config(self):
        return {
            'test-credential': {
                'max_age_days': 90,
                'min_rotation_interval_hours': 24
            }
        }

    @pytest.fixture
    def rotation_manager(self, credential_manager, rotation_config):
        return RotationManager(credential_manager, rotation_config)

    async def test_check_rotation_needed(self, rotation_manager):
        # Set up test state
        rotation_manager._rotation_state = {
            'test-credential': {
                'last_rotation': datetime.utcnow() - timedelta(days=91)
            }
        }
        
        credentials = await rotation_manager.check_rotation_needed()
        assert 'test-credential' in credentials

    async def test_rotate_credentials(self, rotation_manager):
        results = await rotation_manager.rotate_credentials(['test-credential'])
        assert 'test-credential' in results['successful']

    def test_needs_rotation(self, rotation_manager):
        # Test credential that needs rotation
        old_rotation = datetime.utcnow() - timedelta(days=91)
        config = {'max_age_days': 90}
        assert rotation_manager._needs_rotation(old_rotation, config)
        
        # Test credential that doesn't need rotation
        recent_rotation = datetime.utcnow() - timedelta(days=45)
        assert not rotation_manager._needs_rotation(recent_rotation, config)

    def test_can_rotate(self, rotation_manager):
        # Test credential that can be rotated
        rotation_manager._rotation_state = {
            'test-credential': {
                'last_rotation': datetime.utcnow() - timedelta(hours=25)
            }
        }
        assert rotation_manager._can_rotate('test-credential')
        
        # Test credential that was recently rotated
        rotation_manager._rotation_state = {
            'test-credential': {
                'last_rotation': datetime.utcnow() - timedelta(hours=23)
            }
        }
        assert not rotation_manager._can_rotate('test-credential')