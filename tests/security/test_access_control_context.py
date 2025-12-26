# tests/security/test_access_control_context.py

import pytest
from src.security.access_control import AccessControl, Role, User


class TestAccessControlContext:
    """Test context-based user management in AccessControl"""
    
    @pytest.fixture
    def access_control(self):
        """Create AccessControl instance with test data"""
        ac = AccessControl(jwt_secret="test-secret-key")
        
        # Add test roles
        admin_role = Role(
            name="admin",
            permissions=["read", "write", "delete", "admin"],
            description="Administrator role"
        )
        viewer_role = Role(
            name="viewer",
            permissions=["read"],
            description="Read-only viewer"
        )
        
        ac.add_role(admin_role)
        ac.add_role(viewer_role)
        
        # Add test users
        admin_user = User(username="admin_user", roles=["admin"], active=True)
        viewer_user = User(username="viewer_user", roles=["viewer"], active=True)
        
        ac.add_user(admin_user)
        ac.add_user(viewer_user)
        
        return ac
    
    def test_get_current_user_no_context(self, access_control):
        """Test _get_current_user raises error when no context set"""
        with pytest.raises(RuntimeError) as exc_info:
            access_control._get_current_user()
        
        assert "No user context set" in str(exc_info.value)
    
    def test_set_and_get_current_user(self, access_control):
        """Test setting and getting current user"""
        access_control.set_current_user("admin_user")
        username = access_control._get_current_user()
        
        assert username == "admin_user"
    
    def test_clear_current_user(self, access_control):
        """Test clearing current user context"""
        access_control.set_current_user("admin_user")
        access_control.clear_current_user()
        
        with pytest.raises(RuntimeError):
            access_control._get_current_user()
    
    def test_require_permission_with_valid_user(self, access_control):
        """Test @require_permission decorator with valid user"""
        access_control.set_current_user("admin_user")
        
        @access_control.require_permission("write")
        def protected_function():
            return "success"
        
        result = protected_function()
        assert result == "success"
    
    def test_require_permission_without_permission(self, access_control):
        """Test @require_permission decorator denies insufficient permissions"""
        access_control.set_current_user("viewer_user")
        
        @access_control.require_permission("write")
        def protected_function():
            return "success"
        
        with pytest.raises(PermissionError) as exc_info:
            protected_function()
        
        assert "viewer_user lacks permission: write" in str(exc_info.value)
    
    def test_require_permission_no_context(self, access_control):
        """Test @require_permission decorator fails without user context"""
        # Clear any previous context
        access_control.clear_current_user()
        
        @access_control.require_permission("read")
        def protected_function():
            return "success"
        
        with pytest.raises(RuntimeError) as exc_info:
            protected_function()
        
        assert "No user context set" in str(exc_info.value)
    
    def test_context_isolation(self, access_control):
        """Test that context changes don't affect each other"""
        access_control.set_current_user("admin_user")
        username1 = access_control._get_current_user()
        
        access_control.set_current_user("viewer_user")
        username2 = access_control._get_current_user()
        
        assert username1 == "admin_user"
        assert username2 == "viewer_user"
    
    def test_multiple_permission_checks(self, access_control):
        """Test multiple permission-protected functions"""
        access_control.set_current_user("admin_user")
        
        @access_control.require_permission("read")
        def read_data():
            return "read"
        
        @access_control.require_permission("write")
        def write_data():
            return "write"
        
        @access_control.require_permission("delete")
        def delete_data():
            return "delete"
        
        assert read_data() == "read"
        assert write_data() == "write"
        assert delete_data() == "delete"
