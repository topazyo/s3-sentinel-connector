# src/core/log_parser.py

import json
import re
import ipaddress
from datetime import datetime
from typing import Dict, Any, Optional, List
from abc import ABC, abstractmethod

class LogParserException(Exception):
    """Base exception for log parsing errors"""
    pass

class LogParser(ABC):
    """Abstract base class for log parsers"""
    
    @abstractmethod
    def parse(self, log_data: bytes) -> Dict[str, Any]:
        """Parse log data into structured format"""
        pass
    
    @abstractmethod
    def validate(self, parsed_data: Dict[str, Any]) -> bool:
        """Validate parsed log data"""
        pass

class FirewallLogParser(LogParser):
    """Parser for firewall logs"""
    
    def __init__(self):
        self.field_mappings = {
            'src_ip': 'SourceIP',
            'dst_ip': 'DestinationIP',
            'action': 'FirewallAction',
            'rule_name': 'RuleName',
            'proto': 'Protocol',
            'src_port': 'SourcePort',
            'dst_port': 'DestinationPort',
            'bytes': 'BytesTransferred'
        }
        
        self.timestamp_formats = [
            '%Y-%m-%dT%H:%M:%S.%fZ',
            '%Y-%m-%d %H:%M:%S',
            '%b %d %Y %H:%M:%S'
        ]

    def parse(self, log_data: bytes) -> Dict[str, Any]:
        """
        Parse firewall log data
        
        Args:
            log_data: Raw log data in bytes
            
        Returns:
            Dict containing parsed log fields
        """
        try:
            # Decode and split log line
            log_line = log_data.decode('utf-8').strip()
            fields = log_line.split('|')
            
            # Create initial parsed data
            parsed_data = {}
            
            # Extract timestamp first
            timestamp_str = fields[0]
            parsed_data['TimeGenerated'] = self._parse_timestamp(timestamp_str)
            
            # Parse remaining fields
            for field_name, value in zip(self.field_mappings.keys(), fields[1:]):
                normalized_name = self.field_mappings.get(field_name, field_name)
                parsed_data[normalized_name] = self._normalize_field(field_name, value)
            
            # Add additional computed fields
            parsed_data['LogSource'] = 'Firewall'
            parsed_data['ProcessingTime'] = datetime.utcnow()
            
            return parsed_data
            
        except Exception as e:
            raise LogParserException(f"Failed to parse firewall log: {str(e)}")

    def validate(self, parsed_data: Dict[str, Any]) -> bool:
        """
        Validate parsed log data
        
        Args:
            parsed_data: Dictionary containing parsed log fields
            
        Returns:
            bool indicating if data is valid
        """
        required_fields = ['TimeGenerated', 'SourceIP', 'DestinationIP', 'FirewallAction']
        
        # Check required fields
        for field in required_fields:
            if field not in parsed_data:
                logging.error(f"Missing required field: {field}")
                return False
        
        # Validate IP addresses
        try:
            ipaddress.ip_address(parsed_data['SourceIP'])
            ipaddress.ip_address(parsed_data['DestinationIP'])
        except ValueError:
            logging.error("Invalid IP address format")
            return False
        
        # Validate action
        valid_actions = ['allow', 'deny', 'drop', 'reset']
        if parsed_data['FirewallAction'].lower() not in valid_actions:
            logging.error(f"Invalid firewall action: {parsed_data['FirewallAction']}")
            return False
        
        return True

    def _parse_timestamp(self, timestamp_str: str) -> datetime:
        """Parse timestamp string into datetime object"""
        for fmt in self.timestamp_formats:
            try:
                return datetime.strptime(timestamp_str, fmt)
            except ValueError:
                continue
        raise ValueError(f"Unable to parse timestamp: {timestamp_str}")

    def _normalize_field(self, field_name: str, value: str) -> Any:
        """Normalize field values based on field type"""
        if not value:
            return None
            
        # IP address fields
        if field_name in ['src_ip', 'dst_ip']:
            return str(ipaddress.ip_address(value.strip()))
            
        # Integer fields
        if field_name in ['src_port', 'dst_port', 'bytes']:
            return int(value)
            
        # Action field
        if field_name == 'action':
            return value.lower()
            
        # Protocol field
        if field_name == 'proto':
            return value.upper()
            
        return value.strip()

class JsonLogParser(LogParser):
    """Parser for JSON-formatted logs"""
    
    def __init__(self, schema: Optional[Dict] = None):
        self.schema = schema or {}
        
    def parse(self, log_data: bytes) -> Dict[str, Any]:
        try:
            # Parse JSON data
            parsed_json = json.loads(log_data)
            
            # Apply schema mapping if provided
            if self.schema:
                return self._apply_schema(parsed_json)
            
            return parsed_json
            
        except json.JSONDecodeError as e:
            raise LogParserException(f"Invalid JSON format: {str(e)}")
            
    def validate(self, parsed_data: Dict[str, Any]) -> bool:
        """Validate JSON data against schema"""
        if not self.schema:
            return True
            
        required_fields = self.schema.get('required', [])
        field_types = self.schema.get('types', {})
        
        # Check required fields
        for field in required_fields:
            if field not in parsed_data:
                return False
        
        # Check field types
        for field, expected_type in field_types.items():
            if field in parsed_data and not isinstance(parsed_data[field], expected_type):
                return False
        
        return True