# tests/integration/test_pipeline_integration.py
"""
Integration tests for Phase 4: Test complete pipeline flows with realistic scenarios
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from datetime import datetime, timedelta, timezone
import json
import asyncio
from io import BytesIO


@pytest.mark.asyncio
async def test_s3_download_and_parse_integration():
    """Test S3 download integrates with log parsing"""
    from src.core.s3_handler import S3Handler
    from src.core.log_parser import FirewallLogParser
    
    # Mock S3 client with paginator
    mock_s3_client = Mock()
    mock_paginator = Mock()
    mock_page_iterator = iter([
        {
            'Contents': [
                {
                    'Key': 'logs/firewall-2024-01-01.log',
                    'LastModified': datetime.now(timezone.utc),
                    'Size': 1024,
                    'ETag': '"abc123"'
                }
            ]
        }
    ])
    mock_paginator.paginate.return_value = mock_page_iterator
    mock_s3_client.get_paginator.return_value = mock_paginator
    
    # Mock log content (pipe-delimited format expected by FirewallLogParser)
    # Format: timestamp|src_ip|dst_ip|action|rule_name|proto|src_port|dst_port|bytes
    log_content = b"2024-01-01T10:00:00Z|192.168.1.100|10.0.0.1|ALLOW|rule1|TCP|80|443|1024"
    
    # Mock get_object response
    mock_response = {
        'Body': BytesIO(log_content),
        'ContentEncoding': None,
        'ContentLength': len(log_content),
        'ETag': '"abc123"'
    }
    mock_s3_client.get_object.return_value = mock_response
    
    # Initialize components with correct signatures
    with patch('src.core.s3_handler.boto3') as mock_boto3:
        mock_boto3.client.return_value = mock_s3_client
        
        s3_handler = S3Handler(
            aws_access_key='test_key',
            aws_secret_key='test_secret',
            region='us-east-1'
        )
        
        parser = FirewallLogParser()
        
        # Flow: S3 download → parse
        objects = s3_handler.list_objects('test-bucket')  # bucket passed as argument
        assert len(objects) == 1
        
        content = s3_handler.download_object('test-bucket', objects[0]['Key'])
        # download_object returns bytes
        assert content == log_content
        
        # Parse the downloaded content (parser expects pipe-delimited format)
        # Format: timestamp|src_ip|dst_ip|action|rule_name|proto|src_port|dst_port|bytes
        proper_log = b"2024-01-01T10:00:00Z|192.168.1.100|10.0.0.1|ALLOW|rule1|TCP|80|443|1024"
        parsed_log = parser.parse(proper_log)
        assert parsed_log is not None
        assert 'SourceIP' in parsed_log


@pytest.mark.asyncio
async def test_credential_and_encryption_integration():
    """Test credential retrieval integrates with encryption"""
    from src.security.credential_manager import CredentialManager
    from src.security.encryption import EncryptionManager
    
    # Mock Azure Key Vault client with async support
    async def mock_get_secret(name):
        mock_secret = Mock()
        mock_secret.value = 'test-password-123'
        return mock_secret
    
    with patch('src.security.credential_manager.SecretClient') as mock_secret_client_class:
        mock_secret_client = Mock()
        mock_secret_client.get_secret = mock_get_secret
        mock_secret_client_class.return_value = mock_secret_client
        
        # 1. Get credential from Key Vault
        cred_manager = CredentialManager({
            'vault_url': 'https://test.vault.azure.net',
            'use_key_vault': True,
            'cache_ttl': 300
        })
        
        credential = await cred_manager.get_credential('database_password')
        assert credential == 'test-password-123'
        
    # 2. Encrypt the credential
    import tempfile
    with tempfile.TemporaryDirectory() as temp_key_dir:
        encryption_manager = EncryptionManager(temp_key_dir)
        
        encrypted = encryption_manager.encrypt(credential.encode())
        assert encrypted != credential.encode()
        
        decrypted = encryption_manager.decrypt(encrypted)
        assert decrypted == credential.encode()


@pytest.mark.asyncio
async def test_failed_batch_storage_fallback():
    """Test failed batch storage with local fallback"""
    from src.core.sentinel_router import SentinelRouter
    from azure.core.exceptions import HttpResponseError
    import tempfile
    import os
    
    # Mock Sentinel client that fails with Azure error
    with patch('src.core.sentinel_router.LogsIngestionClient') as mock_client_class:
        # Use regular Mock (not AsyncMock) since upload is called via run_in_executor (synchronously)
        mock_client = Mock()
        # Raise Azure error to trigger failed batch handling
        azure_error = HttpResponseError("Ingestion failed")
        mock_client.upload.side_effect = azure_error
        mock_client_class.return_value = mock_client
        
        # Use local fallback (no Azure Blob)
        with tempfile.TemporaryDirectory() as temp_dir:
            # Mock Azure credential
            with patch('azure.identity.DefaultAzureCredential'):
                router = SentinelRouter(
                    dcr_endpoint='https://test.ingest.monitor.azure.com',
                    rule_id='dcr-test',
                    stream_name='test-stream'
                )
                
                # Set local failed logs path
                router.failed_logs_path = temp_dir
            
                # Try to route logs (will fail and store locally)
                # Use firewall-compatible log format with required fields: TimeGenerated, SourceIP, DestinationIP, Action
                test_logs = [
                    {
                        'TimeGenerated': '2024-01-01T10:00:00Z',
                        'SourceIP': '192.168.1.100',
                        'DestinationIP': '10.0.0.1',
                        'Action': 'ALLOW',
                        'Protocol': 'TCP'
                    },
                    {
                        'TimeGenerated': '2024-01-01T10:00:01Z',
                        'SourceIP': '192.168.1.101',
                        'DestinationIP': '10.0.0.2',
                        'Action': 'DENY',
                        'Protocol': 'UDP'
                    }
                ]
                
                try:
                    # route_logs signature: (log_type, logs, data_classification)
                    await router.route_logs('firewall', test_logs)
                except Exception:
                    pass  # Expected to fail
                
                # Check if failed batch was stored locally
                files = os.listdir(temp_dir)
                assert len(files) > 0, "Failed batch should be stored locally"
                
                # Verify file contains JSON data with correct structure
                with open(os.path.join(temp_dir, files[0]), 'r') as f:
                    stored_data = json.load(f)
                    assert 'data' in stored_data  # Failed batch stores logs in 'data' key
                    assert 'batch_id' in stored_data
                    assert 'error' in stored_data
                    assert len(stored_data['data']) == 2  # Both logs stored


@pytest.mark.asyncio
async def test_core_manager_async_initialization():
    """Test CoreManager async factory initialization"""
    from src.core import CoreManager
    
    # Create mock credential manager that returns dict for aws-credentials
    async def mock_get_credential(name):
        if name == 'aws-credentials':
            return {
                'access_key': 'test-access-key',
                'secret_key': 'test-secret-key'
            }
        return 'test-credential-value'
    
    mock_cred_manager = Mock()
    mock_cred_manager.get_credential = mock_get_credential
    
    # Mock all dependencies
    with patch('src.core.s3_handler.boto3'):
        with patch('src.core.sentinel_router.LogsIngestionClient'):
            with patch('azure.identity.DefaultAzureCredential'):
                
                # Create mock security and monitoring managers
                mock_security = Mock()
                mock_security.credential_manager = mock_cred_manager
                mock_monitoring = Mock()
                
                # Initialize via factory method
                config = {
                    'aws': {
                        'access_key_ref': 'keyvault:aws-access-key',
                        'secret_key_ref': 'keyvault:aws-secret-key',
                        'region': 'us-east-1'
                    },
                    'parser': {},
                    'sentinel': {
                        'dcr_endpoint': 'https://test',
                        'rule_id': 'test',
                        'stream_name': 'test'
                    }
                }
                
                manager = await CoreManager.create(
                    config=config,
                    security_manager=mock_security,
                    monitoring_manager=mock_monitoring
                )
                
                # Verify initialization
                assert manager._initialized is True
                assert hasattr(manager, 's3_handler')
    """Test configuration validation with real validator"""
    from src.security.config_validator import ConfigurationValidator
    
    validator = ConfigurationValidator()
    
    # Test valid config
    valid_config = {
        'aws': {
            'bucket': 'test-bucket',
            'region': 'us-east-1',
            'access_key_ref': 'keyvault:aws-access-key'  # Key Vault reference
        },
        'sentinel': {
            'endpoint': 'https://test.ingest.monitor.azure.com',
            'dcr_id': 'dcr-test',
            'stream_name': 'test-stream'
        },
        'monitoring': {
            'metrics': {
                'endpoint': 'https://test'
            }
        },
        'permissions': {
            'roles': [
                {
                    'name': 'admin',
                    'permissions': ['read', 'write', 'delete']
                }
            ]
        }
    }
    
    validation_result = validator.validate_configuration(valid_config)
    assert validation_result['valid'] is True
    if 'violations' in validation_result:
        assert len(validation_result['violations']) == 0


@pytest.mark.asyncio
async def test_parser_with_different_formats():
    """Test parser handles different log formats correctly"""
    from src.core.log_parser import FirewallLogParser, JsonLogParser
    
    # Test firewall logs (expects bytes in pipe-delimited format)
    # Format: timestamp|src_ip|dst_ip|action|rule_name|proto|src_port|dst_port|bytes
    firewall_parser = FirewallLogParser()
    firewall_log = b"2024-01-01T10:00:00Z|192.168.1.100|10.0.0.1|ALLOW|rule1|TCP|80|443|1024"
    
    parsed_firewall = firewall_parser.parse(firewall_log)
    assert parsed_firewall is not None
    assert 'SourceIP' in parsed_firewall
    
    # Test JSON logs (expects bytes)
    json_parser = JsonLogParser()
    json_log = b'{"timestamp": "2024-01-01T10:00:00Z", "level": "ERROR", "message": "Test error"}'
    
    parsed_json = json_parser.parse(json_log)
    assert parsed_json is not None
    assert 'level' in parsed_json


@pytest.mark.asyncio
async def test_component_metrics_integration():
    """Test component metrics collection across operations"""
    from src.monitoring.component_metrics import ComponentMetrics
    
    # Create metrics for different components
    s3_metrics = ComponentMetrics('s3_handler')
    parser_metrics = ComponentMetrics('log_parser')
    sentinel_metrics = ComponentMetrics('sentinel_router')
    
    # Simulate pipeline execution metrics
    # S3 download phase
    s3_metrics.record_processing(count=100, duration=2.5, batch_size=100)
    
    # Parsing phase (1 error out of 100)
    parser_metrics.record_processing(count=100, duration=1.8, batch_size=100)
    parser_metrics.record_error('ParseError')
    
    # Sentinel ingestion phase
    sentinel_metrics.record_processing(count=99, duration=3.2, batch_size=50)
    
    # Verify metrics are tracked correctly
    s3_stats = s3_metrics.get_metrics()
    assert s3_stats['processed_count'] == 100
    assert s3_stats['error_count'] == 0
    assert s3_stats['avg_processing_time'] == pytest.approx(0.025)
    
    parser_stats = parser_metrics.get_metrics()
    assert parser_stats['processed_count'] == 100
    assert parser_stats['error_count'] == 1
    assert parser_stats['error_rate'] == pytest.approx(0.01)
    
    sentinel_stats = sentinel_metrics.get_metrics()
    assert sentinel_stats['processed_count'] == 99
    assert sentinel_stats['avg_batch_size'] == 50


@pytest.mark.asyncio
async def test_access_control_context_integration():
    """Test access control with context management"""
    from src.security.access_control import AccessControl, Role, User
    
    # Create access control (takes jwt_secret string, not dict)
    access_control = AccessControl(jwt_secret='test-secret-key-12345')
    
    # Add role and user
    role = Role(name='user_role', permissions=['read', 'write'])
    access_control.add_role(role)
    
    user = User(username='user123', roles=['user_role'], active=True)
    access_control.add_user(user)
    
    # Set user context using instance method
    access_control.set_current_user('user123')
    
    try:
        # Generate token (method takes username string, not dict)
        token = access_control.generate_token('user123')
        assert token is not None
        
        # Verify token (returns payload with username field)
        decoded = access_control.validate_token(token)
        assert decoded['username'] == 'user123'
        
        # Test permission check
        has_read = access_control.has_permission('user123', 'read')
        assert has_read is True  # Should have read permission from role
        
    finally:
        # Clean up context
        access_control.clear_current_user()


@pytest.mark.asyncio
async def test_encryption_key_rotation_integration():
    """Test encryption key rotation workflow"""
    from src.security.encryption import EncryptionManager
    from src.security.rotation_manager import RotationManager
    from src.security.credential_manager import CredentialManager
    import tempfile
    import os
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create encryption manager with key store path
        encryption_manager = EncryptionManager(temp_dir)
        
        # Create some encrypted files
        test_file = os.path.join(temp_dir, 'test.enc')
        data = b'sensitive data'
        encrypted = encryption_manager.encrypt(data)
        with open(test_file, 'wb') as f:
            f.write(encrypted)
        
        # Test encryption/decryption works
        decrypted = encryption_manager.decrypt(encrypted)
        assert decrypted == data
        
        # Create credential manager with mock
        async def mock_get_secret(name):
            mock_secret = Mock()
            mock_secret.value = 'test-credential'
            return mock_secret
        
        with patch('src.security.credential_manager.SecretClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_secret = mock_get_secret
            mock_client_class.return_value = mock_client
            
            cred_manager = CredentialManager({
                'vault_url': 'https://test.vault.azure.net',
                'use_key_vault': True
            })
            
            # Create rotation manager
            rotation_manager = RotationManager(
                credential_manager=cred_manager,
                rotation_config={
                    'test_credential': {
                        'max_age_days': 90,
                        'min_rotation_interval_hours': 24
                    }
                }
            )
            
            # Test that rotation manager was created successfully
            assert rotation_manager.credential_manager is not None
            assert rotation_manager.rotation_config is not None

