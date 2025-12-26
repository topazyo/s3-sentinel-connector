# tests/test_phase3_fixes.py

"""
Tests for Phase 3 Quality Issues Resolution
Tests H1, H2, H3, H5, M3, M4 fixes
"""

import pytest
import asyncio
import os
import tempfile
import shutil
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from typing import Dict, Any


class TestCoreManagerAsyncFixes:
    """Test H1 & H2: Async/Sync mismatch fixes in CoreManager"""
    
    @pytest.mark.asyncio
    async def test_factory_method_initialization(self):
        """Test CoreManager.create() factory method works"""
        from src.core import CoreManager
        
        # Mock dependencies
        config = {
            'aws': {'region': 'us-east-1'},
            'sentinel': {
                'dcr_endpoint': 'https://test.endpoint',
                'rule_id': 'test-rule',
                'stream_name': 'test-stream'
            }
        }
        
        security_manager = Mock()
        security_manager.credential_manager.get_credential = AsyncMock(
            return_value={
                'access_key': 'test-key',
                'secret_key': 'test-secret'
            }
        )
        
        monitoring_manager = Mock()
        
        # Create via factory method
        core_manager = await CoreManager.create(
            config,
            security_manager,
            monitoring_manager
        )
        
        # Verify initialization
        assert core_manager._initialized
        assert core_manager.s3_handler is not None
        assert core_manager.sentinel_router is not None
        assert 'firewall' in core_manager.parsers
        assert 'json' in core_manager.parsers
    
    @pytest.mark.asyncio
    async def test_manual_initialization(self):
        """Test CoreManager manual initialization pattern"""
        from src.core import CoreManager
        
        config = {
            'aws': {'region': 'us-east-1'},
            'sentinel': {
                'dcr_endpoint': 'https://test.endpoint',
                'rule_id': 'test-rule',
                'stream_name': 'test-stream'
            }
        }
        
        security_manager = Mock()
        security_manager.credential_manager.get_credential = AsyncMock(
            return_value={
                'access_key': 'test-key',
                'secret_key': 'test-secret'
            }
        )
        
        monitoring_manager = Mock()
        
        # Create without initialization
        core_manager = CoreManager(config, security_manager, monitoring_manager)
        assert not core_manager._initialized
        
        # Initialize manually
        await core_manager.initialize()
        assert core_manager._initialized
    
    @pytest.mark.asyncio
    async def test_process_logs_requires_initialization(self):
        """Test process_logs raises error if not initialized"""
        from src.core import CoreManager
        
        config = {
            'aws': {'region': 'us-east-1'},
            'sentinel': {
                'dcr_endpoint': 'https://test.endpoint',
                'rule_id': 'test-rule',
                'stream_name': 'test-stream'
            }
        }
        
        security_manager = Mock()
        monitoring_manager = Mock()
        
        core_manager = CoreManager(config, security_manager, monitoring_manager)
        
        # Should raise RuntimeError
        with pytest.raises(RuntimeError) as exc_info:
            await core_manager.process_logs('bucket', 'prefix', 'json')
        
        assert "not initialized" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_uses_async_s3_methods(self):
        """Test that process_logs uses async S3 methods"""
        from src.core import CoreManager
        
        config = {
            'aws': {'region': 'us-east-1'},
            'sentinel': {
                'dcr_endpoint': 'https://test.endpoint',
                'rule_id': 'test-rule',
                'stream_name': 'test-stream'
            }
        }
        
        security_manager = Mock()
        security_manager.credential_manager.get_credential = AsyncMock(
            return_value={
                'access_key': 'test-key',
                'secret_key': 'test-secret'
            }
        )
        
        monitoring_manager = Mock()
        monitoring_manager.record_metric = AsyncMock()
        
        core_manager = await CoreManager.create(
            config,
            security_manager,
            monitoring_manager
        )
        
        # Mock S3 handler methods
        core_manager.s3_handler.list_objects_async = AsyncMock(return_value=[])
        core_manager.s3_handler.process_files_batch_async = AsyncMock(
            return_value={'successful': [], 'failed': []}
        )
        
        # Process logs
        await core_manager.process_logs('test-bucket', 'prefix', 'json')
        
        # Verify async methods were called
        core_manager.s3_handler.list_objects_async.assert_called_once()
        core_manager.s3_handler.process_files_batch_async.assert_called_once()


class TestSentinelRouterFailedBatchStorage:
    """Test H3: _store_failed_batch implementation"""
    
    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for local storage"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    @pytest.mark.asyncio
    async def test_store_failed_batch_local_fallback(self, temp_dir):
        """Test failed batch storage to local file system"""
        from src.core.sentinel_router import SentinelRouter
        
        router = SentinelRouter(
            dcr_endpoint='https://test.endpoint',
            rule_id='test-rule',
            stream_name='test-stream',
            logs_client=Mock()  # Mock to avoid Azure client init
        )
        
        # Set local storage path via attribute (not environment)
        router.failed_logs_path = temp_dir
        
        failed_batch_info = {
            'batch_id': 'test-batch-123',
            'timestamp': '2025-12-26T12:00:00',
            'error': 'Test error',
            'retry_count': 0,
            'data': [{'log': 'test'}]
        }
        
        # Store failed batch
        await router._store_failed_batch(failed_batch_info)
        
        # Verify file was created
        files = os.listdir(temp_dir)
        assert len(files) == 1
        assert 'test-batch-123' in files[0]
        
        # Verify content
        import json
        with open(os.path.join(temp_dir, files[0]), 'r') as f:
            stored_data = json.load(f)
        
        assert stored_data['batch_id'] == 'test-batch-123'
        assert stored_data['error'] == 'Test error'
    
    @pytest.mark.asyncio
    async def test_store_multiple_failed_batches(self, temp_dir):
        """Test storing multiple failed batches"""
        from src.core.sentinel_router import SentinelRouter
        
        router = SentinelRouter(
            dcr_endpoint='https://test.endpoint',
            rule_id='test-rule',
            stream_name='test-stream',
            logs_client=Mock()
        )
        
        # Set local storage path via attribute (not environment)
        router.failed_logs_path = temp_dir
        
        # Store multiple batches
        for i in range(3):
            await router._store_failed_batch({
                'batch_id': f'batch-{i}',
                'timestamp': f'2025-12-26T12:00:0{i}',
                'error': f'Error {i}',
                'retry_count': 0,
                'data': [{'log': f'test {i}'}]
            })
        
        # Verify all files created
        files = os.listdir(temp_dir)
        assert len(files) == 3


class TestConfigValidatorPermissions:
    """Test H5: _validate_permissions implementation"""
    
    def test_validate_permissions_with_roles(self):
        """Test permission validation with role configuration"""
        from src.security.config_validator import ConfigurationValidator
        
        validator = ConfigurationValidator()
        
        config = {
            'roles': {
                'admin': {
                    'permissions': ['read', 'write', 'delete', 'admin']
                },
                'viewer': {
                    'permissions': ['read']
                }
            }
        }
        
        result = validator._validate_permissions(config)
        
        assert result['valid']
        assert len(result['violations']) == 0
    
    def test_validate_permissions_missing_field(self):
        """Test validation catches missing permissions field"""
        from src.security.config_validator import ConfigurationValidator
        
        validator = ConfigurationValidator()
        
        config = {
            'roles': {
                'admin': {
                    'description': 'Admin role'
                    # Missing 'permissions' field
                }
            }
        }
        
        result = validator._validate_permissions(config)
        
        assert not result['valid']
        assert any('missing' in v.lower() for v in result['violations'])
    
    def test_validate_permissions_wildcard_warning(self):
        """Test validation warns about wildcard permissions"""
        from src.security.config_validator import ConfigurationValidator
        
        validator = ConfigurationValidator()
        
        config = {
            'roles': {
                'superadmin': {
                    'permissions': ['*']
                }
            }
        }
        
        result = validator._validate_permissions(config)
        
        assert result['valid']
        assert any('wildcard' in w.lower() for w in result['warnings'])
    
    def test_validate_permission_definitions(self):
        """Test validation of permission definitions"""
        from src.security.config_validator import ConfigurationValidator
        
        validator = ConfigurationValidator()
        
        config = {
            'permissions': {
                'read_logs': {
                    'resource': 'logs',
                    'actions': ['read']
                },
                'write_logs': {
                    'resource': 'logs',
                    'actions': ['write']
                }
            }
        }
        
        result = validator._validate_permissions(config)
        
        assert result['valid']
        assert len(result['violations']) == 0
    
    def test_validate_empty_config(self):
        """Test validation with no permissions config"""
        from src.security.config_validator import ConfigurationValidator
        
        validator = ConfigurationValidator()
        
        config = {}
        
        result = validator._validate_permissions(config)
        
        assert result['valid']
        assert any('no permissions' in w.lower() for w in result['warnings'])


class TestUnusedImportsRemoved:
    """Test M3: Unused cryptography imports removed"""
    
    def test_encryption_imports_cleaned(self):
        """Test that unused imports are removed from encryption.py"""
        from src.security import encryption
        
        # Should still have Fernet
        assert hasattr(encryption, 'Fernet')
        
        # Should NOT have unused imports
        assert not hasattr(encryption, 'hashes')
        assert not hasattr(encryption, 'PBKDF2HMAC')
        assert not hasattr(encryption, 'Cipher')
        assert not hasattr(encryption, 'algorithms')
        assert not hasattr(encryption, 'modes')
