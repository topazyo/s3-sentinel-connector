# src/core/s3_handler.py

import boto3
import logging
import gzip
import json
from botocore.exceptions import ClientError, ConnectionError
from typing import List, Dict, Optional, Union
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import wraps
import time

class RetryableError(Exception):
    """Custom exception for errors that should trigger a retry"""
    pass

def retry_with_backoff(retries=3, backoff_in_seconds=1):
    """Decorator for implementing exponential backoff"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for i in range(retries):
                try:
                    return func(*args, **kwargs)
                except RetryableError as e:
                    if i == retries - 1:  # Last retry
                        raise
                    wait_time = (backoff_in_seconds * 2 ** i) + random.uniform(0, 1)
                    logging.warning(f"Retrying {func.__name__} after {wait_time:.2f}s. Error: {str(e)}")
                    time.sleep(wait_time)
            return func(*args, **kwargs)
        return wrapper
    return decorator

class S3Handler:
    def __init__(self, 
                 aws_access_key: str, 
                 aws_secret_key: str, 
                 region: str,
                 max_retries: int = 3,
                 batch_size: int = 10,
                 max_threads: int = 5):
        """
        Initialize S3 handler with configuration and monitoring
        
        Args:
            aws_access_key: AWS access key
            aws_secret_key: AWS secret key
            region: AWS region
            max_retries: Maximum number of retry attempts
            batch_size: Number of files to process in each batch
            max_threads: Maximum number of concurrent threads
        """
        self.setup_logging()
        self.max_retries = max_retries
        self.batch_size = batch_size
        self.max_threads = max_threads
        self.metrics = {
            'files_processed': 0,
            'bytes_processed': 0,
            'errors': 0,
            'processing_time': 0
        }
        
        try:
            self.s3_client = boto3.client(
                's3',
                aws_access_key_id=aws_access_key,
                aws_secret_access_key=aws_secret_key,
                region_name=region,
                config=boto3.Config(
                    retries={'max_attempts': max_retries},
                    connect_timeout=5,
                    read_timeout=30
                )
            )
            logging.info(f"Successfully initialized S3 client in region {region}")
        except Exception as e:
            logging.critical(f"Failed to initialize S3 client: {str(e)}")
            raise

    def setup_logging(self) -> None:
        """Configure detailed logging with timestamps and log levels"""
        logging.basicConfig(
            format='%(asctime)s %(levelname)-8s [%(filename)s:%(lineno)d] %(message)s',
            level=logging.INFO,
            datefmt='%Y-%m-%d %H:%M:%S'
        )

    @retry_with_backoff(retries=3)
    def list_objects(self, 
                    bucket: str, 
                    prefix: str = "", 
                    last_processed_time: Optional[datetime] = None,
                    max_keys: int = 1000) -> List[Dict]:
        """
        List objects in S3 bucket with advanced filtering and pagination
        
        Args:
            bucket: S3 bucket name
            prefix: Object prefix for filtering
            last_processed_time: Only list objects modified after this time
            max_keys: Maximum number of keys to return
        
        Returns:
            List of object metadata dictionaries
        """
        objects = []
        paginator = self.s3_client.get_paginator('list_objects_v2')
        
        try:
            page_iterator = paginator.paginate(
                Bucket=bucket,
                Prefix=prefix,
                PaginationConfig={'MaxItems': max_keys}
            )
            
            for page in page_iterator:
                if 'Contents' not in page:
                    continue
                
                for obj in page['Contents']:
                    # Apply filters
                    if last_processed_time and obj['LastModified'] <= last_processed_time:
                        continue
                    
                    # Filter out empty files and unwanted extensions
                    if obj['Size'] == 0 or not self._is_valid_file(obj['Key']):
                        continue
                    
                    objects.append({
                        'Key': obj['Key'],
                        'Size': obj['Size'],
                        'LastModified': obj['LastModified'],
                        'ETag': obj['ETag'],
                        'StorageClass': obj.get('StorageClass', 'STANDARD')
                    })
            
            logging.info(f"Found {len(objects)} new objects in {bucket}/{prefix}")
            return objects
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_msg = self._get_error_message(error_code)
            logging.error(f"S3 list operation failed: {error_msg}")
            if error_code in ['SlowDown', 'InternalError']:
                raise RetryableError(f"Temporary S3 issue: {error_msg}")
            raise
        except Exception as e:
            logging.error(f"Unexpected error during list operation: {str(e)}")
            raise

    def _is_valid_file(self, key: str) -> bool:
        """Check if file should be processed based on extension and patterns"""
        valid_extensions = ['.log', '.json', '.gz', '.csv']
        excluded_patterns = ['temp', 'partial', 'incomplete']
        
        # Check file extension
        if not any(key.endswith(ext) for ext in valid_extensions):
            return False
            
        # Check for excluded patterns
        if any(pattern in key.lower() for pattern in excluded_patterns):
            return False
            
        return True

    def process_files_batch(self, 
                          bucket: str, 
                          objects: List[Dict],
                          callback: Optional[callable] = None) -> Dict:
        """
        Process multiple files in parallel with advanced error handling
        
        Args:
            bucket: S3 bucket name
            objects: List of object metadata
            callback: Optional callback function for processed data
            
        Returns:
            Dict containing processing metrics and results
        """
        results = {
            'successful': [],
            'failed': [],
            'metrics': {
                'total_files': len(objects),
                'total_bytes': sum(obj['Size'] for obj in objects),
                'start_time': datetime.utcnow()
            }
        }
        
        with ThreadPoolExecutor(max_workers=self.max_threads) as executor:
            future_to_obj = {
                executor.submit(self._process_single_file, bucket, obj, callback): obj
                for obj in objects
            }
            
            for future in as_completed(future_to_obj):
                obj = future_to_obj[future]
                try:
                    data = future.result()
                    results['successful'].append({
                        'key': obj['Key'],
                        'size': obj['Size'],
                        'processed_at': datetime.utcnow()
                    })
                except Exception as e:
                    logging.error(f"Failed to process {obj['Key']}: {str(e)}")
                    results['failed'].append({
                        'key': obj['Key'],
                        'error': str(e),
                        'time': datetime.utcnow()
                    })
        
        # Update metrics
        results['metrics']['end_time'] = datetime.utcnow()
        results['metrics']['duration'] = (
            results['metrics']['end_time'] - results['metrics']['start_time']
        ).total_seconds()
        results['metrics']['success_rate'] = len(results['successful']) / len(objects)
        
        self._log_batch_results(results)
        return results

    def _process_single_file(self, 
                           bucket: str, 
                           obj: Dict,
                           callback: Optional[callable]) -> bytes:
        """Process a single S3 file with decompression and validation"""
        try:
            content = self.download_object(bucket, obj['Key'])
            
            # Validate content
            if not self._validate_content(content, obj['Key']):
                raise ValueError("Content validation failed")
            
            # Process content if callback provided
            if callback:
                content = callback(content)
            
            return content
            
        except Exception as e:
            logging.error(f"Error processing {obj['Key']}: {str(e)}")
            raise