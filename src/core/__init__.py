# src/core/__init__.py

from typing import Dict, Any, Optional
import logging
import asyncio
from .s3_handler import S3Handler
from .log_parser import FirewallLogParser, JsonLogParser
from .sentinel_router import SentinelRouter

class CoreManager:
    """Central core functionality management class"""
    
    def __init__(self, 
                 config: Dict[str, Any],
                 security_manager: Any,
                 monitoring_manager: Any):
        """
        Initialize core components
        
        Args:
            config: Core configuration
            security_manager: Security manager instance
            monitoring_manager: Monitoring manager instance
        """
        self.config = config
        self.security_manager = security_manager
        self.monitoring_manager = monitoring_manager
        self.logger = logging.getLogger(__name__)
        
        # Initialize core components
        self._initialize_components()

    async def _initialize_components(self):
        """Initialize core components"""
        try:
            # Get AWS credentials
            aws_credentials = await self.security_manager.credential_manager.get_credential(
                'aws-credentials'
            )
            
            # Initialize S3 handler
            self.s3_handler = S3Handler(
                aws_access_key=aws_credentials['access_key'],
                aws_secret_key=aws_credentials['secret_key'],
                region=self.config['aws']['region']
            )
            
            # Initialize parsers
            self.parsers = {
                'firewall': FirewallLogParser(),
                'json': JsonLogParser()
            }
            
            # Initialize Sentinel router
            self.sentinel_router = SentinelRouter(
                dcr_endpoint=self.config['sentinel']['dcr_endpoint'],
                rule_id=self.config['sentinel']['rule_id'],
                stream_name=self.config['sentinel']['stream_name']
            )
            
            self.logger.info("Core components initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize core components: {str(e)}")
            raise

    async def process_logs(self, 
                         bucket: str,
                         prefix: str,
                         log_type: str) -> Dict[str, Any]:
        """
        Process logs from S3 and send to Sentinel
        
        Args:
            bucket: S3 bucket name
            prefix: S3 prefix
            log_type: Type of logs to process
            
        Returns:
            Processing results
        """
        try:
            # List objects
            objects = await self.s3_handler.list_objects(bucket, prefix)
            
            # Process in batches
            results = await self.s3_handler.process_files_batch(
                bucket,
                objects,
                callback=self._process_log_batch
            )
            
            # Record metrics
            await self.monitoring_manager.record_metric(
                'core',
                'logs_processed',
                len(objects)
            )
            
            return results
            
        except Exception as e:
            self.logger.error(f"Log processing failed: {str(e)}")
            raise

    async def _process_log_batch(self, 
                               batch: List[Dict[str, Any]],
                               log_type: str) -> None:
        """Process batch of logs"""
        try:
            # Get appropriate parser
            parser = self.parsers.get(log_type)
            if not parser:
                raise ValueError(f"Unsupported log type: {log_type}")
            
            # Parse logs
            parsed_logs = [
                parser.parse(log)
                for log in batch
            ]
            
            # Send to Sentinel
            await self.sentinel_router.route_logs(log_type, parsed_logs)
            
        except Exception as e:
            self.logger.error(f"Batch processing failed: {str(e)}")
            raise