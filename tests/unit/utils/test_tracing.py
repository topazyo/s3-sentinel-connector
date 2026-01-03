# tests/unit/utils/test_tracing.py
"""
Unit tests for correlation ID tracing utilities (B2-006/RES-06)

Phase 4 (Observability): Comprehensive testing of correlation ID generation,
propagation, and integration with logging.
"""

import pytest
import asyncio
import logging
from unittest.mock import Mock, patch
import uuid

from src.utils.tracing import (
    get_correlation_id,
    set_correlation_id,
    clear_correlation_id,
    with_correlation_id,
    get_correlation_context
)


class TestCorrelationIDGeneration:
    """Test correlation ID generation and auto-creation"""

    def test_get_correlation_id_generates_uuid(self):
        """Test that get_correlation_id generates a UUID if not set"""
        # Arrange
        clear_correlation_id()  # Ensure clean state
        
        # Act
        cid = get_correlation_id()
        
        # Assert
        assert cid is not None
        assert len(cid) > 0
        # Verify it's a valid UUID format
        uuid.UUID(cid)  # Will raise if not valid UUID

    def test_get_correlation_id_is_idempotent(self):
        """Test that get_correlation_id returns same ID when called multiple times"""
        # Arrange
        clear_correlation_id()
        
        # Act
        cid1 = get_correlation_id()
        cid2 = get_correlation_id()
        cid3 = get_correlation_id()
        
        # Assert
        assert cid1 == cid2 == cid3

    def test_get_correlation_id_after_clear(self):
        """Test that get_correlation_id generates new ID after clear"""
        # Arrange
        cid1 = get_correlation_id()
        
        # Act
        clear_correlation_id()
        cid2 = get_correlation_id()
        
        # Assert
        assert cid1 != cid2


class TestCorrelationIDSetting:
    """Test explicit correlation ID setting"""

    def test_set_correlation_id_stores_value(self):
        """Test that set_correlation_id stores the provided value"""
        # Arrange
        test_id = "550e8400-e29b-41d4-a716-446655440000"
        
        # Act
        set_correlation_id(test_id)
        retrieved = get_correlation_id()
        
        # Assert
        assert retrieved == test_id

    def test_set_correlation_id_overrides_existing(self):
        """Test that set_correlation_id overrides existing ID"""
        # Arrange
        first_id = "111e8400-e29b-41d4-a716-446655440000"
        second_id = "222e8400-e29b-41d4-a716-446655440000"
        
        # Act
        set_correlation_id(first_id)
        assert get_correlation_id() == first_id
        set_correlation_id(second_id)
        retrieved = get_correlation_id()
        
        # Assert
        assert retrieved == second_id
        assert retrieved != first_id

    def test_set_correlation_id_with_custom_format(self):
        """Test that set_correlation_id accepts custom formats"""
        # Arrange
        custom_id = "custom-request-12345"
        
        # Act
        set_correlation_id(custom_id)
        retrieved = get_correlation_id()
        
        # Assert
        assert retrieved == custom_id


class TestCorrelationIDClearing:
    """Test correlation ID clearing"""

    def test_clear_correlation_id_removes_value(self):
        """Test that clear_correlation_id removes the current ID"""
        # Arrange
        set_correlation_id("test-id-123")
        assert get_correlation_id() == "test-id-123"
        
        # Act
        clear_correlation_id()
        new_id = get_correlation_id()
        
        # Assert
        assert new_id != "test-id-123"
        assert new_id != ""  # Should generate new ID

    def test_clear_correlation_id_idempotent(self):
        """Test that clear_correlation_id can be called multiple times"""
        # Arrange
        set_correlation_id("test-id")
        
        # Act & Assert
        clear_correlation_id()
        clear_correlation_id()  # Should not raise
        clear_correlation_id()  # Should not raise


class TestCorrelationIDContext:
    """Test get_correlation_context for structured logging"""

    def test_get_correlation_context_returns_dict(self):
        """Test that get_correlation_context returns a dict"""
        # Act
        context = get_correlation_context()
        
        # Assert
        assert isinstance(context, dict)
        assert 'correlation_id' in context

    def test_get_correlation_context_includes_current_id(self):
        """Test that get_correlation_context includes the current correlation ID"""
        # Arrange
        test_id = "context-test-id"
        set_correlation_id(test_id)
        
        # Act
        context = get_correlation_context()
        
        # Assert
        assert context['correlation_id'] == test_id

    def test_get_correlation_context_generates_if_not_set(self):
        """Test that get_correlation_context generates ID if not set"""
        # Arrange
        clear_correlation_id()
        
        # Act
        context = get_correlation_context()
        
        # Assert
        assert 'correlation_id' in context
        assert len(context['correlation_id']) > 0
        # Should be valid UUID
        uuid.UUID(context['correlation_id'])


class TestCorrelationIDWithLogging:
    """Test with_correlation_id logging wrapper"""

    @patch('logging.Logger.info')
    def test_with_correlation_id_info(self, mock_info):
        """Test that with_correlation_id logs info with correlation ID"""
        # Arrange
        logger = logging.getLogger('test')
        test_id = "log-test-id"
        set_correlation_id(test_id)
        
        # Act
        with_correlation_id(logger, 'info', "Test message")
        
        # Assert
        assert mock_info.called
        call_args, call_kwargs = mock_info.call_args
        assert "Test message" in call_args
        assert 'extra' in call_kwargs
        assert call_kwargs['extra']['correlation_id'] == test_id

    @patch('logging.Logger.error')
    def test_with_correlation_id_error(self, mock_error):
        """Test that with_correlation_id logs error with correlation ID"""
        # Arrange
        logger = logging.getLogger('test')
        test_id = "error-log-id"
        set_correlation_id(test_id)
        
        # Act
        with_correlation_id(logger, 'error', "Error occurred")
        
        # Assert
        assert mock_error.called
        call_args, call_kwargs = mock_error.call_args
        assert "Error occurred" in call_args
        assert call_kwargs['extra']['correlation_id'] == test_id

    @patch('logging.Logger.warning')
    def test_with_correlation_id_with_additional_args(self, mock_warning):
        """Test that with_correlation_id merges additional args with correlation ID"""
        # Arrange
        logger = logging.getLogger('test')
        test_id = "warning-log-id"
        set_correlation_id(test_id)
        
        # Act
        with_correlation_id(
            logger, 'warning', "Warning message", 
            extra={'batch_size': 100, 'status': 'degraded'}
        )
        
        # Assert
        assert mock_warning.called
        call_args, call_kwargs = mock_warning.call_args
        assert call_kwargs['extra']['correlation_id'] == test_id
        assert call_kwargs['extra']['batch_size'] == 100
        assert call_kwargs['extra']['status'] == 'degraded'


class TestCorrelationIDAsyncSafety:
    """Test that correlation IDs work correctly with asyncio"""

    @pytest.mark.asyncio
    async def test_correlation_id_isolated_across_async_tasks(self):
        """Test that correlation IDs are isolated between async tasks"""
        # Track which task got which ID
        task_ids = {}
        
        async def task_with_correlation(task_name: str):
            # Each task sets its own correlation ID
            cid = f"{task_name}-id"
            set_correlation_id(cid)
            await asyncio.sleep(0.01)  # Simulate async work
            retrieved = get_correlation_id()
            task_ids[task_name] = retrieved
        
        # Act - Run multiple tasks concurrently
        await asyncio.gather(
            task_with_correlation("task1"),
            task_with_correlation("task2"),
            task_with_correlation("task3")
        )
        
        # Assert - Each task should have its own correlation ID
        assert task_ids['task1'] == 'task1-id'
        assert task_ids['task2'] == 'task2-id'
        assert task_ids['task3'] == 'task3-id'

    @pytest.mark.asyncio
    async def test_correlation_id_preserved_across_awaits(self):
        """Test that correlation ID is preserved across await boundaries"""
        # Arrange
        test_id = "async-preserved-id"
        set_correlation_id(test_id)
        
        # Act
        id_before = get_correlation_id()
        await asyncio.sleep(0.01)  # Cross await boundary
        id_after = get_correlation_id()
        
        # Assert
        assert id_before == test_id
        assert id_after == test_id


class TestCorrelationIDIntegration:
    """Test integration scenarios"""

    def test_correlation_id_in_structured_log(self):
        """Test correlation ID included in structured log output"""
        # Arrange
        logger = logging.getLogger('integration_test')
        test_id = "integration-log-id"
        set_correlation_id(test_id)
        
        # Act
        context = get_correlation_context()
        
        # Simulate structured logging
        log_entry = {
            'message': 'Processing started',
            'batch_size': 50,
            **context
        }
        
        # Assert
        assert log_entry['correlation_id'] == test_id
        assert log_entry['message'] == 'Processing started'
        assert log_entry['batch_size'] == 50

    def test_correlation_id_pipeline_flow(self):
        """Test correlation ID propagation through pipeline stages"""
        # Arrange
        clear_correlation_id()
        
        # Stage 1: S3 Ingestion
        s3_cid = get_correlation_id()  # Auto-generated
        s3_context = get_correlation_context()
        
        # Stage 2: Parsing (same context)
        parser_cid = get_correlation_id()
        parser_context = get_correlation_context()
        
        # Stage 3: Sentinel Routing (same context)
        sentinel_cid = get_correlation_id()
        sentinel_context = get_correlation_context()
        
        # Assert - All stages should have same correlation ID
        assert s3_cid == parser_cid == sentinel_cid
        assert s3_context == parser_context == sentinel_context


class TestCorrelationIDEdgeCases:
    """Test edge cases and error handling"""

    def test_get_correlation_id_thread_safe(self):
        """Test that get_correlation_id is thread-safe"""
        # This test validates contextvars behavior (async-safe by design)
        # Multiple calls should return consistent results
        ids = [get_correlation_id() for _ in range(100)]
        
        # All calls should return the same ID
        assert len(set(ids)) == 1

    def test_set_correlation_id_with_empty_string(self):
        """Test that set_correlation_id handles empty string"""
        # Arrange & Act
        set_correlation_id("")
        cid = get_correlation_id()
        
        # Assert - Should generate new ID since empty string is treated as "not set"
        assert cid != ""
        uuid.UUID(cid)  # Should be valid UUID

    def test_correlation_context_reusable(self):
        """Test that correlation context dict can be reused"""
        # Arrange
        test_id = "reusable-id"
        set_correlation_id(test_id)
        context = get_correlation_context()
        
        # Act - Use context multiple times
        log1 = {'msg': 'Step 1', **context}
        log2 = {'msg': 'Step 2', **context}
        log3 = {'msg': 'Step 3', **context}
        
        # Assert
        assert log1['correlation_id'] == test_id
        assert log2['correlation_id'] == test_id
        assert log3['correlation_id'] == test_id
