# src/security/access_control.py

from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import jwt
import time
from functools import wraps
import logging
from contextvars import ContextVar

# Context variable to store current user in async contexts
_current_user_context: ContextVar[Optional[str]] = ContextVar('current_user', default=None)

@dataclass
class Role:
    """Role definition"""
    name: str
    permissions: List[str]
    description: Optional[str] = None

@dataclass
class User:
    """User definition"""
    username: str
    roles: List[str]
    active: bool = True

class AccessControl:
    def __init__(self, jwt_secret: str) -> None:
        """
        Initialize access control
        
        Args:
            jwt_secret: Secret for JWT token generation/validation
        """
        self.jwt_secret = jwt_secret
        self.roles: Dict[str, Role] = {}
        self.users: Dict[str, User] = {}
        self.logger = logging.getLogger(__name__)

    def add_role(self, role: Role) -> None:
        """Add role to access control"""
        self.roles[role.name] = role
        self.logger.info(f"Added role: {role.name}")

    def add_user(self, user: User) -> None:
        """Add user to access control"""
        self.users[user.username] = user
        self.logger.info(f"Added user: {user.username}")

    def has_permission(self, username: str, permission: str) -> bool:
        """Check if user has specific permission"""
        user = self.users.get(username)
        if not user or not user.active:
            return False
            
        user_permissions = set()
        for role_name in user.roles:
            role = self.roles.get(role_name)
            if role:
                user_permissions.update(role.permissions)
                
        return permission in user_permissions

    def generate_token(self, username: str, expiry: int = 3600) -> str:
        """Generate JWT token for user"""
        user = self.users.get(username)
        if not user or not user.active:
            raise ValueError(f"Invalid or inactive user: {username}")
            
        payload = {
            'username': username,
            'roles': user.roles,
            'exp': int(time.time()) + expiry
        }
        
        return jwt.encode(payload, self.jwt_secret, algorithm='HS256')

    def validate_token(self, token: str) -> Dict[str, Any]:
        """Validate JWT token"""
        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=['HS256'])
            username = payload.get('username')
            
            user = self.users.get(username)
            if not user or not user.active:
                raise ValueError(f"Invalid or inactive user: {username}")
                
            return payload
            
        except jwt.ExpiredSignatureError:
            raise ValueError("Token has expired")
        except jwt.InvalidTokenError as e:
            raise ValueError(f"Invalid token: {str(e)}") from e

    def require_permission(self, permission: str):
        """Decorator for permission-based access control"""
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                # Extract username from context or token
                username = self._get_current_user()
                
                if not self.has_permission(username, permission):
                    raise PermissionError(
                        f"User {username} lacks permission: {permission}"
                    )
                    
                return func(*args, **kwargs)
            return wrapper
        return decorator
    
    def _get_current_user(self) -> str:
        """
        Get current user from context.
        
        Returns:
            Username string
            
        Raises:
            RuntimeError: If no user context is set
            
        Note:
            User context should be set using set_current_user() before
            calling methods protected by @require_permission decorator.
        """
        username = _current_user_context.get()
        if username is None:
            raise RuntimeError(
                "No user context set. Call set_current_user() before "
                "invoking permission-protected methods."
            )
        return username
    
    def set_current_user(self, username: str) -> None:
        """
        Set current user in context.
        
        Args:
            username: Username to set as current user
            
        Note:
            This should be called at the start of request handling,
            typically after validating a JWT token.
        """
        _current_user_context.set(username)
    
    def clear_current_user(self) -> None:
        """
        Clear current user from context.
        
        Note:
            Should be called at end of request handling for cleanup.
        """
        _current_user_context.set(None)