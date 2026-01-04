# src/core/sentinel_router.py

import asyncio
import hashlib
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, ClassVar, Dict, List, Optional, Set

from azure.core.exceptions import AzureError
from azure.identity import DefaultAzureCredential
from azure.monitor.ingestion import LogsIngestionClient

# Phase 4 (Resilience - B2-001): Circuit breaker for external service protection
from ..utils.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpenError,
)

# Phase 4 (Observability - B2-006): Correlation IDs for cross-component tracing
from ..utils.tracing import get_correlation_id

try:
    from azure.storage.blob import BlobServiceClient, ContainerClient

    BLOB_STORAGE_AVAILABLE = True
except ImportError:
    BLOB_STORAGE_AVAILABLE = False
    BlobServiceClient = None
    ContainerClient = None


@dataclass
class TableConfig:
    """Configuration for a Sentinel table"""

    table_name: str
    schema_version: str
    required_fields: List[str]
    retention_days: int
    transform_map: Dict[str, str]
    data_type_map: Dict[str, str]
    compression_enabled: bool = True
    batch_size: int = 1000


class SentinelRouter:
    """
    Routes logs to Azure Sentinel with batching, retry, and observability.

    Phase 4 (Resilience - B2-001): Circuit breaker protection for Azure calls
    Phase 4 (Observability - B1-008): Tracks dropped logs with reasons
    Phase 4 (Observability - B2-005): Tracks failed batches with categorization
    Phase 5 (Security - B2-011): Redacts PII from failed batch storage
    """

    # Phase 5 (Security - B2-011/P2-SEC-03): PII redaction patterns
    PII_PATTERNS: ClassVar[Dict[str, re.Pattern]] = {
        "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
        "phone": re.compile(
            r"\b\d{3}[-.]?\d{4}\b|\b\d{3}[-.]?\d{3}[-.]?\d{4}\b"
        ),  # XXX-XXXX or XXX-XXX-XXXX
        "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        "credit_card": re.compile(r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b"),
        "ipv4": re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b"),
        "api_key": re.compile(
            r"\b[a-zA-Z0-9_]{32,}\b"
        ),  # Generic long alphanumeric strings (with underscores)
    }

    # Field names that commonly contain PII (case-insensitive matching)
    # Note: 'name' is too generic and causes false positives, excluded
    PII_FIELD_NAMES: ClassVar[Set[str]] = {
        "password",
        "passwd",
        "pwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "authorization",
        "auth",
        "bearer",
        "cookie",
        "session",
        "email",
        "e_mail",
        "mail",
        "phone",
        "telephone",
        "mobile",
        "ssn",
        "social_security",
        "credit_card",
        "creditcard",
        "card_number",
        "address",
        "street",
        "zipcode",
        "postal_code",
        "firstname",
        "lastname",
        "fullname",
        "username",
        "user_name",
    }

    def __init__(
        self,
        dcr_endpoint: str,
        rule_id: str,
        stream_name: str,
        max_retries: int = 3,
        batch_timeout: int = 30,
        logs_client: Optional[Any] = None,
        credential: Optional[Any] = None,
    ) -> None:
        """
        Initialize Sentinel router with configuration

        Args:
            dcr_endpoint: Data Collection Rule endpoint
            rule_id: Data Collection Rule ID
            stream_name: Log stream name
            max_retries: Maximum number of retry attempts
            batch_timeout: Timeout for batch operations in seconds
        """
        self.dcr_endpoint = dcr_endpoint
        self.rule_id = rule_id
        self.stream_name = stream_name
        self.max_retries = max_retries
        self.batch_timeout = batch_timeout

        # Initialize Azure clients (can be overridden for tests)
        if logs_client is not None:
            self.logs_client = logs_client
        else:
            self._initialize_azure_clients(credential)

        # Load table configurations
        self.table_configs = self._load_table_configs()

        # Initialize metrics
        self.metrics = {
            "records_processed": 0,
            "bytes_ingested": 0,
            "failed_records": 0,
            "dropped_logs": 0,  # Phase 4 (B1-008/OBS-03): Track silently dropped logs
            "drop_reasons": {},  # Phase 4 (B1-008): Count drops by reason
            "failed_batch_count": 0,  # Phase 4 (B2-005/RES-05): Track failed batches
            "failure_reasons": {},  # Phase 4 (B2-005): Count batch failures by reason
            "last_ingestion_time": None,
        }

        # Initialize executor for sync operations
        self._executor = ThreadPoolExecutor(max_workers=4)

        # Phase 4 (Resilience - B2-001): Circuit breaker for Azure Sentinel
        circuit_config = CircuitBreakerConfig(
            failure_threshold=5,  # Open after 5 failures
            recovery_timeout=60,  # Attempt recovery after 60s
            success_threshold=2,  # Need 2 successes to close
            operation_timeout=batch_timeout,  # Use batch_timeout for operations
        )
        self._circuit_breaker = CircuitBreaker("azure-sentinel", circuit_config)

        # Initialize failed batch storage from config (not environment)
        # Container name should be passed via config, not os.getenv
        self.failed_batches_container = (
            "sentinel-failed-batches"
        )  # Can be overridden via setter
        self._blob_client: Optional[BlobServiceClient] = None

    def set_failed_batches_container(self, container_name: str) -> None:
        """Set the failed batches container name (should come from config, not environment)"""
        self.failed_batches_container = container_name

    def _initialize_azure_clients(self, credential: Optional[Any] = None):
        """Initialize Azure clients with error handling"""
        try:
            credential = credential or DefaultAzureCredential()
            self.logs_client = LogsIngestionClient(
                endpoint=self.dcr_endpoint, credential=credential, logging_enable=True
            )
            logging.info("Successfully initialized Azure clients")
        except Exception as e:
            logging.critical(f"Failed to initialize Azure clients: {e!s}")
            raise

    def _load_table_configs(self) -> Dict[str, TableConfig]:
        """Load and validate table configurations"""
        # This could be loaded from a configuration file
        return {
            "firewall": TableConfig(
                table_name="Custom_Firewall_CL",
                schema_version="1.0",
                required_fields=[
                    "TimeGenerated",
                    "SourceIP",
                    "DestinationIP",
                    "Action",
                ],
                retention_days=90,
                transform_map={
                    "src_ip": "SourceIP",
                    "dst_ip": "DestinationIP",
                    "action": "Action",
                },
                data_type_map={
                    "TimeGenerated": "datetime",
                    "SourceIP": "string",
                    "DestinationIP": "string",
                    "BytesTransferred": "long",
                },
            ),
            "vpn": TableConfig(
                table_name="Custom_VPN_CL",
                schema_version="2.1",
                required_fields=["TimeGenerated", "UserPrincipalName", "SessionID"],
                retention_days=30,
                transform_map={
                    "user": "UserPrincipalName",
                    "session": "SessionID",
                    "ip_address": "ClientIP",
                },
                data_type_map={
                    "TimeGenerated": "datetime",
                    "SessionID": "string",
                    "BytesIn": "long",
                    "BytesOut": "long",
                },
            ),
        }

    async def route_logs(
        self,
        log_type: str,
        logs: List[Dict[str, Any]],
        data_classification: str = "standard",
    ) -> Dict[str, Any]:
        """
        Route logs to appropriate Sentinel table with batching and error handling

        Args:
            log_type: Type of logs (e.g., 'firewall', 'vpn')
            logs: List of log dictionaries to route
            data_classification: Classification level of the data

        Returns:
            Dict containing routing metrics and results
        """
        if not logs:
            return {"status": "skip", "message": "No logs to process"}

        table_config = self.table_configs.get(log_type)
        if not table_config:
            raise ValueError(f"Unsupported log type: {log_type}")

        results = {
            "processed": 0,
            "failed": 0,
            "batch_count": 0,
            "start_time": datetime.now(timezone.utc),
        }

        try:
            # Prepare logs for ingestion
            initial_count = len(logs)
            prepared_logs = [
                self._prepare_log_entry(log, table_config, data_classification)
                for log in logs
            ]

            # Phase 4 (Observability - B1-008/OBS-03): Track dropped logs
            # Filter out None values (failed preparations) and meter them
            valid_logs = [log for log in prepared_logs if log is not None]
            dropped_count = initial_count - len(valid_logs)

            if dropped_count > 0:
                # Phase 4 (B1-008): Meter dropped logs
                self.metrics["dropped_logs"] += dropped_count
                drop_rate = (dropped_count / initial_count) * 100

                # Phase 4 (B1-008): Warn when logs are dropped
                logging.warning(
                    f"Dropped {dropped_count}/{initial_count} logs ({drop_rate:.1f}%) "
                    f"in {log_type} batch. "
                    f"Total dropped: {self.metrics['dropped_logs']}. "
                    f"Reasons: {self.metrics.get('drop_reasons', {})}. "
                    f"Check log preparation errors above."
                )

            # Process in batches
            batches = self._create_batches(valid_logs, table_config.batch_size)

            async with asyncio.TaskGroup() as group:
                for batch in batches:
                    group.create_task(self._ingest_batch(batch, table_config, results))

            self._update_metrics(results)
            return results

        except Exception as e:
            logging.error(f"Error routing logs: {e!s}")
            raise

    def _prepare_log_entry(
        self, log: Dict[str, Any], table_config: TableConfig, data_classification: str
    ) -> Optional[Dict[str, Any]]:
        """Prepare a single log entry for ingestion"""
        try:
            # Transform fields according to mapping
            transformed_log = {}
            for source, target in table_config.transform_map.items():
                if source in log:
                    transformed_log[target] = log[source]

            # Preserve fields that already match expected targets
            for key, value in log.items():
                if (
                    key in table_config.required_fields
                    or key in table_config.data_type_map
                ):
                    transformed_log.setdefault(key, value)

            # Add required fields if missing
            if "TimeGenerated" not in transformed_log:
                transformed_log["TimeGenerated"] = datetime.now(
                    timezone.utc
                ).isoformat()

            # Add metadata
            transformed_log["DataClassification"] = data_classification
            transformed_log["SchemaVersion"] = table_config.schema_version

            # Validate data types
            for field, expected_type in table_config.data_type_map.items():
                if field in transformed_log:
                    transformed_log[field] = self._convert_data_type(
                        transformed_log[field], expected_type
                    )

            # Validate required fields
            missing_fields = [
                f for f in table_config.required_fields if f not in transformed_log
            ]
            if missing_fields:
                # Phase 4 (Observability - B1-008/OBS-03): Track drop reason
                drop_reason = f"missing_fields:{','.join(missing_fields)}"
                self.metrics["drop_reasons"][drop_reason] = (
                    self.metrics["drop_reasons"].get(drop_reason, 0) + 1
                )

                logging.warning(
                    f"Dropping log due to missing required fields: {missing_fields}. "
                    f"Log preview: {str(log)[:200]}..."
                )
                return None

            return transformed_log

        except Exception as e:
            # Phase 4 (Observability - B1-008/OBS-03): Track drop reason
            error_type = type(e).__name__
            drop_reason = f"preparation_error:{error_type}"
            self.metrics["drop_reasons"][drop_reason] = (
                self.metrics["drop_reasons"].get(drop_reason, 0) + 1
            )

            logging.error(
                f"Dropping log due to preparation error ({error_type}): {e!s}. "
                f"Log preview: {str(log)[:200]}..."
            )
            return None

    async def _ingest_batch(
        self,
        batch: List[Dict[str, Any]],
        table_config: TableConfig,
        results: Dict[str, Any],
    ) -> None:
        """Ingest a batch of logs to Sentinel with circuit breaker protection

        Phase 4 (Resilience - B2-001): Wraps Azure SDK calls with circuit breaker
        """
        try:
            # Phase 4 (Resilience - B2-001): Wrap upload in circuit breaker
            async def upload_with_circuit_breaker():
                body = json.dumps(
                    batch,
                    default=lambda o: o.isoformat() if isinstance(o, datetime) else o,
                )

                if table_config.compression_enabled:
                    body = self._compress_data(body)

                # Azure SDK upload() is synchronous, wrap in executor
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    self._executor,
                    self.logs_client.upload,
                    self.rule_id,
                    self.stream_name,
                    body,
                    "application/json",
                )

            # Execute through circuit breaker (Phase 4 - B2-001)
            await self._circuit_breaker.call(upload_with_circuit_breaker)

            results["processed"] += len(batch)
            results["batch_count"] += 1

        except CircuitBreakerOpenError as e:
            # Phase 4 (Resilience - B2-001): Circuit open, reject immediately
            logging.error(f"Circuit breaker OPEN for Azure Sentinel: {e!s}")
            results["failed"] += len(batch)
            # Store failed batch for later retry (Phase 4: Graceful degradation)
            await self._handle_failed_batch(batch, e)

        except AzureError as e:
            logging.error(f"Azure ingestion error: {e!s}")
            results["failed"] += len(batch)
            # Store failed batch for retry if needed
            await self._handle_failed_batch(batch, e)
        except Exception as e:
            logging.error(f"Unexpected error during batch ingestion: {e!s}")
            results["failed"] += len(batch)

    @staticmethod
    def _create_batches(
        logs: List[Dict[str, Any]], batch_size: int
    ) -> List[List[Dict[str, Any]]]:
        """Create batches of logs for processing"""
        return [logs[i : i + batch_size] for i in range(0, len(logs), batch_size)]

    @staticmethod
    def _convert_data_type(value: Any, target_type: str) -> Any:
        """Convert value to target data type"""
        type_converters = {
            "datetime": lambda x: x.isoformat() if isinstance(x, datetime) else x,
            "long": int,
            "double": float,
            "boolean": bool,
            "string": str,
        }

        converter = type_converters.get(target_type)
        if not converter:
            raise ValueError(f"Unsupported data type: {target_type}")

        try:
            return converter(value)
        except (ValueError, TypeError) as e:
            raise ValueError(f"Data type conversion failed: {e!s}") from e

    @staticmethod
    def _compress_data(data: str) -> bytes:
        """Compress data for transmission"""
        import gzip

        return gzip.compress(data.encode("utf-8"))

    async def _handle_failed_batch(
        self, batch: List[Dict[str, Any]], error: Exception
    ) -> None:
        """
        Handle failed batch processing with comprehensive observability

        Phase 4 (B2-005/RES-05): Enhanced failed batch visibility
        - Track batch failure count and failure reasons
        - Categorize errors for trend analysis
        - Log warnings when failure rate exceeds threshold

        Args:
            batch: The failed log batch
            error: The exception that caused the failure
        """
        batch_id = hashlib.md5(str(batch).encode()).hexdigest()

        # Phase 4 (B2-005): Categorize error for observability
        error_category = self._categorize_batch_error(error)

        # Phase 4 (B2-005): Track metrics
        self.metrics["failed_batch_count"] += 1
        self.metrics["failed_records"] += len(batch)
        self.metrics["failure_reasons"][error_category] = (
            self.metrics["failure_reasons"].get(error_category, 0) + 1
        )

        # Store failed batch for retry
        failed_batch_info = {
            "batch_id": batch_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": str(error),
            "error_category": error_category,  # Phase 4 (B2-005): Structured categorization
            "retry_count": 0,
            "data": batch,
        }

        # Could be stored in Azure Storage or other persistent storage
        await self._store_failed_batch(failed_batch_info)

        # Phase 4 (B2-005 + B2-006): Structured logging with correlation ID
        log_extra = {
            "batch_id": batch_id,
            "error_category": error_category,
            "batch_size": len(batch),
            "total_failed_batches": self.metrics["failed_batch_count"],
            "correlation_id": get_correlation_id(),  # Phase 4 (B2-006): Add correlation ID
        }
        logging.error(f"Batch {batch_id} failed: {error!s}", extra=log_extra)

        # Phase 4 (B2-005): Warn on high failure rates
        self._check_failure_rate_and_warn()

    async def _store_failed_batch(self, failed_batch_info: Dict[str, Any]) -> None:
        """
        Store failed batch for later retry using Azure Blob Storage.

        Phase 5 (Security - B2-011/P2-SEC-03): Redacts PII before storage

        Args:
            failed_batch_info: Dictionary containing batch metadata and data
                - batch_id: Unique identifier
                - timestamp: Failure timestamp
                - error: Error message
                - retry_count: Number of retry attempts
                - data: The actual log batch

        Note:
            If Azure Blob Storage is unavailable, falls back to local file storage.
        """
        batch_id = failed_batch_info["batch_id"]
        # Use safe filename format (replace colons with hyphens for Windows)
        timestamp = failed_batch_info["timestamp"].replace(":", "-")
        blob_name = f"failed-batch-{batch_id}-{timestamp}.json"

        try:
            # Phase 5 (B2-011): Redact PII from batch data before storage
            redacted_batch_info = self._redact_pii_from_batch(failed_batch_info)

            # Serialize batch data
            batch_json = json.dumps(
                redacted_batch_info,
                default=lambda o: o.isoformat() if isinstance(o, datetime) else str(o),
                indent=2,
            )

            # Try Azure Blob Storage first
            if BLOB_STORAGE_AVAILABLE and self._blob_client:
                await self._store_to_blob_storage(blob_name, batch_json)
                logging.info(f"Stored failed batch {batch_id} to Azure Blob Storage")
            else:
                # Fallback to local file storage
                await self._store_to_local_file(blob_name, batch_json)
                logging.info(f"Stored failed batch {batch_id} to local storage")

        except Exception as e:
            logging.error(f"Failed to store failed batch {batch_id}: {e!s}")
            # Last resort: log the batch data
            logging.error(
                f"Failed batch data: {json.dumps(failed_batch_info, default=str)}"
            )

    def _redact_pii_from_batch(self, batch_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Redact PII from failed batch before storage.

        Phase 5 (Security - B2-011/P2-SEC-03): Prevents PII exposure in failed batch logs

        Args:
            batch_info: Failed batch info containing 'data' field with log records

        Returns:
            Deep copy of batch_info with PII redacted from 'data' field
        """
        # Deep copy to avoid modifying original
        import copy

        redacted_info = copy.deepcopy(batch_info)

        # Redact PII from batch data
        if "data" in redacted_info and isinstance(redacted_info["data"], list):
            redacted_info["data"] = [
                self._redact_pii_from_record(record) for record in redacted_info["data"]
            ]

        return redacted_info

    def _redact_pii_from_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """
        Redact PII from a single log record.

        Phase 5 (Security - B2-011/P2-SEC-03): Multi-layered PII redaction

        Strategy:
        1. Redact known PII field names (password, email, ssn, etc.)
        2. Scan string values for PII patterns (regex-based)

        Args:
            record: Single log record dictionary

        Returns:
            Record with PII redacted (REDACTED format for visibility)
        """
        import copy

        redacted_record = copy.deepcopy(record)

        for key, value in redacted_record.items():
            # Process nested structures first (preserve structure for debugging)
            if isinstance(value, dict):
                # Recursively redact nested dicts
                redacted_record[key] = self._redact_pii_from_record(value)
            elif isinstance(value, list):
                # Redact list elements
                redacted_record[key] = [
                    (
                        self._redact_pii_from_string(item)
                        if isinstance(item, str)
                        else (
                            self._redact_pii_from_record(item)
                            if isinstance(item, dict)
                            else item
                        )
                    )
                    for item in value
                ]
            elif self._is_pii_field_name(key):
                # Strategy 1: Redact by field name (only for scalar values)
                redacted_record[key] = f"[REDACTED:{key.upper()}]"
            elif isinstance(value, str):
                # Strategy 2: Scan string values for PII patterns
                redacted_record[key] = self._redact_pii_from_string(value)

        return redacted_record

    def _is_pii_field_name(self, field_name: str) -> bool:
        """
        Check if field name indicates PII content.

        Phase 5 (Security - B2-011): Field name-based PII detection

        Args:
            field_name: Field name to check

        Returns:
            True if field name matches known PII patterns
        """
        field_lower = field_name.lower()
        return any(pii_name in field_lower for pii_name in self.PII_FIELD_NAMES)

    def _redact_pii_from_string(self, text: str) -> str:
        """
        Redact PII patterns from string value.

        Phase 5 (Security - B2-011): Pattern-based PII detection

        Args:
            text: String to scan and redact

        Returns:
            String with PII patterns replaced with [REDACTED:TYPE]
        """
        redacted_text = text

        # Apply each PII pattern
        for pii_type, pattern in self.PII_PATTERNS.items():
            matches = pattern.findall(redacted_text)
            if matches:
                # Replace each match with redaction marker
                for match in matches:
                    # Handle tuple matches (phone regex returns groups)
                    match_str = match if isinstance(match, str) else "".join(match)
                    redacted_text = redacted_text.replace(
                        match_str, f"[REDACTED:{pii_type.upper()}]"
                    )

        return redacted_text

    async def _store_to_blob_storage(self, blob_name: str, data: str) -> None:
        """Store data to Azure Blob Storage"""
        if not self._blob_client:
            # Blob storage connection should be configured via constructor
            # Do not use os.getenv here - violates architecture security rules
            raise RuntimeError(
                "Azure Blob Storage client not configured. "
                "Pass blob storage connection string via constructor or disable blob storage for failed batches."
            )

        # Get or create container
        loop = asyncio.get_running_loop()
        container_client = self._blob_client.get_container_client(
            self.failed_batches_container
        )

        # Create container if it doesn't exist
        try:
            await loop.run_in_executor(
                self._executor, container_client.create_container
            )
        except Exception as e:
            # Container may already exist, continue
            logging.debug(
                f"Container '{self.failed_batches_container}' already exists or creation failed: {e}"
            )
            pass

        # Upload blob
        blob_client = container_client.get_blob_client(blob_name)
        await loop.run_in_executor(
            self._executor, blob_client.upload_blob, data, True  # overwrite
        )

    async def _store_to_local_file(self, filename: str, data: str) -> None:
        """Store data to local file system as fallback"""
        # Use instance attribute (set from config) instead of os.getenv
        failed_batches_dir = getattr(self, "failed_logs_path", "./failed_batches")

        # Create directory if it doesn't exist
        os.makedirs(failed_batches_dir, exist_ok=True)

        filepath = os.path.join(failed_batches_dir, filename)

        # Write to file asynchronously
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._executor, self._write_file, filepath, data)

    @staticmethod
    def _write_file(filepath: str, data: str) -> None:
        """Write data to file (sync helper for executor)"""
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(data)

    def _update_metrics(self, results: Dict[str, Any]) -> None:
        """Update internal metrics"""
        self.metrics["records_processed"] += results["processed"]
        self.metrics["failed_records"] += results["failed"]
        # Phase 4 (B2-005): Track batch count for failure rate calculation
        self.metrics["batch_count"] = self.metrics.get("batch_count", 0) + results.get(
            "batch_count", 0
        )
        self.metrics["last_ingestion_time"] = datetime.now(timezone.utc)

    def get_drop_metrics(self) -> Dict[str, Any]:
        """
        Get detailed metrics about dropped logs.

        Phase 4 (Observability - B1-008/OBS-03): Provides visibility into log dropping.

        Returns:
            Dict containing:
            - total_dropped: Total number of dropped logs
            - drop_rate: Percentage of logs dropped (if records_processed > 0)
            - drop_reasons: Breakdown of why logs were dropped
            - recommendations: Suggested actions to reduce drops
        """
        total_logs = self.metrics["records_processed"] + self.metrics["dropped_logs"]
        drop_rate = (
            (self.metrics["dropped_logs"] / total_logs * 100) if total_logs > 0 else 0.0
        )

        recommendations = []

        # Analyze drop reasons and provide actionable recommendations
        for reason, _count in self.metrics.get("drop_reasons", {}).items():
            if "missing_fields" in reason:
                recommendations.append(
                    f"Fix missing fields: {reason.split(':', 1)[1]}. "
                    f"Check log parser schema mapping."
                )
            elif "preparation_error" in reason:
                error_type = reason.split(":", 1)[1]
                recommendations.append(
                    f"Fix preparation errors ({error_type}). "
                    f"Check data type conversions and field mappings."
                )

        return {
            "total_dropped": self.metrics["dropped_logs"],
            "drop_rate_percent": round(drop_rate, 2),
            "drop_reasons": dict(self.metrics.get("drop_reasons", {})),
            "recommendations": recommendations,
            "total_processed": self.metrics["records_processed"],
            "total_failed": self.metrics["failed_records"],
        }

    def _categorize_batch_error(self, error: Exception) -> str:
        """
        Categorize batch failure errors for observability

        Phase 4 (B2-005/RES-05): Structured error categorization for trend analysis.

        Args:
            error: The exception that caused the batch failure

        Returns:
            Categorized error string (e.g., "azure_error:503", "network_timeout")
        """
        error_type = type(error).__name__

        # Azure-specific errors
        if isinstance(error, AzureError):
            # Extract status code if available
            status_code = getattr(error, "status_code", None)
            if status_code:
                return f"azure_error:{status_code}"
            return "azure_error:unknown"

        # Network/connection errors
        if "timeout" in error_type.lower() or "timeout" in str(error).lower():
            return "network_timeout"

        if "connection" in error_type.lower():
            return "network_connection"

        # Circuit breaker errors
        if isinstance(error, CircuitBreakerOpenError):
            return "circuit_breaker_open"

        # Validation errors
        if "validation" in error_type.lower() or isinstance(error, ValueError):
            return "validation_error"

        # Generic categorization
        return f"unknown_error:{error_type}"

    def _check_failure_rate_and_warn(self) -> None:
        """
        Check batch failure rate and warn if exceeding threshold

        Phase 4 (B2-005/RES-05): Proactive warnings for high failure rates.
        Warns every 10 failed batches to avoid log spam.
        """
        failed_batch_count = self.metrics["failed_batch_count"]

        # Warn every 10 failed batches
        if failed_batch_count > 0 and failed_batch_count % 10 == 0:
            total_batches = self.metrics.get("batch_count", 0)
            failure_rate = (
                (failed_batch_count / total_batches * 100) if total_batches > 0 else 0.0
            )

            # Get top failure reasons
            failure_reasons = self.metrics["failure_reasons"]
            top_reasons = sorted(
                failure_reasons.items(), key=lambda x: x[1], reverse=True
            )[
                :3
            ]  # Top 3 reasons

            reasons_str = ", ".join(
                f"{reason}: {count}" for reason, count in top_reasons
            )

            logging.warning(
                f"High batch failure rate detected: {failed_batch_count} batches failed "
                f"({failure_rate:.1f}% of total). Top reasons: {reasons_str}. "
                f"Check Azure Sentinel connectivity and error logs."
            )

    def get_failed_batch_metrics(self) -> Dict[str, Any]:
        """
        Get comprehensive failed batch metrics for observability

        Phase 4 (B2-005/RES-05): Provides visibility into batch failures.
        Similar to get_drop_metrics() but for batch-level failures.

        Returns:
            Dict containing:
            - total_failed_batches: Total number of failed batches
            - failure_rate: Percentage of batches that failed
            - failure_reasons: Breakdown of failure categories
            - recommendations: Suggested actions to reduce failures
            - total_failed_records: Total records in failed batches
        """
        total_batches = (
            self.metrics.get("batch_count", 0) + self.metrics["failed_batch_count"]
        )
        failure_rate = (
            (self.metrics["failed_batch_count"] / total_batches * 100)
            if total_batches > 0
            else 0.0
        )

        recommendations = []

        # Analyze failure reasons and provide actionable recommendations
        for reason, count in self.metrics.get("failure_reasons", {}).items():
            if "azure_error" in reason:
                status_code = reason.split(":", 1)[1] if ":" in reason else "unknown"
                recommendations.append(
                    f"Azure API errors ({status_code}): {count} occurrences. "
                    f"Check Azure Sentinel service health and DCR endpoint configuration."
                )
            elif "network" in reason:
                recommendations.append(
                    f"Network issues ({reason}): {count} occurrences. "
                    f"Check network connectivity and firewall rules."
                )
            elif "circuit_breaker_open" in reason:
                recommendations.append(
                    f"Circuit breaker protection triggered: {count} occurrences. "
                    f"Underlying service is experiencing issues - investigate root cause."
                )
            elif "validation_error" in reason:
                recommendations.append(
                    f"Validation errors: {count} occurrences. "
                    f"Check log schema compatibility with Sentinel table definitions."
                )

        return {
            "total_failed_batches": self.metrics["failed_batch_count"],
            "failure_rate_percent": round(failure_rate, 2),
            "failure_reasons": dict(self.metrics.get("failure_reasons", {})),
            "recommendations": recommendations,
            "total_failed_records": self.metrics["failed_records"],
            "total_batches_processed": total_batches,
        }

    def get_health_status(self) -> Dict[str, Any]:
        """
        Get router health status.

        Phase 4 (Observability - B1-008): Includes dropped log metrics in health check.
        Phase 4 (Resilience - B2-001): Includes circuit breaker state for monitoring.
        Phase 4 (Observability - B2-005): Includes failed batch metrics in health check.
        """
        # Phase 4 (B1-008): Consider drop rate in health status
        drop_metrics = self.get_drop_metrics()
        drop_rate = drop_metrics["drop_rate_percent"]

        # Phase 4 (B2-005): Consider batch failure rate in health status
        failed_batch_metrics = self.get_failed_batch_metrics()
        failure_rate = failed_batch_metrics["failure_rate_percent"]

        # Phase 4 (B2-001): Get circuit breaker status
        circuit_status = self._circuit_breaker.get_metrics()
        is_circuit_open = circuit_status["state"] == "open"

        # Determine health status with comprehensive checks
        if is_circuit_open:
            status = "degraded"  # Phase 4 (B2-001): Circuit open means degraded
        elif failure_rate > 5.0:  # Phase 4 (B2-005): >5% batch failure rate
            status = "degraded"
        elif drop_rate > 10.0:  # Phase 4 (B1-008): >10% drop rate
            status = "degraded"
        elif self.metrics["failed_records"] > 0:
            status = "degraded"
        else:
            status = "healthy"

        return {
            "status": status,
            "metrics": self.metrics,
            "drop_metrics": drop_metrics,  # Phase 4 (B1-008): Include drop metrics
            "failed_batch_metrics": failed_batch_metrics,  # Phase 4 (B2-005): Include batch failure metrics
            "circuit_breaker": {  # Phase 4 (B2-001): Circuit breaker metrics
                "state": circuit_status["state"],
                "failure_count": circuit_status["failure_count"],
                "total_calls": circuit_status["total_calls"],
                "opened_at": circuit_status["opened_at"],
            },
            "last_check": datetime.now(timezone.utc).isoformat(),
        }
