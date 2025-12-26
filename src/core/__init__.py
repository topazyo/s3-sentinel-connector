# src/core/__init__.py

from typing import Dict, Any, Optional, List
import logging
import asyncio
from .s3_handler import S3Handler
from .log_parser import FirewallLogParser, JsonLogParser
from .sentinel_router import SentinelRouter

__all__ = [
    'CoreManager',
    'S3Handler',
    'FirewallLogParser',
    'JsonLogParser',
    'SentinelRouter'
]

class CoreManager:
    """Central core functionality management class"""
    
    def __init__(self, 
                 config: Dict[str, Any],
                 security_manager: Any,
                 monitoring_manager: Any) -> None:
        """
        Initialize core components.
        
        NOTE: Components are not fully initialized yet. Call the create()
        factory method or await initialize() to complete setup.
        
        Args:
            config: Core configuration
            security_manager: Security manager instance
            monitoring_manager: Monitoring manager instance
        """
        self.config = config
        self.security_manager = security_manager
        self.monitoring_manager = monitoring_manager
        self.logger = logging.getLogger(__name__)
        
        # Components set to None initially, initialized via async method
        self.s3_handler: Optional[S3Handler] = None
        self.sentinel_router: Optional[SentinelRouter] = None
        self.parsers: Dict[str, Any] = {}
        self._initialized = False
    
    @classmethod
    async def create(cls,
                    config: Dict[str, Any],
                    security_manager: Any,
                    monitoring_manager: Any) -> 'CoreManager':
        """
        Factory method to create and initialize CoreManager asynchronously.
        
        Args:
            config: Core configuration
            security_manager: Security manager instance
            monitoring_manager: Monitoring manager instance
            
        Returns:
            Fully initialized CoreManager instance
        """
        instance = cls(config, security_manager, monitoring_manager)
        await instance.initialize()
        return instance
    
    async def initialize(self) -> None:
        """Initialize core components asynchronously"""
        if self._initialized:
            self.logger.warning("CoreManager already initialized")
            return
            
        await self._initialize_components()
        self._initialized = True

    async def _initialize_components(self) -> None:
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
            
        Raises:
            RuntimeError: If CoreManager not initialized
        """
        if not self._initialized:
            raise RuntimeError(
                "CoreManager not initialized. Call await initialize() or use "
                "await CoreManager.create() factory method."
            )
            
        try:
            parser = self.parsers.get(log_type)
            if not parser:
                raise ValueError(f"Unsupported log type: {log_type}")

            # List objects - use async variant
            objects = await self.s3_handler.list_objects_async(bucket, prefix)
            
            # Process in batches - use async variant
            results = await self.s3_handler.process_files_batch_async(
                bucket,
                objects,
                parser=parser,
                callback=self._process_log_batch,
                log_type=log_type
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
                               parsed_batch: List[Dict[str, Any]],
                               log_type: str) -> None:
        """Route an already-parsed batch to Sentinel."""
        try:
            await self.sentinel_router.route_logs(log_type, parsed_batch)
        except Exception as e:
            self.logger.error(f"Batch processing failed: {str(e)}")
            raise