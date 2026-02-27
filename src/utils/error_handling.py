# src/utils/error_handling.py
"""Retry and structured error handling primitives used across pipeline components."""

import asyncio
import functools
import logging
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional


@dataclass
class ErrorConfig:
    """Configuration for error handling"""

    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter: float = 0.1
    error_codes: Dict[str, bool] = None  # Map error codes to retryable status


class RetryableError(Exception):
    """Base class for retryable errors"""

    pass


class NonRetryableError(Exception):
    """Base class for non-retryable errors"""

    pass


class ErrorHandler:
    """Centralized retry decision and error telemetry helper."""

    def __init__(self, config: Optional[ErrorConfig] = None) -> None:
        """
        Initialize error handler

        Args:
            config: Error handling configuration
        """
        self.config = config or ErrorConfig()
        self.logger = logging.getLogger(__name__)

        # Initialize error tracking
        self.error_counts: Dict[str, int] = {}
        self.last_errors: Dict[str, datetime] = {}

    def handle_error(
        self, error: Exception, context: str, retry_count: int = 0
    ) -> bool:
        """
        Handle error and determine if retry is needed

        Args:
            error: Exception that occurred
            context: Error context
            retry_count: Current retry attempt

        Returns:
            Boolean indicating if retry should be attempted
        """
        try:
            # Update error tracking
            self._track_error(context, error)

            # Log error details
            self._log_error(error, context, retry_count)

            # Check if error is retryable
            if not self._is_retryable(error):
                return False

            # Check retry count
            if retry_count >= self.config.max_retries:
                return False

            return True

        except Exception as e:
            self.logger.error(f"Error in error handler: {e!s}")
            return False

    def _track_error(self, context: str, error: Exception):
        """Track error occurrence"""
        current_time = datetime.now(timezone.utc)

        if context not in self.error_counts:
            self.error_counts[context] = 0

        self.error_counts[context] += 1
        self.last_errors[context] = current_time

    def _log_error(self, error: Exception, context: str, retry_count: int):
        """Log detailed error information"""
        error_type = type(error).__name__
        error_msg = str(error)
        stack_trace = traceback.format_exc()

        log_data = {
            "error_type": error_type,
            "error_message": error_msg,
            "context": context,
            "retry_count": retry_count,
            "stack_trace": stack_trace,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if retry_count > 0:
            self.logger.warning(f"Retry attempt {retry_count} failed: {error_msg}")
        else:
            self.logger.error(f"Operation failed: {error_msg}")

        self.logger.debug(f"Error details: {log_data}")

    def _is_retryable(self, error: Exception) -> bool:
        """Determine if error is retryable"""
        # Check if error is explicitly retryable
        if isinstance(error, RetryableError):
            return True

        # Check if error is explicitly non-retryable
        if isinstance(error, NonRetryableError):
            return False

        # Check error codes if configured
        if self.config.error_codes and hasattr(error, "code"):
            return self.config.error_codes.get(error.code, False)

        # Default to non-retryable
        return False

    def get_retry_delay(self, retry_count: int) -> float:
        """Calculate retry delay with exponential backoff and jitter"""
        delay = min(
            self.config.base_delay * (self.config.exponential_base**retry_count),
            self.config.max_delay,
        )

        # Add jitter
        import random

        jitter = random.uniform(-self.config.jitter, self.config.jitter)
        return max(0, delay + (delay * jitter))


def retry_with_backoff(
    retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    error_handler: Optional[ErrorHandler] = None,
):
    """
    Decorator for implementing retry logic with exponential backoff

    Args:
        retries: Maximum number of retries
        base_delay: Base delay between retries
        max_delay: Maximum delay between retries
        error_handler: Optional custom error handler
    """

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            handler = error_handler or ErrorHandler(
                ErrorConfig(
                    max_retries=retries, base_delay=base_delay, max_delay=max_delay
                )
            )

            retry_count = 0
            while True:
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    context = f"{func.__name__}({args}, {kwargs})"

                    if not handler.handle_error(e, context, retry_count):
                        raise

                    retry_count += 1
                    delay = handler.get_retry_delay(retry_count)

                    await asyncio.sleep(delay)

        return wrapper

    return decorator
