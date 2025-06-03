# src/core/s3_handler.py

import boto3
import logging
import gzip
import json
from botocore.exceptions import ClientError, ConnectionError # ClientError is already here
from typing import List, Dict, Optional, Union, Any
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import wraps
import time
import random # Added import

class RetryableError(Exception):
    """Custom exception for errors that should trigger a retry"""
    pass

def retry_with_backoff(retries=3, backoff_in_seconds=1):
    """Decorator for implementing exponential backoff"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Add self to args if it's a method
            actual_args = args
            if args and hasattr(args[0], func.__name__): # Crude check if first arg is 'self' or 'cls'
                pass # self is already part of args

            for i in range(retries):
                try:
                    return func(*actual_args, **kwargs)
                except RetryableError as e:
                    if i == retries - 1:  # Last retry
                        raise
                    # Use actual_args[0].logger if available and it's an instance method, else global logging
                    logger_instance = actual_args[0].logger if args and hasattr(args[0], 'logger') else logging
                    wait_time = (backoff_in_seconds * 2 ** i) + random.uniform(0, 1)
                    logger_instance.warning(f"Retrying {func.__name__} after {wait_time:.2f}s. Error: {str(e)}")
                    time.sleep(wait_time)
            return func(*actual_args, **kwargs) # Ensure it's called correctly on final attempt
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
        self.logger = logging.getLogger(__name__) # Initialize logger first
        self.setup_logging() # Call setup_logging
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
            self.logger.info(f"Successfully initialized S3 client in region {region}")
        except Exception as e:
            self.logger.critical(f"Failed to initialize S3 client: {str(e)}")
            raise

    def setup_logging(self) -> None:
        if not self.logger.handlers: # Avoid adding multiple handlers if already configured
            logging.basicConfig( # This will configure the root logger if not already done.
                format='%(asctime)s %(levelname)-8s [%(filename)s:%(lineno)d] %(message)s',
                level=logging.INFO, # Consider making this configurable
                datefmt='%Y-%m-%d %H:%M:%S'
            )

    def _get_error_message(self, error_code: str) -> str:
        # Provide a more user-friendly message for common S3 error codes.
        messages = {
            "NoSuchKey": "The specified key does not exist.",
            "AccessDenied": "Access to the S3 resource was denied. Check permissions.",
            "InvalidBucketName": "The specified bucket name is not valid.",
            "BucketAlreadyOwnedByYou": "The bucket you tried to create is already owned by you.",
            "NoSuchBucket": "The specified bucket does not exist.",
            "SlowDown": "S3 is temporarily busy. Please retry.",
            "InternalError": "S3 encountered an internal error. Please retry."
            # Add more specific S3 error codes and messages as needed
        }
        return messages.get(error_code, f"An S3 error occurred: {error_code}")

    @retry_with_backoff(retries=3)
    def list_objects(self, 
                    bucket: str, 
                    prefix: str = "", 
                    last_processed_time: Optional[datetime] = None,
                    max_keys: int = 1000) -> List[Dict]:
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
                    if last_processed_time and obj['LastModified'] <= last_processed_time:
                        continue
                    if obj['Size'] == 0 or not self._is_valid_file(obj['Key']):
                        continue
                    objects.append({
                        'Key': obj['Key'],
                        'Size': obj['Size'],
                        'LastModified': obj['LastModified'],
                        'ETag': obj['ETag'],
                        'StorageClass': obj.get('StorageClass', 'STANDARD')
                    })
            
            self.logger.info(f"Found {len(objects)} new objects in {bucket}/{prefix}")
            return objects
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'UnknownS3ErrorInList')
            error_msg = self._get_error_message(error_code)
            self.logger.error(f"S3 list operation failed for {bucket}/{prefix}: {error_msg} (Details: {str(e)})")
            if error_code in ['SlowDown', 'InternalError']: # Retryable AWS errors
                raise RetryableError(f"Temporary S3 issue during list: {error_msg}")
            raise # Non-retryable ClientError
        except Exception as e: # Catch other potential errors
            self.logger.error(f"Unexpected error during list operation for {bucket}/{prefix}: {str(e)}")
            raise RetryableError(f"Unexpected error, potentially retryable: {str(e)}") # Assume retryable for unexpected

    def _is_valid_file(self, key: str) -> bool:
        valid_extensions = ['.log', '.json', '.gz', '.csv']
        excluded_patterns = ['temp', 'partial', 'incomplete']
        if not any(key.endswith(ext) for ext in valid_extensions):
            return False
        if any(pattern in key.lower() for pattern in excluded_patterns):
            return False
        return True

    def download_object(self, bucket: str, key: str) -> bytes:
        self.logger.info(f"Attempting to download s3://{bucket}/{key}")
        # In a real scenario, this would use self.s3_client.get_object
        # For testing error handling, one might add:
        # from botocore.exceptions import ClientError # Ensure imported at top of file
        # if "cause_error_NoSuchKey" in key:
        #     raise ClientError({"Error": {"Code": "NoSuchKey", "Message": "Simulated NoSuchKey Error"}}, "GetObject")
        # if "cause_error_AccessDenied" in key:
        #     raise ClientError({"Error": {"Code": "AccessDenied", "Message": "Simulated AccessDenied Error"}}, "GetObject")
        
        # Actual S3 download logic:
        try:
            response = self.s3_client.get_object(Bucket=bucket, Key=key)
            content = response['Body'].read()
            if key.endswith(".gz"):
                return gzip.decompress(content)
            return content
        except ClientError as e: # Propagate ClientError to be handled by _process_single_file
            self.logger.warning(f"S3 ClientError during download of {key}: {e.response.get('Error', {}).get('Code', 'Unknown')}")
            raise
        except Exception as e: # Catch other potential errors during download or decompression
            self.logger.error(f"Unexpected error during download or decompression of {key}: {str(e)}")
            # Wrap non-ClientError exceptions in a generic RetryableError or specific custom error
            # if appropriate, or let it be caught by _process_single_file's generic Exception handler.
            raise RetryableError(f"Download/decompression failed for {key}: {str(e)}")


    def _validate_content(self, content: bytes, file_key: str) -> bool:
        # Placeholder for content validation logic
        self.logger.debug(f"Validating content for {file_key} (length: {len(content)} bytes)")
        if content is None or len(content) == 0: # Basic check
            self.logger.warning(f"Content for {file_key} is empty or None.")
            # Depending on requirements, empty content might be invalid
            # return False 
        return True # Default to true for placeholder

    def _process_single_file(self, 
                           bucket: str, 
                           obj: Dict, # obj is a dictionary like {'Key': 'path/to/file.log.gz', ...}
                           callback: Optional[callable]) -> Optional[Any]: # Callback might return processed data or None
        file_key = obj['Key']
        try:
            content = self.download_object(bucket, file_key) 
            
            if not self._validate_content(content, file_key): 
                # _validate_content should ideally raise ValueError or specific validation error
                raise ValueError("Content validation failed") 
            
            if callback:
                processed_data = callback(content, file_key) # Pass file_key to callback
                return processed_data # Return what the callback returns
            
            return content # Return raw content if no callback
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'UnknownS3Error')
            error_message = self._get_error_message(error_code) 
            self.logger.error(f"S3 ClientError processing {file_key}: {error_message} (Details: {str(e)})")
            # Decide if this specific ClientError is retryable for the whole process_single_file operation
            if error_code in ["SlowDown", "InternalError", "Throttling", "ServiceUnavailable"]: # Example retryable S3 errors
                 raise RetryableError(f"Retryable S3 ClientError for {file_key}: {error_message}")
            raise # Re-raise other ClientErrors to be caught by process_files_batch
            
        except ValueError as ve: 
            self.logger.error(f"Validation error for {file_key}: {str(ve)}")
            raise # Re-raise to be caught by process_files_batch
            
        except Exception as e: 
            self.logger.error(f"Unexpected error processing {file_key}: {str(e)}")
            # Consider if this should be a RetryableError or not
            raise RetryableError(f"Unexpected, potentially retryable error for {file_key}: {str(e)}")


    def _log_batch_results(self, results: Dict) -> None:
        # Placeholder for logging batch processing results
        self.logger.info(f"Batch processing completed. Duration: {results['metrics']['duration']:.2f}s. "
                         f"Successful: {len(results['successful'])}/{results['metrics']['total_files']}. "
                         f"Failed: {len(results['failed'])}/{results['metrics']['total_files']}. "
                         f"Success Rate: {results['metrics']['success_rate']:.2%}.")
        if results['failed']:
            failed_keys = [item['key'] for item in results['failed']]
            self.logger.warning(f"Failed keys: {', '.join(failed_keys[:5])}{'...' if len(failed_keys) > 5 else ''}")


    def process_files_batch(self, 
                          bucket: str, 
                          objects: List[Dict],
                          callback: Optional[callable] = None) -> Dict:
        results = {
            'successful': [],
            'failed': [],
            'metrics': {
                'total_files': len(objects),
                'total_bytes': sum(obj.get('Size', 0) for obj in objects), # Handle if Size is missing
                'start_time': datetime.utcnow(),
                'end_time': None,
                'duration': 0,
                'success_rate': 0
            }
        }
        
        if not objects:
            self.logger.info("No objects to process in this batch.")
            results['metrics']['end_time'] = datetime.utcnow()
            self._log_batch_results(results)
            return results

        with ThreadPoolExecutor(max_workers=self.max_threads) as executor:
            future_to_obj = {
                executor.submit(self._process_single_file, bucket, obj, callback): obj
                for obj in objects
            }
            
            for future in as_completed(future_to_obj):
                obj = future_to_obj[future]
                file_key = obj['Key'] # Get key for logging
                try:
                    # result_data could be the processed_data from callback or raw content
                    result_data = future.result() 
                    results['successful'].append({
                        'key': file_key,
                        'size': obj.get('Size', 0),
                        'processed_at': datetime.utcnow(),
                        # 'data_preview': result_data[:100] if result_data else None # Optional: if you want to see some output
                    })
                    self.metrics['files_processed'] += 1
                    self.metrics['bytes_processed'] += obj.get('Size', 0)
                except Exception as e:
                    self.logger.warning(f"Failed to process file {file_key} after retries: {str(e)}")
                    results['failed'].append({
                        'key': file_key,
                        'error': str(e),
                        'time': datetime.utcnow()
                    })
                    self.metrics['errors'] += 1
        
        results['metrics']['end_time'] = datetime.utcnow()
        results['metrics']['duration'] = (
            results['metrics']['end_time'] - results['metrics']['start_time']
        ).total_seconds()
        
        if results['metrics']['total_files'] > 0:
            results['metrics']['success_rate'] = len(results['successful']) / results['metrics']['total_files']
        
        self.metrics['processing_time'] += results['metrics']['duration']
        self._log_batch_results(results)
        return results