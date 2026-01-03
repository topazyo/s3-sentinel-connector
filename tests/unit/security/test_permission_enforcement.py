# tests/unit/security/test_permission_enforcement.py
"""
Unit tests for permission enforcement (B1-007/SEC-02).

Phase 5 (Security): Validates that @require_permission decorator enforces authorization.
Phase 7 (Testing): Comprehensive coverage of permission scenarios.
"""

import pytest
from unittest.mock import Mock, MagicMock
from src.security.access_control import AccessControl, User, Role
from src.security.permission_enforcer import PermissionEnforcer


class TestPermissionEnforcement:
    """Test permission enforcement on sensitive operations."""
    
    def setup_method(self):
        """Set up test fixtures."""
        # Create access control with test user
        self.access_control = AccessControl(jwt_secret='a' * 32)
        
        # Create roles
        admin_role = Role(
            name='admin',
            permissions=['read:secrets', 'manage:encryption', 'delete:objects', 'manage:credentials']
        )
        readonly_role = Role(
            name='readonly',
            permissions=['read:config']
        )
        
        self.access_control.add_role(admin_role)
        self.access_control.add_role(readonly_role)
        
        # Create users
        admin_user = User(username='admin', roles=['admin'], active=True)
        readonly_user = User(username='readonly', roles=['readonly'], active=True)
        
        self.access_control.add_user(admin_user)
        self.access_control.add_user(readonly_user)
        
        # Create enforcer
        self.enforcer = PermissionEnforcer(self.access_control)
    
    def test_get_secret_requires_permission(self):
        """Phase 5 (B1-007): get_secret should require 'read:secrets' permission."""
        # Mock ConfigManager
        config_manager = Mock()
        config_manager.get_secret = Mock(return_value='secret-value')
        
        # Apply enforcement
        self.enforcer.enforce_permissions(config_manager=config_manager)
        
        # Try with admin (has permission)
        self.access_control.set_current_user('admin')
        result = config_manager.get_secret('test-secret')
        assert result == 'secret-value'
        
        # Try with readonly (lacks permission)
        self.access_control.set_current_user('readonly')
        with pytest.raises(PermissionError) as exc_info:
            config_manager.get_secret('test-secret')
        
        assert 'read:secrets' in str(exc_info.value)
    
    def test_encrypt_requires_permission(self):
        """Phase 5 (B1-007): encrypt should require 'manage:encryption' permission."""
        # Mock EncryptionManager
        encryption_manager = Mock()
        encryption_manager.encrypt = Mock(return_value=b'encrypted')
        
        # Apply enforcement
        self.enforcer.enforce_permissions(encryption_manager=encryption_manager)
        
        # Try with admin (has permission)
        self.access_control.set_current_user('admin')
        result = encryption_manager.encrypt('data')
        assert result == b'encrypted'
        
        # Try with readonly (lacks permission)
        self.access_control.set_current_user('readonly')
        with pytest.raises(PermissionError) as exc_info:
            encryption_manager.encrypt('data')
        
        assert 'manage:encryption' in str(exc_info.value)
    
    def test_decrypt_requires_permission(self):
        """Phase 5 (B1-007): decrypt should require 'manage:encryption' permission."""
        # Mock EncryptionManager
        encryption_manager = Mock()
        encryption_manager.decrypt = Mock(return_value=b'decrypted')
        
        # Apply enforcement
        self.enforcer.enforce_permissions(encryption_manager=encryption_manager)
        
        # Try with admin (has permission)
        self.access_control.set_current_user('admin')
        result = encryption_manager.decrypt(b'encrypted')
        assert result == b'decrypted'
        
        # Try with readonly (lacks permission)
        self.access_control.set_current_user('readonly')
        with pytest.raises(PermissionError) as exc_info:
            encryption_manager.decrypt(b'encrypted')
        
        assert 'manage:encryption' in str(exc_info.value)
    
    def test_no_user_context_raises_error(self):
        """Phase 5 (B1-007): Operations without user context should fail."""
        # Mock ConfigManager
        config_manager = Mock()
        config_manager.get_secret = Mock(return_value='secret-value')
        
        # Apply enforcement
        self.enforcer.enforce_permissions(config_manager=config_manager)
        
        # Clear user context
        self.access_control.clear_current_user()
        
        # Try without setting user
        with pytest.raises(PermissionError) as exc_info:
            config_manager.get_secret('test-secret')
        
        assert 'No user context set' in str(exc_info.value)
        assert 'set_current_user()' in str(exc_info.value)
    
    def test_permission_context_manager(self):
        """Phase 5 (B1-007): Context manager should simplify user context."""
        # Mock ConfigManager
        config_manager = Mock()
        config_manager.get_secret = Mock(return_value='secret-value')
        
        # Apply enforcement
        self.enforcer.enforce_permissions(config_manager=config_manager)
        
        # Use context manager
        with self.enforcer.create_permission_context('admin'):
            result = config_manager.get_secret('test-secret')
            assert result == 'secret-value'
        
        # Context should be cleared after exiting
        with pytest.raises(PermissionError):
            config_manager.get_secret('test-secret')
    
    def test_inactive_user_denied(self):
        """Phase 5: Inactive users should be denied access."""
        # Create inactive user
        inactive_user = User(username='inactive', roles=['admin'], active=False)
        self.access_control.add_user(inactive_user)
        
        # Mock ConfigManager
        config_manager = Mock()
        config_manager.get_secret = Mock(return_value='secret-value')
        
        # Apply enforcement
        self.enforcer.enforce_permissions(config_manager=config_manager)
        
        # Try with inactive user
        self.access_control.set_current_user('inactive')
        with pytest.raises(PermissionError) as exc_info:
            config_manager.get_secret('test-secret')
        
        assert 'lacks permission' in str(exc_info.value)
    
    def test_multiple_permissions(self):
        """Phase 5: User with multiple roles should have combined permissions."""
        # Create user with multiple roles
        power_user_role = Role(
            name='power_user',
            permissions=['read:secrets', 'delete:objects']
        )
        self.access_control.add_role(power_user_role)
        
        multi_role_user = User(
            username='multi',
            roles=['readonly', 'power_user'],
            active=True
        )
        self.access_control.add_user(multi_role_user)
        
        # Mock ConfigManager
        config_manager = Mock()
        config_manager.get_secret = Mock(return_value='secret-value')
        
        # Apply enforcement
        self.enforcer.enforce_permissions(config_manager=config_manager)
        
        # User should have read:secrets from power_user role
        self.access_control.set_current_user('multi')
        result = config_manager.get_secret('test-secret')
        assert result == 'secret-value'


class TestAsyncPermissionEnforcement:
    """Test permission enforcement on async methods."""
    
    def setup_method(self):
        """Set up test fixtures."""
        # Create access control
        self.access_control = AccessControl(jwt_secret='a' * 32)
        
        # Create admin role
        admin_role = Role(
            name='admin',
            permissions=['read:secrets']
        )
        self.access_control.add_role(admin_role)
        
        # Create admin user
        admin_user = User(username='admin', roles=['admin'], active=True)
        self.access_control.add_user(admin_user)
        
        # Create enforcer
        self.enforcer = PermissionEnforcer(self.access_control)
    
    @pytest.mark.asyncio
    async def test_async_get_secret_requires_permission(self):
        """Phase 5 (B1-007): Async get_secret should enforce permissions."""
        # Create async mock
        async def mock_get_secret(secret_name):
            return 'secret-value'
        
        config_manager = Mock()
        config_manager.get_secret = mock_get_secret
        
        # Apply enforcement
        self.enforcer.enforce_permissions(config_manager=config_manager)
        
        # Try with admin
        self.access_control.set_current_user('admin')
        result = await config_manager.get_secret('test-secret')
        assert result == 'secret-value'
    
    @pytest.mark.asyncio
    async def test_async_without_permission_fails(self):
        """Phase 5: Async methods should deny without permission."""
        # Create async mock
        async def mock_get_secret(secret_name):
            return 'secret-value'
        
        config_manager = Mock()
        config_manager.get_secret = mock_get_secret
        
        # Create readonly user
        readonly_role = Role(name='readonly', permissions=[])
        self.access_control.add_role(readonly_role)
        readonly_user = User(username='readonly', roles=['readonly'], active=True)
        self.access_control.add_user(readonly_user)
        
        # Apply enforcement
        self.enforcer.enforce_permissions(config_manager=config_manager)
        
        # Try with readonly
        self.access_control.set_current_user('readonly')
        with pytest.raises(PermissionError):
            await config_manager.get_secret('test-secret')


class TestPermissionErrorMessages:
    """Test that permission error messages are informative."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.access_control = AccessControl(jwt_secret='a' * 32)
        
        readonly_role = Role(name='readonly', permissions=[])
        self.access_control.add_role(readonly_role)
        
        readonly_user = User(username='testuser', roles=['readonly'], active=True)
        self.access_control.add_user(readonly_user)
        
        self.enforcer = PermissionEnforcer(self.access_control)
    
    def test_error_contains_username(self):
        """Phase 4 (Observability): Error should identify the user."""
        config_manager = Mock()
        config_manager.get_secret = Mock(return_value='secret')
        
        self.enforcer.enforce_permissions(config_manager=config_manager)
        
        self.access_control.set_current_user('testuser')
        
        with pytest.raises(PermissionError) as exc_info:
            config_manager.get_secret('test-secret')
        
        error_msg = str(exc_info.value)
        assert 'testuser' in error_msg
    
    def test_error_contains_required_permission(self):
        """Phase 4: Error should state required permission."""
        config_manager = Mock()
        config_manager.get_secret = Mock(return_value='secret')
        
        self.enforcer.enforce_permissions(config_manager=config_manager)
        
        self.access_control.set_current_user('testuser')
        
        with pytest.raises(PermissionError) as exc_info:
            config_manager.get_secret('test-secret')
        
        error_msg = str(exc_info.value)
        assert 'read:secrets' in error_msg
    
    def test_no_context_error_provides_guidance(self):
        """Phase 4: No context error should guide user."""
        config_manager = Mock()
        config_manager.get_secret = Mock(return_value='secret')
        
        self.enforcer.enforce_permissions(config_manager=config_manager)
        
        # Clear any existing user context
        self.access_control.clear_current_user()
        
        with pytest.raises(PermissionError) as exc_info:
            config_manager.get_secret('test-secret')
        
        error_msg = str(exc_info.value)
        assert 'set_current_user()' in error_msg
        assert 'No user context set' in error_msg
