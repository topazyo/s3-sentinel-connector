#!/usr/bin/env python3
"""
S3 to Sentinel Data Connector - Azure Function
Ingests logs from AWS S3 into Microsoft Sentinel via Data Collection Rules (DCR)
"""

import gzip
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, cast

import azure.functions as func
import boto3
from azure.core.exceptions import AzureError
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
from azure.keyvault.secrets import SecretClient
from azure.monitor.ingestion import LogsIngestionClient
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class S3SentinelConnector:
    """Main connector class for S3 to Sentinel data ingestion"""

    def __init__(self):
        """Initialize the connector with configuration from environment variables"""
        # Load configuration
        self.key_vault_url = os.environ.get("KEY_VAULT_URL")
        self.aws_region = os.environ.get("AWS_REGION", "us-west-2")
        self.s3_bucket = os.environ.get("S3_BUCKET_NAME")
        self.s3_prefix = os.environ.get("S3_PREFIX", "logs/")
        self.batch_size = int(os.environ.get("BATCH_SIZE", "1000"))
        self.log_type = os.environ.get("LOG_TYPE", "firewall")
        self.dcr_endpoint = os.environ.get("DCR_ENDPOINT")
        self.dcr_rule_id = os.environ.get("DCR_RULE_ID")
        self.dcr_stream_name = os.environ.get("DCR_STREAM_NAME")

        # State tracking
        self.last_processed_key = None
        self._state_blob_name = "connector-state.json"

        # Initialize clients
        self._init_azure_clients()
        self._init_aws_clients()

        # Load table configuration
        self.table_configs = self._load_table_configs()

        # Metrics
        self.metrics = {
            "files_processed": 0,
            "records_ingested": 0,
            "bytes_processed": 0,
            "errors": 0,
        }

    def _init_azure_clients(self):
        """Initialize Azure clients with managed identity"""
        try:
            # Try managed identity first, fall back to default credential
            try:
                credential = ManagedIdentityCredential()
                # Test the credential
                credential.get_token("https://vault.azure.net/.default")
            except Exception:
                credential = DefaultAzureCredential()

            # Initialize Key Vault client
            if self.key_vault_url:
                self.kv_client = SecretClient(
                    vault_url=self.key_vault_url, credential=credential
                )
            else:
                self.kv_client = None
                logger.warning("Key Vault URL not configured")

            # Initialize Logs Ingestion client
            if not self.dcr_endpoint:
                raise ValueError("DCR_ENDPOINT environment variable is required")

            if not self.dcr_rule_id:
                raise ValueError("DCR_RULE_ID environment variable is required")

            if not self.dcr_stream_name:
                raise ValueError("DCR_STREAM_NAME environment variable is required")

            self.logs_client = LogsIngestionClient(
                endpoint=self.dcr_endpoint, credential=credential, logging_enable=True
            )

            logger.info("Azure clients initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize Azure clients: {e}")
            raise

    def _init_aws_clients(self):
        """Initialize AWS S3 client with credentials from Key Vault"""
        try:
            # Get credentials from Key Vault
            if self.kv_client:
                aws_access_key = self.kv_client.get_secret("aws-access-key-id").value
                aws_secret_key = self.kv_client.get_secret(
                    "aws-secret-access-key"
                ).value
            else:
                # Fall back to environment variables for local testing
                aws_access_key = os.environ.get("AWS_ACCESS_KEY_ID")
                aws_secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")

            # Initialize S3 client
            self.s3_client = boto3.client(
                "s3",
                aws_access_key_id=aws_access_key,
                aws_secret_access_key=aws_secret_key,
                region_name=self.aws_region,
                config=BotoConfig(
                    retries={"max_attempts": 3}, connect_timeout=10, read_timeout=30
                ),
            )

            logger.info(f"AWS S3 client initialized for region {self.aws_region}")

        except Exception as e:
            logger.error(f"Failed to initialize AWS clients: {e}")
            raise

    def _load_table_configs(self) -> Dict[str, Dict[str, Any]]:
        """Load table configuration for different log types"""
        return {
            "firewall": {
                "table_name": "Custom_Firewall_CL",
                "required_fields": [
                    "TimeGenerated",
                    "SourceIP",
                    "DestinationIP",
                    "Action",
                ],
                "transform_map": {
                    "src_ip": "SourceIP",
                    "dst_ip": "DestinationIP",
                    "action": "Action",
                    "proto": "Protocol",
                    "src_port": "SourcePort",
                    "dst_port": "DestinationPort",
                    "bytes": "BytesTransferred",
                    "rule": "RuleName",
                },
                "timestamp_formats": [
                    "%Y-%m-%dT%H:%M:%S.%fZ",
                    "%Y-%m-%dT%H:%M:%SZ",
                    "%Y-%m-%d %H:%M:%S",
                    "%b %d %Y %H:%M:%S",
                ],
            },
            "vpn": {
                "table_name": "Custom_VPN_CL",
                "required_fields": [
                    "TimeGenerated",
                    "UserPrincipalName",
                    "SessionID",
                    "ClientIP",
                ],
                "transform_map": {
                    "user": "UserPrincipalName",
                    "session": "SessionID",
                    "ip_address": "ClientIP",
                    "bytes_in": "BytesIn",
                    "bytes_out": "BytesOut",
                    "duration": "ConnectionDuration",
                },
                "timestamp_formats": [
                    "%Y-%m-%dT%H:%M:%S.%fZ",
                    "%Y-%m-%dT%H:%M:%SZ",
                    "%Y-%m-%d %H:%M:%S",
                ],
            },
        }

    def list_new_objects(
        self, last_modified_after: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """List S3 objects newer than the specified timestamp"""
        objects = []

        try:
            paginator = self.s3_client.get_paginator("list_objects_v2")
            page_iterator = paginator.paginate(
                Bucket=self.s3_bucket,
                Prefix=self.s3_prefix,
                PaginationConfig={"MaxItems": 1000},
            )

            for page in page_iterator:
                if "Contents" not in page:
                    continue

                for obj in page["Contents"]:
                    # Skip if older than last processed
                    if (
                        last_modified_after
                        and obj["LastModified"] <= last_modified_after
                    ):
                        continue

                    # Skip empty files and invalid extensions
                    if obj["Size"] == 0:
                        continue

                    key = obj["Key"]
                    if not self._is_valid_file(key):
                        continue

                    objects.append(
                        {
                            "Key": key,
                            "Size": obj["Size"],
                            "LastModified": obj["LastModified"],
                            "ETag": obj["ETag"],
                        }
                    )

            logger.info(
                f"Found {len(objects)} new objects in s3://{self.s3_bucket}/{self.s3_prefix}"
            )
            return objects

        except ClientError as e:
            logger.error(f"Failed to list S3 objects: {e}")
            self.metrics["errors"] += 1
            raise

    def _is_valid_file(self, key: str) -> bool:
        """Check if file should be processed based on extension and patterns"""
        valid_extensions = [".log", ".json", ".gz", ".csv", ".txt"]
        excluded_patterns = ["temp", "partial", "incomplete", "_tmp"]

        # Check extension
        if not any(key.lower().endswith(ext) for ext in valid_extensions):
            return False

        # Check for excluded patterns
        if any(pattern in key.lower() for pattern in excluded_patterns):
            return False

        return True

    def download_and_parse(self, obj: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Download an S3 object and parse its contents"""
        key = obj["Key"]

        try:
            # Download object
            response = self.s3_client.get_object(Bucket=self.s3_bucket, Key=key)
            content = response["Body"].read()

            # Decompress if needed
            if key.endswith(".gz"):
                content = gzip.decompress(content)

            # Decode
            text_content = content.decode("utf-8", errors="replace")

            # Parse based on file type
            if key.endswith(".json") or key.endswith(".json.gz"):
                records = self._parse_json(text_content)
            else:
                records = self._parse_delimited(text_content)

            self.metrics["files_processed"] += 1
            self.metrics["bytes_processed"] += obj["Size"]

            return records

        except ClientError as e:
            logger.error(f"Failed to download {key}: {e}")
            self.metrics["errors"] += 1
            return []
        except Exception as e:
            logger.error(f"Failed to parse {key}: {e}")
            self.metrics["errors"] += 1
            return []

    def _parse_json(self, content: str) -> List[Dict[str, Any]]:
        """Parse JSON log content"""
        records = []
        config = self.table_configs.get(self.log_type, {})
        transform_map = config.get("transform_map", {})

        try:
            # Try parsing as JSON array first
            data = json.loads(content)
            if isinstance(data, list):
                items = data
            else:
                items = [data]

            for item in items:
                record = self._transform_record(item, transform_map, config)
                if record:
                    records.append(record)

        except json.JSONDecodeError:
            # Try NDJSON (newline-delimited JSON)
            for line in content.strip().split("\n"):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                    record = self._transform_record(item, transform_map, config)
                    if record:
                        records.append(record)
                except json.JSONDecodeError:
                    continue

        return records

    def _parse_delimited(self, content: str) -> List[Dict[str, Any]]:
        """Parse pipe or comma-delimited log content"""
        records = []
        config = self.table_configs.get(self.log_type, {})
        transform_map = config.get("transform_map", {})

        lines = content.strip().split("\n")

        for line in lines:
            if not line.strip():
                continue

            # Detect delimiter
            if "|" in line:
                fields = line.split("|")
            elif "," in line:
                fields = line.split(",")
            else:
                fields = line.split()

            # Map fields based on position (assuming standard order)
            field_names = list(transform_map.keys())
            item = {}

            for i, value in enumerate(fields):
                if i < len(field_names):
                    item[field_names[i]] = value.strip()

            record = self._transform_record(item, transform_map, config)
            if record:
                records.append(record)

        return records

    def _transform_record(
        self,
        item: Dict[str, Any],
        transform_map: Dict[str, str],
        config: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Transform a source record to Sentinel schema"""
        record = {}

        # Apply field mappings
        for source, target in transform_map.items():
            if source in item:
                record[target] = item[source]

        # Copy fields that already match target names
        for key, value in item.items():
            if key not in transform_map:
                record.setdefault(key, value)

        # Ensure TimeGenerated exists
        if "TimeGenerated" not in record:
            # Try to find a timestamp field
            for ts_field in ["timestamp", "time", "datetime", "event_time"]:
                if ts_field in item:
                    record["TimeGenerated"] = self._parse_timestamp(
                        item[ts_field], config.get("timestamp_formats", [])
                    )
                    break
            else:
                # Use current time if no timestamp found
                record["TimeGenerated"] = datetime.now(timezone.utc).isoformat()

        # Validate required fields
        required = config.get("required_fields", [])
        for field in required:
            if field not in record or record[field] is None:
                return None

        # Add metadata
        record["SchemaVersion"] = "1.0"
        record["DataClassification"] = "standard"

        return record

    def _parse_timestamp(self, ts_str: str, formats: List[str]) -> str:
        """Parse timestamp string to ISO format"""
        if not ts_str:
            return datetime.now(timezone.utc).isoformat()

        for fmt in formats:
            try:
                dt = datetime.strptime(str(ts_str), fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.isoformat()
            except ValueError:
                continue

        # Return as-is if no format matches
        return str(ts_str)

    def ingest_to_sentinel(self, records: List[Dict[str, Any]]) -> int:
        """Ingest records to Sentinel via DCR"""
        if not records:
            return 0

        if not self.dcr_rule_id or not self.dcr_stream_name:
            raise ValueError(
                "DCR rule_id and stream_name must be configured for ingestion"
            )

        ingested = 0

        # Process in batches
        for i in range(0, len(records), self.batch_size):
            batch = records[i : i + self.batch_size]

            try:
                # Cast to List[Any] to satisfy the logs parameter type requirement
                self.logs_client.upload(
                    rule_id=self.dcr_rule_id,
                    stream_name=self.dcr_stream_name,
                    logs=cast(List[Any], batch),
                )

                ingested += len(batch)
                logger.info(f"Ingested batch of {len(batch)} records")

            except AzureError as e:
                logger.error(f"Failed to ingest batch: {e}")
                self.metrics["errors"] += 1
                # Store failed batch for retry
                self._store_failed_batch(batch, str(e))

        self.metrics["records_ingested"] += ingested
        return ingested

    def _store_failed_batch(self, batch: List[Dict[str, Any]], error: str):
        """Store failed batch for later retry"""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"failed_batch_{timestamp}.json"

        logger.warning(f"Storing failed batch: {filename} ({len(batch)} records)")
        # In production, this would write to blob storage for retry
        # For now, just log the failure

    def run(self) -> Dict[str, Any]:
        """Main execution method"""
        start_time = datetime.now(timezone.utc)

        try:
            # List new objects
            objects = self.list_new_objects()

            if not objects:
                logger.info("No new objects to process")
                return {
                    "status": "success",
                    "message": "No new objects",
                    "metrics": self.metrics,
                }

            # Process each object
            all_records = []
            for obj in objects:
                records = self.download_and_parse(obj)
                all_records.extend(records)

                # Ingest in chunks to avoid memory issues
                if len(all_records) >= self.batch_size * 5:
                    self.ingest_to_sentinel(all_records)
                    all_records = []

            # Ingest remaining records
            if all_records:
                self.ingest_to_sentinel(all_records)

            duration = (datetime.now(timezone.utc) - start_time).total_seconds()

            return {
                "status": "success",
                "duration_seconds": duration,
                "metrics": self.metrics,
            }

        except Exception as e:
            logger.exception(f"Connector run failed: {e}")
            return {"status": "error", "error": str(e), "metrics": self.metrics}


# Global connector instance (reused across invocations)
connector: Optional[S3SentinelConnector] = None


def main(timer: func.TimerRequest) -> None:
    """Azure Function entry point"""
    global connector

    utc_timestamp = datetime.now(timezone.utc).isoformat()

    if timer.past_due:
        logger.warning("Timer trigger is running late!")

    logger.info(f"S3 Sentinel Connector started at {utc_timestamp}")

    try:
        # Initialize connector on first run
        if connector is None:
            connector = S3SentinelConnector()

        # Execute the connector
        result = connector.run()

        logger.info(f"Connector completed: {json.dumps(result)}")

    except Exception as e:
        logger.exception(f"Connector failed: {e}")
        raise
