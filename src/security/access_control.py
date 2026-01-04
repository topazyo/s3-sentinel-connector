# src/security/access_control.py

import logging
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Dict, List, Optional, Set

import jwt

# Context variable to store current user in async contexts
_current_user_context: ContextVar[Optional[str]] = ContextVar(
    "current_user", default=None
)


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
    """
    Manages user authentication and authorization.

    Provides JWT token generation/validation and role-based access control.

    Phase 5 (Security - B1-006/SEC-01): Enforces minimum 32-byte JWT secret
    """

    # Phase 5 (Security - B1-006): Minimum JWT secret length (256 bits)
    MIN_JWT_SECRET_LENGTH = 32  # bytes

    def __init__(
        self, jwt_secret: str, min_secret_length: Optional[int] = None
    ) -> None:
        """
        Initialize access control with JWT secret validation.

        Args:
            jwt_secret: JWT signing secret (minimum 32 bytes for security)
            min_secret_length: Override minimum length (default: 32 bytes)

        Raises:
            ValueError: If JWT secret is shorter than minimum length

        Phase 5 (Security - B1-006/SEC-01): Validates JWT secret strength
        """
        if min_secret_length is None:
            min_secret_length = self.MIN_JWT_SECRET_LENGTH

        # Phase 5 (Security - B1-006): Enforce minimum secret length
        if len(jwt_secret) < min_secret_length:
            raise ValueError(
                f"JWT secret must be at least {min_secret_length} bytes for security. "
                f"Current length: {len(jwt_secret)} bytes. "
                f"Use a cryptographically strong random string of at least 32 characters."
            )

        self.jwt_secret = jwt_secret
        self.roles: Dict[str, Role] = {}
        self.users: Dict[str, User] = {}
        self.logger = logging.getLogger(__name__)

        # Phase 5 (Security - B2-009/P1-SEC-01): Token revocation tracking
        self._revoked_tokens: Set[str] = set()  # Set of revoked token IDs (jti)
        self._revoked_token_expiry: Dict[str, datetime] = {}  # jti -> expiry time
        self._user_revocation_timestamps: Dict[str, datetime] = (
            {}
        )  # username -> revocation time

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
        """
        Generate JWT token for user with unique token ID (jti)

        Phase 5 (Security - B2-009/P1-SEC-01): Adds jti claim for revocation support

        Args:
            username: Username for token
            expiry: Token expiry in seconds (default: 1 hour)

        Returns:
            JWT token string
        """
        user = self.users.get(username)
        if not user or not user.active:
            raise ValueError(f"Invalid or inactive user: {username}")

        # Phase 5 (B2-009): Generate unique token ID for revocation tracking
        token_id = str(uuid.uuid4())

        payload = {
            "username": username,
            "roles": user.roles,
            "jti": token_id,  # JWT ID claim for revocation
            "iat": int(time.time()),  # Issued at
            "exp": int(time.time()) + expiry,
        }

        return jwt.encode(payload, self.jwt_secret, algorithm="HS256")

    def validate_token(self, token: str) -> Dict[str, Any]:
        """
        Validate JWT token and check revocation status

        Phase 5 (Security - B2-009/P1-SEC-01): Checks token revocation

        Args:
            token: JWT token string

        Returns:
            Decoded token payload

        Raises:
            ValueError: If token is invalid, expired, or revoked
        """
        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=["HS256"])
            username = payload.get("username")

            # Check user exists and is active
            user = self.users.get(username)
            if not user or not user.active:
                raise ValueError(f"Invalid or inactive user: {username}")

            # Phase 5 (B2-009): Check token revocation
            token_id = payload.get("jti")
            if token_id and self.is_token_revoked(token_id):
                self.logger.warning(
                    "Revoked token used", extra={"username": username, "jti": token_id}
                )
                raise ValueError("Token has been revoked")

            # Phase 5 (B2-009): Check user-level revocation
            issued_at = payload.get("iat")
            if issued_at and self._is_token_revoked_by_user(username, issued_at):
                self.logger.warning(
                    "Token issued before user revocation",
                    extra={"username": username, "iat": issued_at},
                )
                raise ValueError("All user tokens have been revoked")

            return payload

        except jwt.ExpiredSignatureError:
            raise ValueError("Token has expired") from None
        except jwt.InvalidTokenError as e:
            raise ValueError(f"Invalid token: {e!s}") from e

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

    # Phase 5 (Security - B2-009/P1-SEC-01): Token Revocation Methods

    def revoke_token(self, token: str, reason: Optional[str] = None) -> None:
        """
        Revoke a specific token by adding its jti to the revocation list.

        Phase 5 (B2-009): Emergency token revocation capability

        Args:
            token: JWT token string to revoke
            reason: Optional reason for revocation (for audit logging)

        Raises:
            ValueError: If token is invalid or missing jti claim
        """
        try:
            # Decode without verification to extract jti (token may be expired)
            payload = jwt.decode(token, options={"verify_signature": False})
            token_id = payload.get("jti")

            if not token_id:
                raise ValueError("Token missing jti claim - cannot revoke")

            # Add to revocation set
            self._revoked_tokens.add(token_id)

            # Track expiry for cleanup
            exp_timestamp = payload.get("exp")
            if exp_timestamp:
                self._revoked_token_expiry[token_id] = datetime.fromtimestamp(
                    exp_timestamp, tz=timezone.utc
                )

            # Audit log
            username = payload.get("username", "unknown")
            self.logger.warning(
                f"Token revoked: jti={token_id}, user={username}, reason={reason}",
                extra={
                    "event": "token_revoked",
                    "jti": token_id,
                    "username": username,
                    "reason": reason,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )

        except jwt.DecodeError as e:
            raise ValueError(f"Invalid token format: {e!s}") from e

    def revoke_all_user_tokens(
        self, username: str, reason: Optional[str] = None
    ) -> int:
        """
        Revoke all tokens for a specific user (emergency lockout).

        Phase 5 (B2-009): Mass revocation for compromised accounts

        Args:
            username: Username whose tokens should be revoked
            reason: Optional reason for revocation (for audit logging)

        Returns:
            Number of tokens revoked (0 if no tracking available)

        Note:
            This marks a revocation timestamp for the user. All tokens
            issued before this timestamp will be rejected.
        """
        revocation_time = datetime.now(timezone.utc)
        self._user_revocation_timestamps[username] = revocation_time

        # Audit log
        self.logger.warning(
            f"All tokens revoked for user: {username}, reason={reason}",
            extra={
                "event": "user_tokens_revoked",
                "username": username,
                "reason": reason,
                "revocation_time": revocation_time.isoformat(),
            },
        )

        # Count revoked tokens (approximate - based on active revocation set)
        revoked_count = sum(
            1
            for jti in self._revoked_tokens
            if self._get_username_from_jti(jti) == username
        )

        return revoked_count

    def is_token_revoked(self, token_id: str) -> bool:
        """
        Check if a token ID is in the revocation list.

        Phase 5 (B2-009): Revocation status check

        Args:
            token_id: Token jti claim value

        Returns:
            True if token is revoked, False otherwise
        """
        return token_id in self._revoked_tokens

    def _is_token_revoked_by_user(self, username: str, issued_at: int) -> bool:
        """
        Check if token was issued before user-level revocation.

        Phase 5 (B2-009): User-level revocation check

        Args:
            username: Token username
            issued_at: Token issued-at timestamp (seconds since epoch)

        Returns:
            True if user revoked all tokens after this token was issued
        """
        user_revocation = self._user_revocation_timestamps.get(username)
        if not user_revocation:
            return False

        token_issued = datetime.fromtimestamp(issued_at, tz=timezone.utc)
        return token_issued < user_revocation

    def cleanup_expired_revocations(self) -> int:
        """
        Remove expired tokens from revocation list (TTL-based cleanup).

        Phase 5 (B2-009): Prevent revocation list memory bloat

        Returns:
            Number of expired revocations removed
        """
        now = datetime.now(timezone.utc)
        expired_jtis = [
            jti for jti, expiry in self._revoked_token_expiry.items() if expiry < now
        ]

        for jti in expired_jtis:
            self._revoked_tokens.discard(jti)
            del self._revoked_token_expiry[jti]

        if expired_jtis:
            self.logger.info(
                f"Cleaned up {len(expired_jtis)} expired revocations",
                extra={"count": len(expired_jtis)},
            )

        return len(expired_jtis)

    def get_revocation_stats(self) -> Dict[str, Any]:
        """
        Get token revocation statistics.

        Phase 5 (B2-009): Revocation metrics for monitoring

        Returns:
            Dictionary with revocation counts and status
        """
        return {
            "total_revoked_tokens": len(self._revoked_tokens),
            "users_with_revocations": len(self._user_revocation_timestamps),
            "tracked_expiries": len(self._revoked_token_expiry),
        }

    def _get_username_from_jti(self, token_id: str) -> Optional[str]:
        """
        Extract username from revoked token ID (best effort).

        Note: This is a helper for statistics and may return None
        if the token information is not available.
        """
        # In production, this could be enhanced with a token metadata store
        # For now, return None as we don't store full token payloads
        return None
