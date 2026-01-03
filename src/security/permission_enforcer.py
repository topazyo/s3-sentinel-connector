# src/security/permission_enforcer.py
"""
Permission enforcement utilities (B1-007/SEC-02).

Provides runtime decoration of sensitive methods with @require_permission checks.

Phase 5 (Security): Enforces role-based access control on sensitive operations
Phase 3 (Contracts): Documents permission requirements for each operation
"""

from typing import Callable, Any
from functools import wraps
import logging

logger = logging.getLogger(__name__)


class PermissionEnforcer:
    """
    Enforces permission checks on sensitive operations.
    
    Phase 5 (Security - B1-007/SEC-02): Applies @require_permission decorator
    at runtime to sensitive methods based on configuration.
    """
    
    # Permission mappings for sensitive operations
    OPERATION_PERMISSIONS = {
        'config.get_secret': 'read:secrets',
        'encryption.encrypt': 'manage:encryption',
        'encryption.decrypt': 'manage:encryption',
        's3.delete_object': 'delete:objects',
        'credential.rotate': 'manage:credentials',
    }
    
    def __init__(self, access_control):
        """
        Initialize permission enforcer.
        
        Args:
            access_control: AccessControl instance for permission checks
        """
        self.access_control = access_control
        self.logger = logging.getLogger(__name__)
    
    def enforce_permissions(self, 
                          config_manager=None,
                          encryption_manager=None,
                          s3_handler=None,
                          credential_manager=None):
        """
        Apply permission decorators to sensitive methods.
        
        Args:
            config_manager: ConfigManager instance (optional)
            encryption_manager: EncryptionManager instance (optional)
            s3_handler: S3Handler instance (optional)
            credential_manager: CredentialManager instance (optional)
            
        Phase 5 (Security - B1-007): Wraps methods with permission checks
        """
        if config_manager and hasattr(config_manager, 'get_secret'):
            self._wrap_method(
                config_manager, 
                'get_secret', 
                'read:secrets'
            )
            self.logger.info("Applied permission check to ConfigManager.get_secret")
        
        if encryption_manager:
            if hasattr(encryption_manager, 'encrypt'):
                self._wrap_method(
                    encryption_manager, 
                    'encrypt', 
                    'manage:encryption'
                )
                self.logger.info("Applied permission check to EncryptionManager.encrypt")
            
            if hasattr(encryption_manager, 'decrypt'):
                self._wrap_method(
                    encryption_manager, 
                    'decrypt', 
                    'manage:encryption'
                )
                self.logger.info("Applied permission check to EncryptionManager.decrypt")
        
        if s3_handler and hasattr(s3_handler, 'delete_object'):
            self._wrap_method(
                s3_handler, 
                'delete_object', 
                'delete:objects'
            )
            self.logger.info("Applied permission check to S3Handler.delete_object")
        
        if credential_manager and hasattr(credential_manager, 'rotate_credential'):
            self._wrap_method(
                credential_manager, 
                'rotate_credential', 
                'manage:credentials'
            )
            self.logger.info("Applied permission check to CredentialManager.rotate_credential")
    
    def _wrap_method(self, obj: Any, method_name: str, permission: str):
        """
        Wrap a method with permission checking decorator.
        
        Args:
            obj: Object containing the method
            method_name: Name of method to wrap
            permission: Required permission string
            
        Phase 5 (Security - B1-007): Runtime method decoration
        """
        original_method = getattr(obj, method_name)
        
        @wraps(original_method)
        def wrapper(*args, **kwargs):
            # Check permission via access_control
            decorator = self.access_control.require_permission(permission)
            decorated = decorator(original_method)
            return decorated(*args, **kwargs)
        
        # For async methods
        if hasattr(original_method, '__call__'):
            import asyncio
            import inspect
            
            if inspect.iscoroutinefunction(original_method):
                @wraps(original_method)
                async def async_wrapper(*args, **kwargs):
                    # Check permission before calling
                    try:
                        username = self.access_control._get_current_user()
                        if not self.access_control.has_permission(username, permission):
                            raise PermissionError(
                                f"User {username} lacks permission: {permission}"
                            )
                    except RuntimeError as e:
                        # No user context set
                        raise PermissionError(
                            f"No user context set. Permission required: {permission}. "
                            f"Call set_current_user() before invoking {method_name}()."
                        ) from e
                    
                    # Call original method
                    return await original_method(*args, **kwargs)
                
                setattr(obj, method_name, async_wrapper)
                return
        
        # For sync methods
        @wraps(original_method)
        def sync_wrapper(*args, **kwargs):
            # Check permission before calling
            try:
                username = self.access_control._get_current_user()
                if not self.access_control.has_permission(username, permission):
                    raise PermissionError(
                        f"User {username} lacks permission: {permission}"
                    )
            except RuntimeError as e:
                # No user context set
                raise PermissionError(
                    f"No user context set. Permission required: {permission}. "
                    f"Call set_current_user() before invoking {method_name}()."
                ) from e
            
            # Call original method
            return original_method(*args, **kwargs)
        
        setattr(obj, method_name, sync_wrapper)
    
    def create_permission_context(self, username: str):
        """
        Context manager for setting user context.
        
        Usage:
            with enforcer.create_permission_context('admin'):
                config.get_secret('my-secret')
        
        Args:
            username: Username to set as current user
            
        Phase 5 (Security - B1-007): Simplifies permission context management
        """
        class PermissionContext:
            def __init__(self, access_control, username):
                self.access_control = access_control
                self.username = username
            
            def __enter__(self):
                self.access_control.set_current_user(self.username)
                return self
            
            def __exit__(self, exc_type, exc_val, exc_tb):
                self.access_control.clear_current_user()
                return False
        
        return PermissionContext(self.access_control, username)
