# src/core/s3_handler.py

import asyncio
import gzip
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from ..utils.error_handling import RetryableError
from ..utils.rate_limiter import RateLimiter
from ..utils.tracing import get_correlation_context
from .log_parser import LogParser


class S3Handler:
    def __init__(
        self,
        aws_access_key: str,
        aws_secret_key: str,
        region: str,
        max_retries: int = 3,
        batch_size: int = 10,
        max_threads: int = 5,
        rate_limiter: Optional[RateLimiter] = None,
        rate_limit: Optional[float] = None,
    ) -> None:
        """
        Initialize S3 handler with configuration and monitoring

        Args:
            aws_access_key: AWS access key
            aws_secret_key: AWS secret key
            region: AWS region
            max_retries: Maximum number of retry attempts
            batch_size: Number of files to process in each batch
            max_threads: Maximum number of concurrent threads
            rate_limiter: Optional RateLimiter instance. If None and rate_limit
                         is specified, creates a new RateLimiter.
            rate_limit: Maximum requests per second (default: 10.0 req/sec).
                       Only used if rate_limiter is None.

        **Phase 5 (Security - B1-001):** Rate limiting prevents abuse and
        respects AWS service limits. Default 10 req/sec is conservative.
        """
        self.setup_logging()
        self.max_retries = max_retries
        self.batch_size = batch_size
        self.max_threads = max_threads
        self.metrics = {
            "files_processed": 0,
            "bytes_processed": 0,
            "errors": 0,
            "processing_time": 0,
            "rate_limited": 0,  # Track how many operations were rate limited
        }
        self._executor = ThreadPoolExecutor(max_workers=self.max_threads)

        # Initialize rate limiter (Phase 5: Security - B1-001)
        if rate_limiter is not None:
            self.rate_limiter = rate_limiter
        elif rate_limit is not None:
            self.rate_limiter = RateLimiter(rate=rate_limit)
        else:
            # Default: 10 req/sec (conservative, respects AWS best practices)
            self.rate_limiter = RateLimiter(rate=10.0)

        logging.info(
            "S3Handler initialized with rate limiting: %s",
            self.rate_limiter,
            extra=get_correlation_context(),  # Phase 4 (B2-006): Add correlation ID
        )

        try:
            self.s3_client = boto3.client(
                "s3",
                aws_access_key_id=aws_access_key,
                aws_secret_access_key=aws_secret_key,
                region_name=region,
                config=Config(
                    retries={"max_attempts": max_retries},
                    connect_timeout=5,
                    read_timeout=30,
                ),
            )
            logging.info(
                f"Successfully initialized S3 client in region {region}",
                extra=get_correlation_context(),  # Phase 4 (B2-006): Add correlation ID
            )
        except Exception as e:
            logging.critical(f"Failed to initialize S3 client: {e!s}")
            raise

    def setup_logging(self) -> None:
        """Configure detailed logging with timestamps and log levels"""
        logging.basicConfig(
            format="%(asctime)s %(levelname)-8s [%(filename)s:%(lineno)d] %(message)s",
            level=logging.INFO,
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    def list_objects(
        self,
        bucket: str,
        prefix: str = "",
        last_processed_time: Optional[datetime] = None,
        max_keys: int = 1000,
    ) -> List[Dict[str, Any]]:
        """
        Synchronously list objects in S3 with filtering and pagination.

        **Phase 5 (Security - B1-001):** Rate limited to prevent abuse.
        Default: 10 req/sec. Configurable via rate_limit parameter in __init__.
        """
        if last_processed_time and last_processed_time.tzinfo is None:
            last_processed_time = last_processed_time.replace(tzinfo=timezone.utc)
        return self._list_objects_sync(bucket, prefix, last_processed_time, max_keys)

    async def list_objects_async(
        self,
        bucket: str,
        prefix: str = "",
        last_processed_time: Optional[datetime] = None,
        max_keys: int = 1000,
    ) -> List[Dict[str, Any]]:
        """Async wrapper for listing objects with async rate limiting."""
        # Phase 5 (Security - B1-001): Apply async rate limiting
        if not await self.rate_limiter.acquire_async(timeout=30.0):
            error_msg = (
                f"Rate limit timeout (async) for list_objects: {bucket}/{prefix}"
            )
            logging.error(
                error_msg,
                extra=get_correlation_context(),  # Phase 4 (B2-006): Add correlation ID
            )
            self.metrics["rate_limited"] += 1
            raise RetryableError(error_msg)

        loop = asyncio.get_running_loop()
        # Note: Actual S3 call uses sync client (no async rate limit needed internally)
        return await loop.run_in_executor(
            self._executor,
            self._list_objects_internal,
            bucket,
            prefix,
            last_processed_time,
            max_keys,
        )

    def _list_objects_internal(
        self,
        bucket: str,
        prefix: str,
        last_processed_time: Optional[datetime],
        max_keys: int,
    ) -> List[Dict[str, Any]]:
        """Internal list objects without rate limiting (rate limit applied in caller)."""
        objects: List[Dict[str, Any]] = []
        paginator = self.s3_client.get_paginator("list_objects_v2")

        try:
            page_iterator = paginator.paginate(
                Bucket=bucket, Prefix=prefix, PaginationConfig={"MaxItems": max_keys}
            )

            for page in page_iterator:
                if "Contents" not in page:
                    continue

                for obj in page["Contents"]:
                    if (
                        last_processed_time
                        and obj["LastModified"] <= last_processed_time
                    ):
                        continue

                    if obj["Size"] == 0 or not self._is_valid_file(obj["Key"]):
                        continue

                    objects.append(
                        {
                            "Key": obj["Key"],
                            "Size": obj["Size"],
                            "LastModified": obj["LastModified"],
                            "ETag": obj["ETag"],
                            "StorageClass": obj.get("StorageClass", "STANDARD"),
                        }
                    )

            logging.info("Found %s new objects in %s/%s", len(objects), bucket, prefix)
            return objects

        except ClientError as e:
            self._handle_aws_error(e)
        except Exception:
            raise

    def _is_valid_file(self, key: str) -> bool:
        """Check if file should be processed based on extension and patterns"""
        valid_extensions = [".log", ".json", ".gz", ".csv"]
        excluded_patterns = ["temp", "partial", "incomplete"]

        # Check file extension
        if not any(key.endswith(ext) for ext in valid_extensions):
            return False

        # Check for excluded patterns
        if any(pattern in key.lower() for pattern in excluded_patterns):
            return False

        return True

    def process_files_batch(
        self,
        bucket: str,
        objects: List[Dict[str, Any]],
        parser: Optional[LogParser] = None,
        callback: Optional[callable] = None,
        log_type: Optional[str] = None,
        batch_size: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Synchronously process files with optional parsing and callback."""
        batch_size = batch_size or self.batch_size
        results: Dict[str, Any] = {
            "processed": 0,
            "failed": 0,
            "errors": [],
            "successful": [],
        }

        if not objects:
            return results

        chunks = [
            objects[i : i + batch_size] for i in range(0, len(objects), batch_size)
        ]

        for chunk in chunks:
            parsed_batch: List[Any] = []
            for obj in chunk:
                key = obj["Key"]
                try:
                    content = self.download_object(bucket, key)
                    if not self._validate_content(content, key):
                        raise ValueError("Content validation failed")

                    if parser:
                        parsed = parser.parse(content)
                        if not parser.validate(parsed):
                            raise ValueError("Parsed content failed validation")
                        payload = parsed
                    else:
                        payload = content

                    parsed_batch.append(payload)
                    results["processed"] += 1
                    results["successful"].append(
                        {"key": key, "size": obj.get("Size", len(content))}
                    )
                except Exception as e:
                    logging.error(
                        "Failed to process %s: %s",
                        key,
                        str(e),
                        extra=get_correlation_context(),  # Phase 4 (B2-006): Add correlation ID
                    )
                    results["failed"] += 1
                    results["errors"].append({"key": key, "error": str(e)})

            if callback and parsed_batch:
                if asyncio.iscoroutinefunction(callback):
                    if log_type is not None:
                        asyncio.run(callback(parsed_batch, log_type))
                    else:
                        asyncio.run(callback(parsed_batch))
                else:
                    if log_type is not None:
                        callback(parsed_batch, log_type)
                    else:
                        callback(parsed_batch)

        return results

    async def process_files_batch_async(
        self,
        bucket: str,
        objects: List[Dict[str, Any]],
        parser: Optional[LogParser] = None,
        callback: Optional[callable] = None,
        log_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Async variant of batch processing for compatibility with async callers."""
        loop = asyncio.get_running_loop()
        results: Dict[str, Any] = {
            "successful": [],
            "failed": [],
            "metrics": {
                "total_files": len(objects),
                "total_bytes": sum(obj["Size"] for obj in objects) if objects else 0,
                "start_time": datetime.now(timezone.utc),
            },
        }

        if not objects:
            results["metrics"].update(
                {
                    "end_time": datetime.now(timezone.utc),
                    "duration": 0,
                    "success_rate": 0,
                }
            )
            return results

        chunks = [
            objects[i : i + self.batch_size]
            for i in range(0, len(objects), self.batch_size)
        ]

        for chunk in chunks:
            tasks = []
            for obj in chunk:
                tasks.append(
                    loop.run_in_executor(
                        self._executor, self.download_object, bucket, obj["Key"]
                    )
                )

            downloaded = await asyncio.gather(*tasks, return_exceptions=True)
            parsed_batch: List[Any] = []

            for obj, content in zip(chunk, downloaded):
                key = obj["Key"]
                if isinstance(content, Exception):
                    results["failed"].append({"key": key, "error": str(content)})
                    continue

                try:
                    if not self._validate_content(content, key):
                        raise ValueError("Content validation failed")

                    if parser:
                        parsed = await loop.run_in_executor(
                            self._executor, parser.parse, content
                        )
                        is_valid = await loop.run_in_executor(
                            self._executor, parser.validate, parsed
                        )
                        if not is_valid:
                            raise ValueError("Parsed content failed validation")
                        payload = parsed
                    else:
                        payload = content

                    parsed_batch.append(payload)
                    results["successful"].append(
                        {"key": key, "size": obj.get("Size", len(content))}
                    )
                except Exception as e:
                    results["failed"].append({"key": key, "error": str(e)})

            if callback and parsed_batch:
                if asyncio.iscoroutinefunction(callback):
                    if log_type is not None:
                        await callback(parsed_batch, log_type)
                    else:
                        await callback(parsed_batch)
                else:
                    if log_type is not None:
                        callback(parsed_batch, log_type)
                    else:
                        callback(parsed_batch)

        results["metrics"]["end_time"] = datetime.now(timezone.utc)
        results["metrics"]["duration"] = (
            results["metrics"]["end_time"] - results["metrics"]["start_time"]
        ).total_seconds()
        success_count = len(results["successful"])
        results["metrics"]["success_rate"] = (
            success_count / results["metrics"]["total_files"]
            if results["metrics"]["total_files"]
            else 0
        )
        return results

    def _download_object(self, bucket: str, key: str) -> bytes:
        """Retained for backward compatibility; calls sync download."""
        return self._download_object_sync(bucket, key)

    def download_object(self, bucket: str, key: str) -> bytes:
        """Public synchronous download method used in tests and callers."""
        return self._download_object_sync(bucket, key)

    def _download_object_sync(self, bucket: str, key: str) -> bytes:
        """Synchronous download with optional decompression and rate limiting."""
        # Phase 5 (Security - B1-001): Apply rate limiting before S3 API call
        if not self.rate_limiter.acquire(timeout=30.0):
            error_msg = f"Rate limit timeout acquiring token for download: {key}"
            logging.error(
                error_msg,
                extra=get_correlation_context(),  # Phase 4 (B2-006): Add correlation ID
            )
            self.metrics["rate_limited"] += 1
            raise RetryableError(error_msg)

        try:
            response = self.s3_client.get_object(Bucket=bucket, Key=key)
            body = response["Body"].read()

            if key.endswith(".gz"):
                body = gzip.decompress(body)

            return body

        except ClientError as e:
            self._handle_aws_error(e)
        except Exception:
            raise

    def _list_objects_sync(
        self,
        bucket: str,
        prefix: str,
        last_processed_time: Optional[datetime],
        max_keys: int,
    ) -> List[Dict[str, Any]]:
        """Synchronous list objects with rate limiting."""
        # Phase 5 (Security - B1-001): Apply rate limiting before S3 API call
        if not self.rate_limiter.acquire(timeout=30.0):
            error_msg = f"Rate limit timeout acquiring token for list_objects: {bucket}/{prefix}"
            logging.error(
                error_msg,
                extra=get_correlation_context(),  # Phase 4 (B2-006): Add correlation ID
            )
            self.metrics["rate_limited"] += 1
            raise RetryableError(error_msg)

        return self._list_objects_internal(
            bucket, prefix, last_processed_time, max_keys
        )

    def _list_objects_internal(
        self,
        bucket: str,
        prefix: str,
        last_processed_time: Optional[datetime],
        max_keys: int,
    ) -> List[Dict[str, Any]]:
        """Internal list objects implementation (no rate limiting - applied by caller)."""
        objects: List[Dict[str, Any]] = []
        paginator = self.s3_client.get_paginator("list_objects_v2")

        try:
            page_iterator = paginator.paginate(
                Bucket=bucket, Prefix=prefix, PaginationConfig={"MaxItems": max_keys}
            )

            for page in page_iterator:
                if "Contents" not in page:
                    continue

                for obj in page["Contents"]:
                    if (
                        last_processed_time
                        and obj["LastModified"] <= last_processed_time
                    ):
                        continue

                    if obj["Size"] == 0 or not self._is_valid_file(obj["Key"]):
                        continue

                    objects.append(
                        {
                            "Key": obj["Key"],
                            "Size": obj["Size"],
                            "LastModified": obj["LastModified"],
                            "ETag": obj["ETag"],
                            "StorageClass": obj.get("StorageClass", "STANDARD"),
                        }
                    )

            logging.info("Found %s new objects in %s/%s", len(objects), bucket, prefix)
            return objects

        except ClientError as e:
            self._handle_aws_error(e)
        except Exception:
            raise

    def _validate_content(self, content: bytes, key: str) -> bool:
        """Basic content validation to ensure non-empty payloads."""
        if not content:
            logging.error("Empty content for %s", key)
            return False

        # Quick JSON sanity check for .json files
        if key.endswith(".json"):
            try:
                import json

                json.loads(content)
            except Exception:
                logging.error("Invalid JSON content in %s", key)
                return False

        return True

    def _log_batch_results(self, results: Dict[str, Any]) -> None:
        """Log batch processing metrics."""
        metrics = results["metrics"]
        logging.info(
            "Batch processed %s files (success: %s, failed: %s) in %.2fs",
            metrics["total_files"],
            len(results["successful"]),
            len(results["failed"]),
            metrics.get("duration", 0),
        )

    def _get_error_message(self, error_code: str) -> str:
        """Map S3 error codes to human-readable messages."""
        messages = {
            "SlowDown": "S3 is throttling requests. Backing off and retrying.",
            "InternalError": "S3 internal error encountered.",
            "AccessDenied": "Access denied to the requested S3 resource.",
            "NoSuchKey": "Requested object does not exist.",
        }
        return messages.get(error_code, f"S3 error {error_code}")

    def _handle_aws_error(self, error: ClientError) -> None:
        """Handle AWS errors with retryable mapping."""
        error_code = error.response["Error"].get("Code")
        error_msg = self._get_error_message(error_code)
        logging.error(
            "S3 operation failed: %s",
            error_msg,
            extra=get_correlation_context(),  # Phase 4 (B2-006): Add correlation ID
        )

        if error_code in ["SlowDown", "InternalError", "503"]:
            raise RetryableError(error_msg)

        raise error
