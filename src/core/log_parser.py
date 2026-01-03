# src/core/log_parser.py

import json
import ipaddress
import logging
from datetime import datetime, timezone
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
    
    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
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
            '%Y-%m-%dT%H:%M:%SZ',
            '%Y-%m-%d %H:%M:%S',
            '%b %d %Y %H:%M:%S',
            '%Y/%m/%d %H:%M:%S'
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
            parsed_data['ProcessingTime'] = datetime.now(timezone.utc)
            
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
                self.logger.error(f"Missing required field: {field}")
                return False
        
        # Validate IP addresses
        try:
            ipaddress.ip_address(parsed_data['SourceIP'])
            ipaddress.ip_address(parsed_data['DestinationIP'])
        except ValueError:
            self.logger.error("Invalid IP address format")
            return False
        
        # Validate action
        valid_actions = ['allow', 'deny', 'drop', 'reset']
        if parsed_data['FirewallAction'].lower() not in valid_actions:
            self.logger.error(f"Invalid firewall action: {parsed_data['FirewallAction']}")
            return False
        
        return True

    def _parse_timestamp(self, timestamp_str: str) -> datetime:
        """Parse timestamp string into datetime object"""
        for fmt in self.timestamp_formats:
            try:
                parsed = datetime.strptime(timestamp_str, fmt)
                # Attach UTC if no timezone info present
                return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
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
    
    # Phase 5 (Security - B1-002/SEC-03): DoS protection limits
    DEFAULT_MAX_SIZE_BYTES = 10 * 1024 * 1024  # 10MB
    DEFAULT_MAX_DEPTH = 50  # Max nesting depth
    
    def __init__(self, 
                 schema: Optional[Dict] = None,
                 max_size_bytes: Optional[int] = None,
                 max_depth: Optional[int] = None) -> None:
        """Initialize JSON log parser with security limits.
        
        Args:
            schema: Optional schema for validation
            max_size_bytes: Maximum JSON payload size (default: 10MB)
            max_depth: Maximum nesting depth (default: 50)
            
        Phase 5 (Security): Size and depth limits prevent DoS attacks
        via deeply nested or large JSON payloads.
        """
        self.schema = schema or {}
        self.max_size_bytes = max_size_bytes or self.DEFAULT_MAX_SIZE_BYTES
        self.max_depth = max_depth or self.DEFAULT_MAX_DEPTH
        self.logger = logging.getLogger(__name__)
        
    def parse(self, log_data: bytes) -> Dict[str, Any]:
        """Parse JSON log data with security limits.
        
        Args:
            log_data: Raw JSON data in bytes
            
        Returns:
            Parsed JSON dictionary
            
        Raises:
            LogParserException: If payload exceeds size/depth limits or is invalid JSON
            
        Phase 5 (Security): Enforces size and depth limits before parsing
        Phase 4 (Resilience): Structured error logging with context
        """
        try:
            # Phase 5 (Security - B1-002): Check size limit before parsing
            payload_size = len(log_data)
            if payload_size > self.max_size_bytes:
                error_msg = (
                    f"JSON payload exceeds maximum size: "
                    f"{payload_size} bytes > {self.max_size_bytes} bytes"
                )
                self.logger.warning(
                    "JSON size limit exceeded",
                    extra={
                        'payload_size': payload_size,
                        'max_size': self.max_size_bytes,
                        'component': 'JsonLogParser'
                    }
                )
                raise LogParserException(error_msg)
            
            # Phase 5 (Security - B1-002): Parse with depth limit
            parsed_json = self._parse_with_depth_limit(log_data)
            
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

    def _apply_schema(self, parsed_json: Dict[str, Any]) -> Dict[str, Any]:
        """Apply basic schema mapping and type validation for JSON logs."""
        result: Dict[str, Any] = {}

        # Ensure required fields exist
        required_fields = self.schema.get('required', [])
        for field in required_fields:
            if field not in parsed_json:
                raise LogParserException(f"Missing required field: {field}")

        # Copy fields while enforcing expected types when provided
        field_types = self.schema.get('types', {})
        for field, value in parsed_json.items():
            expected_type = field_types.get(field)
            if expected_type:
                if not isinstance(value, expected_type):
                    raise LogParserException(
                        f"Field {field} expected {expected_type.__name__}, got {type(value).__name__}"
                    )
            result[field] = value

        return result
    
    def _parse_with_depth_limit(self, log_data: bytes) -> Dict[str, Any]:
        """Parse JSON with depth limit to prevent deeply nested payloads.
        
        Args:
            log_data: Raw JSON bytes
            
        Returns:
            Parsed JSON dictionary
            
        Raises:
            LogParserException: If nesting depth exceeds max_depth
            
        Phase 5 (Security - B1-002/SEC-03): Prevents DoS via deeply nested JSON
        """
        # First parse without depth check
        try:
            parsed = json.loads(log_data)
        except RecursionError:
            raise LogParserException(
                f"JSON nesting depth exceeds maximum: > {self.max_depth} levels"
            )
        
        # Then validate depth
        actual_depth = self._measure_depth(parsed)
        if actual_depth > self.max_depth:
            raise LogParserException(
                f"JSON nesting depth exceeds maximum: "
                f"{actual_depth} levels > {self.max_depth} levels"
            )
        
        return parsed
    
    def _measure_depth(self, obj: Any, current_depth: int = 1) -> int:
        """Recursively measure the nesting depth of a JSON structure.
        
        Args:
            obj: Object to measure
            current_depth: Current depth level
            
        Returns:
            Maximum depth found
        """
        if not isinstance(obj, (dict, list)):
            return current_depth
        
        if isinstance(obj, dict):
            if not obj:  # Empty dict
                return current_depth
            return max(
                self._measure_depth(v, current_depth + 1)
                for v in obj.values()
            )
        else:  # list
            if not obj:  # Empty list
                return current_depth
            return max(
                self._measure_depth(item, current_depth + 1)
                for item in obj
            )