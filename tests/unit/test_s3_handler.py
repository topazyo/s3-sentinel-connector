# tests/test_s3_handler.py

import pytest
from datetime import datetime, timedelta
from src.core.s3_handler import S3Handler, RetryableError
from botocore.exceptions import ClientError
import json

class TestS3Handler:
    def test_list_objects(self, s3_handler, mock_s3_bucket):
        """Test listing objects from S3"""
        objects = s3_handler.list_objects(mock_s3_bucket, prefix="logs/firewall")
        
        assert len(objects) == 2
        assert all(obj['Key'].startswith('logs/firewall') for obj in objects)

    def test_list_objects_with_time_filter(self, s3_handler, mock_s3_bucket):
        """Test listing objects with time filter"""
        cutoff_time = datetime.utcnow() - timedelta(hours=1)
        objects = s3_handler.list_objects(
            mock_s3_bucket,
            prefix="logs/firewall",
            last_processed_time=cutoff_time
        )
        
        assert len(objects) > 0
        assert all(obj['LastModified'] > cutoff_time for obj in objects)

    def test_download_object(self, s3_handler, mock_s3_bucket):
        """Test downloading object from S3"""
        key = "logs/firewall/2024/02/20/log1.json"
        content = s3_handler.download_object(mock_s3_bucket, key)
        
        assert content is not None
        parsed_content = json.loads(content)
        assert parsed_content['src_ip'] == "192.168.1.1"

    def test_download_object_compressed(self, s3_handler, mock_s3_bucket):
        """Test downloading and decompressing gzipped object"""
        import gzip
        
        # Upload compressed test file
        s3 = boto3.client('s3')
        test_content = b'{"test": "data"}'
        compressed_content = gzip.compress(test_content)
        key = "logs/compressed/test.json.gz"
        
        s3.put_object(
            Bucket=mock_s3_bucket,
            Key=key,
            Body=compressed_content
        )
        
        # Download and verify
        content = s3_handler.download_object(mock_s3_bucket, key)
        assert content == test_content

    def test_process_files_batch(self, s3_handler, mock_s3_bucket):
        """Test batch processing of files"""
        objects = s3_handler.list_objects(mock_s3_bucket, prefix="logs/firewall")
        results = s3_handler.process_files_batch(mock_s3_bucket, objects, batch_size=2)
        
        assert results['processed'] == 2
        assert results['failed'] == 0

    @pytest.mark.parametrize("error_code,should_retry", [
        ("SlowDown", True),
        ("NoSuchBucket", False),
        ("AccessDenied", False)
    ])
    def test_error_handling(self, s3_handler, error_code, should_retry):
        """Test error handling for different scenarios"""
        error_response = {
            'Error': {
                'Code': error_code,
                'Message': 'Test error'
            }
        }
        
        if should_retry:
            with pytest.raises(RetryableError):
                s3_handler._handle_aws_error(
                    ClientError(error_response, 'test_operation')
                )
        else:
            with pytest.raises(ClientError):
                s3_handler._handle_aws_error(
                    ClientError(error_response, 'test_operation')
                )

    def test_validate_content(self, s3_handler):
        """Test content validation"""
        valid_content = b'{"valid": "json"}'
        invalid_content = b'invalid json'
        
        assert s3_handler._validate_content(valid_content, "test.json")
        assert not s3_handler._validate_content(invalid_content, "test.json")