# tests/unit/core/test_pii_redaction.py

"""
Phase 5 (Security - B2-011/P2-SEC-03): PII Redaction Tests

Tests for PII redaction in failed batch storage.
Validates protection of sensitive data (email, phone, SSN, etc.) before persistence.
"""

import pytest
import json
from datetime import datetime, timezone

from src.core.sentinel_router import SentinelRouter, TableConfig


class TestPIIRedaction:
    """Test PII redaction in failed batch storage"""
    
    @pytest.fixture
    def sentinel_router(self):
        """Create SentinelRouter instance for testing"""
        router = SentinelRouter(
            dcr_endpoint="https://test.azure.com",
            rule_id="test-rule",
            stream_name="test-stream",
            logs_client=None,  # Mock client
            credential=None
        )
        return router
    
    def test_redact_email_addresses(self, sentinel_router):
        """Test email address redaction"""
        record = {
            'user': 'john.doe@example.com',
            'message': 'Contact support at help@company.org'
        }
        
        redacted = sentinel_router._redact_pii_from_record(record)
        
        assert '[REDACTED:EMAIL]' in redacted['user']
        assert '[REDACTED:EMAIL]' in redacted['message']
        assert 'john.doe@example.com' not in redacted['user']
        assert 'help@company.org' not in redacted['message']
    
    def test_redact_phone_numbers(self, sentinel_router):
        """Test phone number redaction"""
        record = {
            'contact': '555-123-4567',
            'mobile': '(555) 987-6543',
            'phone': '5551234567'
        }
        
        redacted = sentinel_router._redact_pii_from_record(record)
        
        assert '[REDACTED:PHONE]' in redacted['contact']
        assert '555-123-4567' not in redacted['contact']
    
    def test_redact_ssn(self, sentinel_router):
        """Test SSN redaction"""
        record = {
            'ssn': '123-45-6789',
            'notes': 'SSN: 987-65-4321'
        }
        
        redacted = sentinel_router._redact_pii_from_record(record)
        
        assert '[REDACTED:SSN]' in redacted['ssn']
        assert '[REDACTED:SSN]' in redacted['notes']
        assert '123-45-6789' not in redacted['ssn']
    
    def test_redact_credit_card_numbers(self, sentinel_router):
        """Test credit card number redaction"""
        record = {
            'payment': '4532-1234-5678-9010',
            'card': '4532123456789010'
        }
        
        redacted = sentinel_router._redact_pii_from_record(record)
        
        assert '[REDACTED:CREDIT_CARD]' in redacted['payment']
        assert '4532-1234-5678-9010' not in redacted['payment']
    
    def test_redact_ipv4_addresses(self, sentinel_router):
        """Test IPv4 address redaction"""
        record = {
            'source_ip': '192.168.1.100',
            'dest_ip': '10.0.0.50'
        }
        
        redacted = sentinel_router._redact_pii_from_record(record)
        
        assert '[REDACTED:IPV4]' in redacted['source_ip']
        assert '[REDACTED:IPV4]' in redacted['dest_ip']
        assert '192.168.1.100' not in redacted['source_ip']
    
    def test_redact_api_keys(self, sentinel_router):
        """Test API key redaction (long alphanumeric strings)"""
        # Use placeholder test keys — never commit real secrets
        record = {
            'api_key': 'sk_live_REDACTED',
            'token': 'ghp_REDACTED'
        }
        
        redacted = sentinel_router._redact_pii_from_record(record)
        
        # API keys should be redacted by pattern OR field name
        assert 'REDACTED' in redacted['api_key']
        assert 'REDACTED' in redacted['token']
    
    def test_redact_by_field_name_password(self, sentinel_router):
        """Test field name-based redaction for passwords"""
        record = {
            'password': 'secret123',
            'user_password': 'mypass',
            'pwd': 'hidden'
        }
        
        redacted = sentinel_router._redact_pii_from_record(record)
        
        assert redacted['password'] == '[REDACTED:PASSWORD]'
        assert redacted['user_password'] == '[REDACTED:USER_PASSWORD]'
        assert redacted['pwd'] == '[REDACTED:PWD]'
        assert 'secret123' not in str(redacted)
    
    def test_redact_by_field_name_token(self, sentinel_router):
        """Test field name-based redaction for tokens"""
        record = {
            'auth_token': 'bearer_xyz',
            'session_token': 'session123',
            'api_token': 'key456'
        }
        
        redacted = sentinel_router._redact_pii_from_record(record)
        
        assert 'REDACTED' in redacted['auth_token']
        assert 'REDACTED' in redacted['session_token']
        assert 'REDACTED' in redacted['api_token']
    
    def test_redact_nested_dictionaries(self, sentinel_router):
        """Test PII redaction in nested structures"""
        record = {
            'user': {
                'email': 'test@example.com',
                'phone': '555-1234',
                'address': {
                    'street': '123 Main St',
                    'zipcode': '12345'
                }
            }
        }
        
        redacted = sentinel_router._redact_pii_from_record(record)
        
        # Email should be redacted
        assert '[REDACTED:EMAIL]' in redacted['user']['email']
        # Address fields should be redacted by field name
        assert 'REDACTED' in redacted['user']['address']['street']
        assert 'REDACTED' in redacted['user']['address']['zipcode']
    
    def test_redact_lists(self, sentinel_router):
        """Test PII redaction in list values"""
        record = {
            'emails': ['user1@test.com', 'user2@test.com'],
            'phones': ['555-1111', '555-2222']
        }
        
        redacted = sentinel_router._redact_pii_from_record(record)
        
        assert all('[REDACTED:EMAIL]' in email for email in redacted['emails'])
        assert 'user1@test.com' not in str(redacted)
    
    def test_preserve_non_pii_data(self, sentinel_router):
        """Test that non-PII data is preserved"""
        record = {
            'timestamp': '2024-01-03T10:00:00Z',
            'log_level': 'INFO',
            'message': 'User logged in successfully',
            'count': 42
        }
        
        redacted = sentinel_router._redact_pii_from_record(record)
        
        assert redacted['timestamp'] == '2024-01-03T10:00:00Z'
        assert redacted['log_level'] == 'INFO'
        assert redacted['message'] == 'User logged in successfully'
        assert redacted['count'] == 42
    
    def test_redact_batch_info(self, sentinel_router):
        """Test redaction of entire failed batch info"""
        batch_info = {
            'batch_id': 'test123',
            'timestamp': '2024-01-03T10:00:00+00:00',
            'error': 'Azure timeout',
            'data': [
                {'user': 'admin@company.com', 'action': 'login'},
                {'user': 'test@example.org', 'action': 'logout'}
            ]
        }
        
        redacted = sentinel_router._redact_pii_from_batch(batch_info)
        
        # Metadata should be preserved
        assert redacted['batch_id'] == 'test123'
        assert redacted['error'] == 'Azure timeout'
        
        # Emails in data should be redacted
        assert '[REDACTED:EMAIL]' in redacted['data'][0]['user']
        assert '[REDACTED:EMAIL]' in redacted['data'][1]['user']
        assert 'admin@company.com' not in str(redacted)
        assert 'test@example.org' not in str(redacted)
    
    def test_mixed_pii_in_single_field(self, sentinel_router):
        """Test multiple PII types in one field"""
        record = {
            'notes': 'Contact John at john@example.com or 555-123-4567'
        }
        
        redacted = sentinel_router._redact_pii_from_record(record)
        
        # Both email and phone should be redacted
        assert '[REDACTED:EMAIL]' in redacted['notes']
        assert '[REDACTED:PHONE]' in redacted['notes']
        assert 'john@example.com' not in redacted['notes']
        assert '555-123-4567' not in redacted['notes']
    
    def test_is_pii_field_name(self, sentinel_router):
        """Test PII field name detection"""
        # Positive cases
        assert sentinel_router._is_pii_field_name('password')
        assert sentinel_router._is_pii_field_name('user_password')
        assert sentinel_router._is_pii_field_name('EMAIL')
        assert sentinel_router._is_pii_field_name('SSN')
        assert sentinel_router._is_pii_field_name('api_key')
        assert sentinel_router._is_pii_field_name('auth_token')
        
        # Negative cases
        assert not sentinel_router._is_pii_field_name('timestamp')
        assert not sentinel_router._is_pii_field_name('log_level')
        assert not sentinel_router._is_pii_field_name('message')
    
    def test_redact_pii_from_string(self, sentinel_router):
        """Test string-level PII redaction"""
        text = "Email admin@test.com, phone 555-1234, SSN 123-45-6789"
        
        redacted = sentinel_router._redact_pii_from_string(text)
        
        assert '[REDACTED:EMAIL]' in redacted
        assert '[REDACTED:PHONE]' in redacted
        assert '[REDACTED:SSN]' in redacted
        assert 'admin@test.com' not in redacted
        assert '123-45-6789' not in redacted
    
    def test_empty_record_redaction(self, sentinel_router):
        """Test redaction of empty record"""
        record = {}
        
        redacted = sentinel_router._redact_pii_from_record(record)
        
        assert redacted == {}
    
    def test_none_values_preserved(self, sentinel_router):
        """Test that None values are preserved"""
        record = {
            'field1': None,
            'field2': 'value',
            'email': None
        }
        
        redacted = sentinel_router._redact_pii_from_record(record)
        
        assert redacted['field1'] is None
        assert redacted['field2'] == 'value'
        # Email field name triggers redaction even if value is None
        assert redacted['email'] == '[REDACTED:EMAIL]'
    
    def test_deep_copy_original_unmodified(self, sentinel_router):
        """Test that original record is not modified during redaction"""
        original = {
            'email': 'test@example.com',
            'password': 'secret123'
        }
        original_copy = original.copy()
        
        redacted = sentinel_router._redact_pii_from_record(original)
        
        # Original should be unchanged
        assert original == original_copy
        # Redacted should have redactions
        assert '[REDACTED' in redacted['email']
        assert '[REDACTED' in redacted['password']
    
    def test_complex_nested_structure(self, sentinel_router):
        """Test redaction in complex nested structure"""
        record = {
            'metadata': {
                'user': {
                    'email': 'admin@company.com',
                    'profile': {
                        'phone': '555-9999',
                        'ssn': '111-22-3333'
                    }
                },
                'contacts': [
                    {'name': 'John', 'email': 'john@test.com'},
                    {'name': 'Jane', 'email': 'jane@test.org'}
                ]
            }
        }
        
        redacted = sentinel_router._redact_pii_from_record(record)
        
        # All emails should be redacted
        assert '[REDACTED:EMAIL]' in redacted['metadata']['user']['email']
        assert '[REDACTED:EMAIL]' in redacted['metadata']['contacts'][0]['email']
        assert '[REDACTED:EMAIL]' in redacted['metadata']['contacts'][1]['email']
        
        # Phone and SSN should be redacted
        assert '[REDACTED:PHONE]' in redacted['metadata']['user']['profile']['phone']
        assert '[REDACTED:SSN]' in redacted['metadata']['user']['profile']['ssn']
        
        # Names should be preserved
        assert redacted['metadata']['contacts'][0]['name'] == 'John'
        assert redacted['metadata']['contacts'][1]['name'] == 'Jane'
    
    def test_case_insensitive_field_matching(self, sentinel_router):
        """Test case-insensitive field name matching"""
        record = {
            'PASSWORD': 'secret',
            'Password': 'hidden',
            'password': 'secure',
            'USER_EMAIL': 'test@example.com',
            'userEmail': 'admin@company.org'
        }
        
        redacted = sentinel_router._redact_pii_from_record(record)
        
        # All password variants should be redacted
        assert 'REDACTED' in redacted['PASSWORD']
        assert 'REDACTED' in redacted['Password']
        assert 'REDACTED' in redacted['password']
        
        # All email variants should be redacted
        assert 'REDACTED' in redacted['USER_EMAIL']
        assert 'REDACTED' in redacted['userEmail']
