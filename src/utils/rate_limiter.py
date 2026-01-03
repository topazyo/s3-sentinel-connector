# src/utils/rate_limiter.py

"""
Rate limiting implementation using token bucket algorithm.

Implements Phase 5 (Security) requirement: Rate limiting on all S3 operations
to prevent abuse and respect AWS service limits.

Reference: VIBE_AUDIT_ROADMAP.md, SEC-07
Story: B1-001 (Implement rate limiting)
"""

import asyncio
import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Thread-safe token bucket rate limiter.
    
    Enforces a maximum request rate by distributing tokens at a fixed rate.
    Each operation consumes one token. If no tokens are available, the caller
    must wait until tokens are replenished.
    
    **Phase 4 (Resilience):** Prevents thundering herd by using token bucket
    **Phase 5 (Security):** Prevents abuse by rate limiting all operations
    **Phase 6 (Performance):** Configurable to balance throughput vs protection
    
    Attributes:
        rate: Maximum requests per second (tokens added per second)
        capacity: Maximum burst capacity (tokens that can accumulate)
        tokens: Current available tokens
        last_update: Timestamp of last token replenishment
    
    Example:
        >>> limiter = RateLimiter(rate=10.0, capacity=20)
        >>> limiter.acquire()  # Blocks if no tokens available
        >>> await limiter.acquire_async()  # Async variant
    """
    
    def __init__(self, rate: float = 10.0, capacity: Optional[float] = None):
        """
        Initialize rate limiter with token bucket parameters.
        
        Args:
            rate: Tokens added per second (requests/sec). Default 10.0 req/sec
                  respects AWS S3 best practices (3,500 PUT/COPY/POST/DELETE,
                  5,500 GET/HEAD per second per prefix).
            capacity: Maximum tokens that can accumulate (burst capacity).
                     If None, defaults to 2x rate (allows short bursts).
        
        **Phase 2 (Consistency):** Configurable via environment/config
        **Phase 5 (Security):** Conservative default (10 req/sec) prevents abuse
        """
        if rate <= 0:
            raise ValueError(f"Rate must be positive, got {rate}")
        
        self.rate = float(rate)
        self.capacity = float(capacity) if capacity is not None else (2 * self.rate)
        
        if self.capacity < self.rate:
            logger.warning(
                "Rate limiter capacity (%s) < rate (%s). "
                "This may cause blocking on every request.",
                self.capacity, self.rate
            )
        
        # Initialize with full capacity (allow immediate burst)
        self.tokens = self.capacity
        self.last_update = time.monotonic()
        
        # Thread safety (Phase 4: Resilience)
        self._lock = threading.Lock()
        self._async_lock = asyncio.Lock()
        
        logger.info(
            "RateLimiter initialized: rate=%.2f req/sec, capacity=%.2f tokens",
            self.rate, self.capacity
        )
    
    def _refill_tokens(self) -> None:
        """
        Refill tokens based on elapsed time since last update.
        
        **Internal method:** Should only be called while holding self._lock
        
        **Phase 6 (Performance):** Uses monotonic time to avoid clock skew issues
        """
        now = time.monotonic()
        elapsed = now - self.last_update
        
        # Add tokens based on elapsed time
        new_tokens = elapsed * self.rate
        self.tokens = min(self.capacity, self.tokens + new_tokens)
        self.last_update = now
    
    def acquire(self, tokens: float = 1.0, timeout: Optional[float] = None) -> bool:
        """
        Acquire tokens synchronously, blocking if necessary.
        
        Args:
            tokens: Number of tokens to acquire (default 1.0 for single request)
            timeout: Maximum time to wait in seconds. If None, waits indefinitely.
                    If 0, non-blocking (returns False if tokens unavailable).
        
        Returns:
            True if tokens acquired, False if timeout exceeded
        
        Raises:
            ValueError: If tokens <= 0 or tokens > capacity
        
        **Phase 4 (Resilience):** Timeout prevents indefinite blocking
        **Phase 6 (Performance):** Thread-safe with minimal lock contention
        
        Example:
            >>> limiter = RateLimiter(rate=10.0)
            >>> if limiter.acquire(timeout=5.0):
            ...     # Proceed with operation
            ...     make_s3_request()
            ... else:
            ...     # Timeout exceeded
            ...     logger.warning("Rate limit acquisition timeout")
        """
        if tokens <= 0:
            raise ValueError(f"Tokens must be positive, got {tokens}")
        if tokens > self.capacity:
            raise ValueError(
                f"Requested tokens ({tokens}) exceeds capacity ({self.capacity})"
            )
        
        deadline = None if timeout is None else (time.monotonic() + timeout)
        
        while True:
            with self._lock:
                self._refill_tokens()
                
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    logger.debug(
                        "Acquired %.2f tokens (remaining: %.2f/%.2f)",
                        tokens, self.tokens, self.capacity
                    )
                    return True
                
                # Check timeout (non-blocking or deadline exceeded)
                if timeout == 0:
                    logger.debug("Rate limit: insufficient tokens (non-blocking)")
                    return False
                
                if deadline and time.monotonic() >= deadline:
                    logger.warning(
                        "Rate limit acquisition timeout after %.2fs", timeout
                    )
                    return False
                
                # Calculate sleep time: how long until we have enough tokens?
                tokens_needed = tokens - self.tokens
                wait_time = tokens_needed / self.rate
                
                # Cap wait time to avoid excessive blocking
                if deadline:
                    wait_time = min(wait_time, deadline - time.monotonic())
                else:
                    wait_time = min(wait_time, 1.0)  # Cap at 1 second per iteration
            
            # Sleep outside the lock to allow other threads to proceed
            if wait_time > 0:
                time.sleep(wait_time)
    
    async def acquire_async(
        self, tokens: float = 1.0, timeout: Optional[float] = None
    ) -> bool:
        """
        Acquire tokens asynchronously, yielding control if tokens unavailable.
        
        Args:
            tokens: Number of tokens to acquire (default 1.0 for single request)
            timeout: Maximum time to wait in seconds. If None, waits indefinitely.
        
        Returns:
            True if tokens acquired, False if timeout exceeded
        
        Raises:
            ValueError: If tokens <= 0 or tokens > capacity
        
        **Phase 4 (Resilience):** Async-friendly, doesn't block event loop
        **Phase 6 (Performance):** Allows concurrent operations while waiting
        
        Example:
            >>> limiter = RateLimiter(rate=10.0)
            >>> if await limiter.acquire_async(timeout=5.0):
            ...     await make_s3_request_async()
            ... else:
            ...     logger.warning("Rate limit acquisition timeout")
        """
        if tokens <= 0:
            raise ValueError(f"Tokens must be positive, got {tokens}")
        if tokens > self.capacity:
            raise ValueError(
                f"Requested tokens ({tokens}) exceeds capacity ({self.capacity})"
            )
        
        deadline = None if timeout is None else (time.monotonic() + timeout)
        
        while True:
            async with self._async_lock:
                # Refill tokens (use synchronous method since it's fast)
                now = time.monotonic()
                elapsed = now - self.last_update
                new_tokens = elapsed * self.rate
                self.tokens = min(self.capacity, self.tokens + new_tokens)
                self.last_update = now
                
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    logger.debug(
                        "Acquired %.2f tokens async (remaining: %.2f/%.2f)",
                        tokens, self.tokens, self.capacity
                    )
                    return True
                
                # Check timeout
                if timeout == 0:
                    logger.debug("Rate limit: insufficient tokens (non-blocking async)")
                    return False
                
                if deadline and time.monotonic() >= deadline:
                    logger.warning(
                        "Rate limit async acquisition timeout after %.2fs", timeout
                    )
                    return False
                
                # Calculate sleep time
                tokens_needed = tokens - self.tokens
                wait_time = tokens_needed / self.rate
                
                if deadline:
                    wait_time = min(wait_time, deadline - time.monotonic())
                else:
                    wait_time = min(wait_time, 1.0)
            
            # Sleep outside the lock using asyncio.sleep
            if wait_time > 0:
                await asyncio.sleep(wait_time)
    
    def reset(self) -> None:
        """
        Reset rate limiter to full capacity.
        
        **Use case:** Testing, or manual override after long idle period.
        **Phase 7 (Testing):** Useful for deterministic test setup
        """
        with self._lock:
            self.tokens = self.capacity
            self.last_update = time.monotonic()
            logger.info("RateLimiter reset to full capacity (%.2f tokens)", self.capacity)
    
    def get_available_tokens(self) -> float:
        """
        Get current available tokens (includes refill since last update).
        
        Returns:
            Current available tokens (float)
        
        **Phase 4 (Observability):** Allows monitoring of rate limiter state
        **Phase 7 (Testing):** Useful for assertions in tests
        """
        with self._lock:
            self._refill_tokens()
            return self.tokens
    
    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"RateLimiter(rate={self.rate:.2f} req/sec, "
            f"capacity={self.capacity:.2f}, tokens={self.tokens:.2f})"
        )
