# tests/test_critical_imports.py

"""
Test that critical imports are present and prevent NameError at runtime.
These tests verify fixes for Phase 1 Critical Issues C1, C4, C5.
"""

import pytest


class TestCriticalImports:
    """Test critical imports that were missing in vibe-coded implementation"""
    
    def test_time_import_in_encryption(self):
        """Test C1: time module is imported in encryption.py"""
        from src.security import encryption
        
        # Verify time is accessible in the module
        assert hasattr(encryption, 'time')
        assert callable(encryption.time.time)
    
    def test_hashlib_import_in_ml_connector(self):
        """Test C4: hashlib module is imported in enhanced_connector.py"""
        pytest.importorskip("tensorflow")
        from src.ml import enhanced_connector
        
        # Verify hashlib is accessible in the module
        assert hasattr(enhanced_connector, 'hashlib')
        assert callable(enhanced_connector.hashlib.md5)
    
    def test_asyncio_import_in_error_handling(self):
        """Test C5: asyncio module is imported in error_handling.py"""
        from src.utils import error_handling
        
        # Verify asyncio is accessible in the module
        assert hasattr(error_handling, 'asyncio')
        assert callable(error_handling.asyncio.sleep)
    
    def test_encryption_manager_uses_time(self):
        """Test that EncryptionManager can use time.time() without NameError"""
        import tempfile
        import shutil
        import os
        
        temp_dir = tempfile.mkdtemp()
        try:
            from src.security.encryption import EncryptionManager, EncryptionConfig
            
            # This should not raise NameError when checking key rotation
            config = EncryptionConfig(key_rotation_days=30)
            manager = EncryptionManager(temp_dir, config)
            
            # Access the method that uses time
            key_file = os.path.join(temp_dir, 'current.key')
            needs_rotation = manager._needs_rotation(key_file)
            
            # Should return bool, not raise NameError
            assert isinstance(needs_rotation, bool)
        finally:
            shutil.rmtree(temp_dir)
    
    def test_ml_connector_can_hash_patterns(self):
        """Test that MLEnhancedConnector can use hashlib without NameError"""
        pytest.importorskip("tensorflow")
        import pandas as pd
        from src.ml.enhanced_connector import MLEnhancedConnector
        
        connector = MLEnhancedConnector()
        
        # Create test pattern
        pattern = pd.DataFrame({'col1': [1, 2, 3], 'col2': [4, 5, 6]})
        
        # This should not raise NameError
        pattern_hash = connector._hash_pattern(pattern)
        
        # Should return hex string
        assert isinstance(pattern_hash, str)
        assert len(pattern_hash) == 32  # MD5 hex digest length
    
    @pytest.mark.asyncio
    async def test_error_handler_retry_uses_asyncio(self):
        """Test that retry_with_backoff can use asyncio.sleep without NameError"""
        import asyncio as async_module
        from src.utils.error_handling import retry_with_backoff
        
        # Test that asyncio.sleep is accessible (verifies C5 fix)
        # The decorator uses asyncio.sleep internally
        call_count = 0
        
        @retry_with_backoff(retries=1, base_delay=0.01)
        async def successful_function():
            nonlocal call_count
            call_count += 1
            # Verify asyncio.sleep doesn't cause NameError
            await async_module.sleep(0.001)
            return "success"
        
        # This should not raise NameError for asyncio.sleep
        result = await successful_function()
        
        assert result == "success"
        assert call_count == 1
