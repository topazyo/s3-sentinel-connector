# tests/test_log_parser.py

import pytest
from datetime import datetime, timezone
from src.core.log_parser import FirewallLogParser, JsonLogParser, LogParserException

class TestFirewallLogParser:
    @pytest.fixture
    def sample_log_line(self):
        return '2024-02-20T12:00:00Z|192.168.1.1|10.0.0.1|allow|firewall-rule-1|TCP|80|443|1024'

    def test_parse_valid_log(self, firewall_parser, sample_log_line):
        """Test parsing valid firewall log"""
        parsed_data = firewall_parser.parse(sample_log_line.encode())
        
        assert parsed_data['SourceIP'] == '192.168.1.1'
        assert parsed_data['DestinationIP'] == '10.0.0.1'
        assert parsed_data['FirewallAction'] == 'allow'
        assert isinstance(parsed_data['TimeGenerated'], datetime)

    def test_normalize_ip_address(self, firewall_parser):
        """Test IP address normalization"""
        valid_ip = '192.168.1.1'
        invalid_ip = '256.256.256.256'
        
        assert firewall_parser._normalize_field('src_ip', valid_ip) == valid_ip
        with pytest.raises(ValueError):
            firewall_parser._normalize_field('src_ip', invalid_ip)

    def test_parse_timestamp(self, firewall_parser):
        """Test timestamp parsing with different formats"""
        timestamps = [
            '2024-02-20T12:00:00Z',
            'Feb 20 2024 12:00:00',
            '2024/02/20 12:00:00'
        ]
        
        for ts in timestamps:
            parsed = firewall_parser._parse_timestamp(ts)
            assert isinstance(parsed, datetime)

    def test_validate_parsed_data(self, firewall_parser):
        """Test validation of parsed log data"""
        valid_data = {
            'TimeGenerated': datetime.now(timezone.utc),
            'SourceIP': '192.168.1.1',
            'DestinationIP': '10.0.0.1',
            'FirewallAction': 'allow'
        }
        
        invalid_data = {
            'TimeGenerated': datetime.now(timezone.utc),
            'SourceIP': '192.168.1.1'  # Missing required fields
        }
        
        assert firewall_parser.validate(valid_data)
        assert not firewall_parser.validate(invalid_data)

class TestJsonLogParser:
    @pytest.fixture
    def sample_schema(self):
        return {
            'required': ['timestamp', 'event_type'],
            'types': {
                'timestamp': str,
                'event_type': str,
                'count': int
            }
        }

    def test_parse_valid_json(self, sample_schema):
        """Test parsing valid JSON log"""
        parser = JsonLogParser(schema=sample_schema)
        log_data = b'{"timestamp": "2024-02-20T12:00:00Z", "event_type": "login", "count": 1}'
        
        parsed_data = parser.parse(log_data)
        assert parsed_data['timestamp'] == "2024-02-20T12:00:00Z"
        assert parsed_data['event_type'] == "login"
        assert parsed_data['count'] == 1

    def test_parse_invalid_json(self, sample_schema):
        """Test parsing invalid JSON log"""
        parser = JsonLogParser(schema=sample_schema)
        invalid_log = b'{"invalid json'
        
        with pytest.raises(LogParserException):
            parser.parse(invalid_log)

    def test_schema_validation(self, sample_schema):
        """Test JSON schema validation"""
        parser = JsonLogParser(schema=sample_schema)
        
        valid_data = {
            'timestamp': '2024-02-20T12:00:00Z',
            'event_type': 'login',
            'count': 1
        }
        
        invalid_data = {
            'timestamp': '2024-02-20T12:00:00Z',
            'count': "invalid"  # Wrong type
        }
        
        assert parser.validate(valid_data)
        assert not parser.validate(invalid_data)