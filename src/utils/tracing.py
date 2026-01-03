# src/utils/tracing.py
"""
Correlation ID management for distributed tracing

Phase 4 (B2-006/RES-06): Adds correlation IDs to all logs for cross-component debugging.
Uses contextvars for async-safe request tracing across S3 → Parser → Sentinel pipeline.
"""

import contextvars
import uuid
from typing import Optional
import logging

# Phase 4 (B2-006): Context variable for correlation ID storage
# Uses contextvars for async-safe propagation (works across await boundaries)
_correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    'correlation_id', 
    default=''
)


def get_correlation_id() -> str:
    """
    Get the current correlation ID, generating one if not set
    
    Phase 4 (B2-006/RES-06): Ensures every log has a correlation ID.
    Auto-generates UUID if not explicitly set (idempotent).
    
    Returns:
        Current correlation ID (UUID v4 format)
        
    Example:
        >>> cid = get_correlation_id()
        >>> logging.info("Processing started", extra={'correlation_id': cid})
    """
    cid = _correlation_id.get()
    if not cid:
        cid = str(uuid.uuid4())
        _correlation_id.set(cid)
    return cid


def set_correlation_id(cid: str) -> None:
    """
    Set the correlation ID for the current context
    
    Phase 4 (B2-006/RES-06): Allows explicit correlation ID propagation.
    Use at request entry points (e.g., when receiving HTTP requests, processing S3 files).
    
    Args:
        cid: Correlation ID to set (typically UUID v4)
        
    Example:
        >>> set_correlation_id("550e8400-e29b-41d4-a716-446655440000")
        >>> # All subsequent logs in this async context will use this ID
    """
    _correlation_id.set(cid)


def clear_correlation_id() -> None:
    """
    Clear the correlation ID from the current context
    
    Phase 4 (B2-006): Used for cleanup or isolation between request boundaries.
    Typically not needed due to contextvars automatic isolation.
    
    Example:
        >>> clear_correlation_id()
        >>> # Next get_correlation_id() will generate a new ID
    """
    _correlation_id.set('')


def with_correlation_id(logger: logging.Logger, level: str, message: str, **kwargs) -> None:
    """
    Log with correlation ID automatically included
    
    Phase 4 (B2-006): Convenience wrapper for logging with correlation ID.
    Ensures consistent correlation ID format across all logs.
    
    Args:
        logger: Logger instance to use
        level: Log level ('info', 'warning', 'error', 'debug')
        message: Log message
        **kwargs: Additional log arguments (will be merged with correlation_id)
        
    Example:
        >>> logger = logging.getLogger(__name__)
        >>> with_correlation_id(logger, 'info', "Processing batch", batch_size=100)
        >>> # Logs: "Processing batch" with extra={'correlation_id': '...', 'batch_size': 100}
    """
    log_func = getattr(logger, level.lower())
    extra = kwargs.pop('extra', {})
    extra['correlation_id'] = get_correlation_id()
    log_func(message, extra=extra, **kwargs)


def get_correlation_context() -> dict:
    """
    Get dictionary with correlation ID for structured logging
    
    Phase 4 (B2-006): Returns dict suitable for use with logging extra parameter.
    Useful for batch operations where same dict is reused.
    
    Returns:
        Dict with correlation_id key
        
    Example:
        >>> context = get_correlation_context()
        >>> logging.info("Step 1", extra=context)
        >>> logging.info("Step 2", extra=context)
        >>> # Both logs share same correlation ID
    """
    return {'correlation_id': get_correlation_id()}
