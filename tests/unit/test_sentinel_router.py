# tests/test_sentinel_router.py

import pytest
import json
from datetime import datetime
from src.core.sentinel_router import SentinelRouter, TableConfig
from azure.core.exceptions import AzureError

class TestSentinelRouter:
    @pytest.fixture
    def sample_logs(self):
        return [
            {
                'TimeGenerated': datetime.utcnow(),
                'SourceIP': '192.168.1.1',
                'DestinationIP': '10.0.0.1',
                'Action': 'allow'
            },
            {
                'TimeGenerated': datetime.utcnow(),
                'SourceIP': '192.168.1.2',
                'DestinationIP': '10.0.0.2',
                'Action': 'deny'
            }
        ]

    @pytest.fixture
    def table_config(self):
        return TableConfig(
            table_name='Custom_Firewall_CL',
            schema_version='1.0',
            required_fields=['TimeGenerated', 'SourceIP', 'DestinationIP', 'Action'],
            retention_days=90,
            transform_map={
                'src_ip': 'SourceIP',
                'dst_ip': 'DestinationIP',
                'action': 'Action'
            },
            data_type_map={
                'TimeGenerated': 'datetime',
                'SourceIP': 'string',
                'DestinationIP': 'string'
            }
        )

    async def test_route_logs(self, sentinel_router, sample_logs, table_config):
        """Test routing logs to Sentinel"""
        results = await sentinel_router.route_logs('firewall', sample_logs)
        
        assert results['processed'] == 2
        assert results['failed'] == 0
        assert results['batch_count'] == 1

    async def test_prepare_log_entry(self, sentinel_router, table_config):
        """Test log entry preparation"""
        log = {
            'src_ip': '192.168.1.1',
            'dst_ip': '10.0.0.1',
            'action': 'allow'
        }
        
        prepared_log = sentinel_router._prepare_log_entry(
            log, 
            table_config,
            'standard'
        )
        
        assert prepared_log['SourceIP'] == '192.168.1.1'
        assert prepared_log['DestinationIP'] == '10.0.0.1'
        assert prepared_log['Action'] == 'allow'
        assert 'TimeGenerated' in prepared_log
        assert prepared_log['DataClassification'] == 'standard'

    async def test_ingest_batch(self, sentinel_router, sample_logs, table_config):
        """Test batch ingestion"""
        results = {'processed': 0, 'failed': 0, 'batch_count': 0}
        
        await sentinel_router._ingest_batch(sample_logs, table_config, results)
        
        assert results['processed'] == 2
        assert results['batch_count'] == 1

    def test_create_batches(self, sentinel_router, sample_logs):
        """Test batch creation"""
        batches = sentinel_router._create_batches(sample_logs, batch_size=1)
        
        assert len(batches) == 2
        assert len(batches[0]) == 1
        assert len(batches[1]) == 1

    @pytest.mark.parametrize("value,target_type,expected", [
        ("123", "long", 123),
        ("true", "boolean", True),
        ("1.23", "double", 1.23),
        (123, "string", "123")
    ])
    def test_convert_data_type(self, sentinel_router, value, target_type, expected):
        """Test data type conversion"""
        result = sentinel_router._convert_data_type(value, target_type)
        assert result == expected
        assert isinstance(result, type(expected))

    async def test_handle_failed_batch(self, sentinel_router, sample_logs):
        """Test failed batch handling"""
        error = AzureError("Test error")
        await sentinel_router._handle_failed_batch(sample_logs, error)
        
        # Verify metrics were updated
        assert sentinel_router.metrics['failed_records'] > 0

    async def test_health_status(self, sentinel_router):
        """Test health status reporting"""
        status = await sentinel_router.get_health_status()
        
        assert 'status' in status
        assert 'metrics' in status
        assert 'last_check' in status