# tests/conftest.py

import pytest
import boto3
import os
from unittest.mock import MagicMock
from moto import mock_s3
from azure.identity import DefaultAzureCredential
from src.core.s3_handler import S3Handler
from src.core.log_parser import FirewallLogParser, JsonLogParser
from src.core.sentinel_router import SentinelRouter
from src.config.config_manager import ConfigManager

@pytest.fixture
def mock_aws_credentials():
    """Mocked AWS Credentials for testing"""
    os.environ['AWS_ACCESS_KEY_ID'] = 'testing'
    os.environ['AWS_SECRET_ACCESS_KEY'] = 'testing'
    os.environ['AWS_SECURITY_TOKEN'] = 'testing'
    os.environ['AWS_SESSION_TOKEN'] = 'testing'

@pytest.fixture
def mock_s3_bucket(mock_aws_credentials):
    """Create mock S3 bucket with test data"""
    with mock_s3():
        s3 = boto3.client('s3')
        bucket_name = 'test-bucket'
        s3.create_bucket(Bucket=bucket_name)
        
        # Add test log files
        test_logs = [
            ('logs/firewall/2024/02/20/log1.json', b'{"src_ip": "192.168.1.1", "dst_ip": "10.0.0.1", "action": "allow"}'),
            ('logs/firewall/2024/02/20/log2.json', b'{"src_ip": "192.168.1.2", "dst_ip": "10.0.0.2", "action": "deny"}')
        ]
        
        for key, content in test_logs:
            s3.put_object(Bucket=bucket_name, Key=key, Body=content)
            
        yield bucket_name

@pytest.fixture
def mock_azure_credential():
    """Mock Azure credential"""
    return MagicMock(spec=DefaultAzureCredential)

@pytest.fixture
def config_manager():
    """Test configuration manager"""
    return ConfigManager(
        config_path="tests/config",
        environment="test",
        vault_url=None,
        enable_hot_reload=False
    )

@pytest.fixture
def s3_handler(mock_aws_credentials):
    """Test S3 handler instance"""
    return S3Handler(
        aws_access_key='testing',
        aws_secret_key='testing',
        region='us-east-1'
    )

@pytest.fixture
def firewall_parser():
    """Test firewall log parser instance"""
    return FirewallLogParser()

@pytest.fixture
def sentinel_router(mock_azure_credential):
    """Test Sentinel router instance"""
    return SentinelRouter(
        dcr_endpoint="https://test-endpoint",
        rule_id="test-rule",
        stream_name="test-stream"
    )