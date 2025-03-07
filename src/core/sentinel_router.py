# src/core/sentinel_router.py

import json
import logging
import hashlib
from typing import Dict, List, Any, Optional, Union
from datetime import datetime, timedelta
from azure.monitor.ingestion import LogsIngestionClient
from azure.identity import DefaultAzureCredential
from azure.core.exceptions import AzureError
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
import asyncio

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
    def __init__(self, 
                 dcr_endpoint: str,
                 rule_id: str,
                 stream_name: str,
                 max_retries: int = 3,
                 batch_timeout: int = 30):
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
        
        # Initialize Azure clients
        self._initialize_azure_clients()
        
        # Load table configurations
        self.table_configs = self._load_table_configs()
        
        # Initialize metrics
        self.metrics = {
            'records_processed': 0,
            'bytes_ingested': 0,
            'failed_records': 0,
            'last_ingestion_time': None
        }

    def _initialize_azure_clients(self):
        """Initialize Azure clients with error handling"""
        try:
            credential = DefaultAzureCredential()
            self.logs_client = LogsIngestionClient(
                endpoint=self.dcr_endpoint,
                credential=credential,
                logging_enable=True
            )
            logging.info("Successfully initialized Azure clients")
        except Exception as e:
            logging.critical(f"Failed to initialize Azure clients: {str(e)}")
            raise

    def _load_table_configs(self) -> Dict[str, TableConfig]:
        """Load and validate table configurations"""
        # This could be loaded from a configuration file
        return {
            'firewall': TableConfig(
                table_name='Custom_Firewall_CL',
                schema_version='1.0',
                required_fields=['TimeGenerated', 'SourceIP', 'DestinationIP', 'Action'],
                retention_days=90,
                transform_map={
                    'src_ip': 'SourceIP',
                    'dst_ip': 'DestinationIP',
                    'action': 'Action',
                },
                data_type_map={
                    'TimeGenerated': 'datetime',
                    'SourceIP': 'string',
                    'DestinationIP': 'string',
                    'BytesTransferred': 'long'
                }
            ),
            'vpn': TableConfig(
                table_name='Custom_VPN_CL',
                schema_version='2.1',
                required_fields=['TimeGenerated', 'UserPrincipalName', 'SessionID'],
                retention_days=30,
                transform_map={
                    'user': 'UserPrincipalName',
                    'session': 'SessionID',
                    'ip_address': 'ClientIP'
                },
                data_type_map={
                    'TimeGenerated': 'datetime',
                    'SessionID': 'string',
                    'BytesIn': 'long',
                    'BytesOut': 'long'
                }
            )
        }

    async def route_logs(self, 
                        log_type: str, 
                        logs: List[Dict[str, Any]],
                        data_classification: str = 'standard') -> Dict[str, Any]:
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
            return {'status': 'skip', 'message': 'No logs to process'}

        table_config = self.table_configs.get(log_type)
        if not table_config:
            raise ValueError(f"Unsupported log type: {log_type}")

        results = {
            'processed': 0,
            'failed': 0,
            'batch_count': 0,
            'start_time': datetime.utcnow()
        }

        try:
            # Prepare logs for ingestion
            prepared_logs = [
                self._prepare_log_entry(log, table_config, data_classification)
                for log in logs
            ]
            
            # Filter out None values (failed preparations)
            prepared_logs = [log for log in prepared_logs if log is not None]
            
            # Process in batches
            batches = self._create_batches(prepared_logs, table_config.batch_size)
            
            async with asyncio.TaskGroup() as group:
                for batch in batches:
                    group.create_task(
                        self._ingest_batch(batch, table_config, results)
                    )

            self._update_metrics(results)
            return results

        except Exception as e:
            logging.error(f"Error routing logs: {str(e)}")
            raise

    def _prepare_log_entry(self, 
                          log: Dict[str, Any], 
                          table_config: TableConfig,
                          data_classification: str) -> Optional[Dict[str, Any]]:
        """Prepare a single log entry for ingestion"""
        try:
            # Transform fields according to mapping
            transformed_log = {}
            for source, target in table_config.transform_map.items():
                if source in log:
                    transformed_log[target] = log[source]

            # Add required fields if missing
            if 'TimeGenerated' not in transformed_log:
                transformed_log['TimeGenerated'] = datetime.utcnow().isoformat()

            # Add metadata
            transformed_log['DataClassification'] = data_classification
            transformed_log['SchemaVersion'] = table_config.schema_version
            
            # Validate data types
            for field, expected_type in table_config.data_type_map.items():
                if field in transformed_log:
                    transformed_log[field] = self._convert_data_type(
                        transformed_log[field], 
                        expected_type
                    )

            # Validate required fields
            if not all(field in transformed_log for field in table_config.required_fields):
                logging.warning(f"Missing required fields in log entry: {log}")
                return None

            return transformed_log

        except Exception as e:
            logging.error(f"Error preparing log entry: {str(e)}")
            return None

    async def _ingest_batch(self,
                           batch: List[Dict[str, Any]],
                           table_config: TableConfig,
                           results: Dict[str, Any]) -> None:
        """Ingest a batch of logs to Sentinel"""
        try:
            body = json.dumps(batch)
            
            if table_config.compression_enabled:
                body = self._compress_data(body)

            await self.logs_client.upload(
                rule_id=self.rule_id,
                stream_name=self.stream_name,
                body=body,
                content_type="application/json"
            )

            results['processed'] += len(batch)
            results['batch_count'] += 1
            
        except AzureError as e:
            logging.error(f"Azure ingestion error: {str(e)}")
            results['failed'] += len(batch)
            # Store failed batch for retry if needed
            await self._handle_failed_batch(batch, e)
        except Exception as e:
            logging.error(f"Unexpected error during batch ingestion: {str(e)}")
            results['failed'] += len(batch)

    @staticmethod
    def _create_batches(logs: List[Dict[str, Any]], 
                       batch_size: int) -> List[List[Dict[str, Any]]]:
        """Create batches of logs for processing"""
        return [logs[i:i + batch_size] for i in range(0, len(logs), batch_size)]

    @staticmethod
    def _convert_data_type(value: Any, target_type: str) -> Any:
        """Convert value to target data type"""
        type_converters = {
            'datetime': lambda x: x.isoformat() if isinstance(x, datetime) else x,
            'long': int,
            'double': float,
            'boolean': bool,
            'string': str
        }
        
        converter = type_converters.get(target_type)
        if not converter:
            raise ValueError(f"Unsupported data type: {target_type}")
            
        try:
            return converter(value)
        except (ValueError, TypeError) as e:
            raise ValueError(f"Data type conversion failed: {str(e)}")

    @staticmethod
    def _compress_data(data: str) -> bytes:
        """Compress data for transmission"""
        import gzip
        return gzip.compress(data.encode('utf-8'))

    async def _handle_failed_batch(self, 
                                 batch: List[Dict[str, Any]], 
                                 error: Exception) -> None:
        """Handle failed batch processing"""
        batch_id = hashlib.md5(str(batch).encode()).hexdigest()
        
        # Store failed batch for retry
        failed_batch_info = {
            'batch_id': batch_id,
            'timestamp': datetime.utcnow().isoformat(),
            'error': str(error),
            'retry_count': 0,
            'data': batch
        }
        
        # Could be stored in Azure Storage or other persistent storage
        await self._store_failed_batch(failed_batch_info)
        
        logging.error(f"Batch {batch_id} failed: {str(error)}")

    async def _store_failed_batch(self, failed_batch_info: Dict[str, Any]) -> None:
        """Store failed batch for later retry"""
        # Implementation would depend on your storage solution
        # Example: Azure Blob Storage
        pass

    def _update_metrics(self, results: Dict[str, Any]) -> None:
        """Update internal metrics"""
        self.metrics['records_processed'] += results['processed']
        self.metrics['failed_records'] += results['failed']
        self.metrics['last_ingestion_time'] = datetime.utcnow()

    async def get_health_status(self) -> Dict[str, Any]:
        """Get router health status"""
        return {
            'status': 'healthy' if self.metrics['failed_records'] == 0 else 'degraded',
            'metrics': self.metrics,
            'last_check': datetime.utcnow().isoformat()
        }