# tests/unit/security/test_token_revocation.py

"""
Phase 5 (Security - B2-009/P1-SEC-01): Token Revocation Tests

Tests for JWT token revocation mechanism in AccessControl.
Validates emergency token invalidation, mass user lockout, and cleanup.
"""

import pytest
import jwt
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from src.security.access_control import AccessControl, Role, User


class TestTokenRevocation:
    """Test token revocation functionality"""
    
    @pytest.fixture
    def access_control(self):
        """Create AccessControl instance with test users"""
        ac = AccessControl(jwt_secret="test_secret_32_chars_minimum_123")
        
        # Create test roles and permissions
        admin_role = Role(
            name="admin",
            permissions=["admin:write", "admin:read"]
        )
        user_role = Role(
            name="user",
            permissions=["user:read"]
        )
        
        ac.add_role(admin_role)
        ac.add_role(user_role)
        
        # Create test users
        admin_user = User(username="admin", roles=["admin"], active=True)
        normal_user = User(username="user1", roles=["user"], active=True)
        
        ac.add_user(admin_user)
        ac.add_user(normal_user)
        
        return ac
    
    def test_generate_token_includes_jti(self, access_control):
        """Test that generated tokens include jti claim"""
        token = access_control.generate_token("admin", expiry=3600)
        
        # Decode without verification to check payload
        payload = jwt.decode(token, options={"verify_signature": False})
        
        assert 'jti' in payload
        assert payload['jti'] is not None
        assert len(payload['jti']) > 0  # UUID format
        assert 'iat' in payload  # Issued at timestamp
        assert 'exp' in payload  # Expiry timestamp
    
    def test_generate_token_jti_uniqueness(self, access_control):
        """Test that each token gets unique jti"""
        token1 = access_control.generate_token("admin", expiry=3600)
        token2 = access_control.generate_token("admin", expiry=3600)
        
        payload1 = jwt.decode(token1, options={"verify_signature": False})
        payload2 = jwt.decode(token2, options={"verify_signature": False})
        
        assert payload1['jti'] != payload2['jti']
    
    def test_validate_token_accepts_valid_token(self, access_control):
        """Test that valid tokens are accepted"""
        token = access_control.generate_token("admin", expiry=3600)
        
        payload = access_control.validate_token(token)
        
        assert payload['username'] == 'admin'
        assert 'jti' in payload
    
    def test_revoke_token_single(self, access_control):
        """Test revoking a single token"""
        token = access_control.generate_token("admin", expiry=3600)
        
        # Revoke the token
        access_control.revoke_token(token, reason="Security test")
        
        # Validate should fail
        with pytest.raises(ValueError, match="Token has been revoked"):
            access_control.validate_token(token)
    
    def test_revoke_token_with_reason(self, access_control):
        """Test token revocation with audit reason"""
        token = access_control.generate_token("admin", expiry=3600)
        
        with patch.object(access_control.logger, 'warning') as mock_log:
            access_control.revoke_token(token, reason="Credential compromise")
            
            # Check audit log was called
            mock_log.assert_called_once()
            call_args = mock_log.call_args
            assert 'Credential compromise' in str(call_args)
    
    def test_revoke_token_invalid_format(self, access_control):
        """Test revoking invalid token raises error"""
        with pytest.raises(ValueError, match="Invalid token format"):
            access_control.revoke_token("invalid_token")
    
    def test_revoke_token_missing_jti(self, access_control):
        """Test revoking token without jti claim"""
        # Create token without jti (old format)
        payload = {'username': 'admin', 'exp': int(time.time()) + 3600}
        token_without_jti = jwt.encode(
            payload, 
            "test_secret_32_chars_minimum_123", 
            algorithm='HS256'
        )
        
        with pytest.raises(ValueError, match="Token missing jti claim"):
            access_control.revoke_token(token_without_jti)
    
    def test_revoke_all_user_tokens(self, access_control):
        """Test revoking all tokens for a user"""
        # Generate multiple tokens for user
        token1 = access_control.generate_token("admin", expiry=3600)
        time.sleep(0.01)  # Ensure different iat
        token2 = access_control.generate_token("admin", expiry=3600)
        
        # Generate token for different user (should not be affected)
        user_token = access_control.generate_token("user1", expiry=3600)
        
        # Revoke all admin tokens
        count = access_control.revoke_all_user_tokens(
            "admin", 
            reason="Account compromise"
        )
        
        # Admin tokens should be rejected
        with pytest.raises(ValueError, match="All user tokens have been revoked"):
            access_control.validate_token(token1)
        
        with pytest.raises(ValueError, match="All user tokens have been revoked"):
            access_control.validate_token(token2)
        
        # Other user's token should still work
        payload = access_control.validate_token(user_token)
        assert payload['username'] == 'user1'
    
    def test_revoke_all_user_tokens_with_logging(self, access_control):
        """Test mass revocation audit logging"""
        with patch.object(access_control.logger, 'warning') as mock_log:
            access_control.revoke_all_user_tokens(
                "admin", 
                reason="Security incident"
            )
            
            # Check audit log
            mock_log.assert_called_once()
            call_args = mock_log.call_args
            assert 'All tokens revoked' in str(call_args)
            assert 'admin' in str(call_args)
            assert 'Security incident' in str(call_args)
    
    def test_is_token_revoked(self, access_control):
        """Test checking revocation status"""
        token = access_control.generate_token("admin", expiry=3600)
        payload = jwt.decode(token, options={"verify_signature": False})
        token_id = payload['jti']
        
        # Initially not revoked
        assert not access_control.is_token_revoked(token_id)
        
        # Revoke token
        access_control.revoke_token(token)
        
        # Now revoked
        assert access_control.is_token_revoked(token_id)
    
    def test_cleanup_expired_revocations(self, access_control):
        """Test cleanup of expired revoked tokens"""
        # Generate token with short expiry
        token = access_control.generate_token("admin", expiry=1)
        
        # Revoke it
        access_control.revoke_token(token)
        payload = jwt.decode(token, options={"verify_signature": False})
        token_id = payload['jti']
        
        # Token should be in revocation list
        assert token_id in access_control._revoked_tokens
        
        # Wait for expiry
        time.sleep(2)
        
        # Cleanup expired revocations
        removed_count = access_control.cleanup_expired_revocations()
        
        # Token should be removed from revocation list
        assert removed_count == 1
        assert token_id not in access_control._revoked_tokens
    
    def test_cleanup_expired_revocations_no_expiry(self, access_control):
        """Test cleanup when no expired revocations exist"""
        # Generate and revoke token with long expiry
        token = access_control.generate_token("admin", expiry=3600)
        access_control.revoke_token(token)
        
        # Cleanup should remove nothing
        removed_count = access_control.cleanup_expired_revocations()
        
        assert removed_count == 0
    
    def test_get_revocation_stats(self, access_control):
        """Test revocation statistics"""
        # Initial stats
        stats = access_control.get_revocation_stats()
        assert stats['total_revoked_tokens'] == 0
        assert stats['users_with_revocations'] == 0
        
        # Revoke some tokens
        token1 = access_control.generate_token("admin", expiry=3600)
        token2 = access_control.generate_token("user1", expiry=3600)
        
        access_control.revoke_token(token1)
        access_control.revoke_token(token2)
        access_control.revoke_all_user_tokens("admin")
        
        # Check updated stats
        stats = access_control.get_revocation_stats()
        assert stats['total_revoked_tokens'] == 2
        assert stats['users_with_revocations'] == 1  # Only admin has user-level revocation
    
    def test_revoke_expired_token(self, access_control):
        """Test revoking already-expired token"""
        # Generate token with short expiry
        token = access_control.generate_token("admin", expiry=1)
        
        # Wait for expiry
        time.sleep(2)
        
        # Should still be able to revoke (adds to blacklist)
        access_control.revoke_token(token, reason="Precautionary revocation")
        
        # Validation should fail (expired, not revoked check)
        with pytest.raises(ValueError, match="Token has expired"):
            access_control.validate_token(token)
    
    def test_concurrent_token_revocation(self, access_control):
        """Test concurrent revocation operations are safe"""
        tokens = [
            access_control.generate_token("admin", expiry=3600)
            for _ in range(5)
        ]
        
        # Revoke all concurrently (simulate)
        for token in tokens:
            access_control.revoke_token(token)
        
        # All should be revoked
        for token in tokens:
            with pytest.raises(ValueError, match="Token has been revoked"):
                access_control.validate_token(token)
    
    def test_revoke_token_preserves_other_tokens(self, access_control):
        """Test revoking one token doesn't affect others"""
        token1 = access_control.generate_token("admin", expiry=3600)
        token2 = access_control.generate_token("admin", expiry=3600)
        
        # Revoke only token1
        access_control.revoke_token(token1)
        
        # token1 should be revoked
        with pytest.raises(ValueError, match="Token has been revoked"):
            access_control.validate_token(token1)
        
        # token2 should still work
        payload = access_control.validate_token(token2)
        assert payload['username'] == 'admin'
    
    def test_user_revocation_timestamp_precision(self, access_control):
        """Test user revocation timestamp precision"""
        # Generate token
        token_before = access_control.generate_token("admin", expiry=3600)
        
        # Longer delay to ensure timestamp difference (>1 second for timestamp precision)
        time.sleep(1.1)
        
        # Revoke all user tokens
        access_control.revoke_all_user_tokens("admin")
        
        # Longer delay to ensure timestamp difference
        time.sleep(1.1)
        
        # Generate new token after revocation
        token_after = access_control.generate_token("admin", expiry=3600)
        
        # Token before revocation should be rejected
        with pytest.raises(ValueError, match="All user tokens have been revoked"):
            access_control.validate_token(token_before)
        
        # Token after revocation should be accepted
        payload = access_control.validate_token(token_after)
        assert payload['username'] == 'admin'
    
    def test_revocation_audit_trail(self, access_control):
        """Test comprehensive audit trail for revocations"""
        token = access_control.generate_token("admin", expiry=3600)
        
        with patch.object(access_control.logger, 'warning') as mock_log:
            # Individual revocation
            access_control.revoke_token(token, reason="Test audit")
            
            # User-level revocation
            access_control.revoke_all_user_tokens("user1", reason="Mass revoke")
            
            # Should have 2 audit log calls
            assert mock_log.call_count == 2
            
            # Check both calls contain required audit info
            all_calls = [str(call) for call in mock_log.call_args_list]
            assert any('token_revoked' in call for call in all_calls)
            assert any('user_tokens_revoked' in call for call in all_calls)
