# src/utils/validation.py

from typing import Any, Dict, List, Optional, Union, Callable
from dataclasses import dataclass
import re
import ipaddress
from datetime import datetime
import json

@dataclass
class ValidationRule:
    """Validation rule definition"""
    field: str
    rule_type: str
    parameters: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None

class DataValidator:
    def __init__(self):
        """Initialize data validator"""
        self._initialize_validators()

    def _initialize_validators(self):
        """Initialize validation functions"""
        self.validators = {
            'required': self._validate_required,
            'type': self._validate_type,
            'regex': self._validate_regex,
            'range': self._validate_range,
            'enum': self._validate_enum,
            'ip': self._validate_ip,
            'timestamp': self._validate_timestamp,
            'length': self._validate_length,
            'custom': self._validate_custom
        }

    def validate(self, 
                data: Dict[str, Any],
                rules: List[ValidationRule]) -> Dict[str, List[str]]:
        """
        Validate data against rules
        
        Args:
            data: Data to validate
            rules: List of validation rules
            
        Returns:
            Dictionary of validation errors by field
        """
        errors: Dict[str, List[str]] = {}
        
        for rule in rules:
            validator = self.validators.get(rule.rule_type)
            if not validator:
                continue
                
            field_value = data.get(rule.field)
            error = validator(field_value, rule.parameters or {})
            
            if error:
                if rule.field not in errors:
                    errors[rule.field] = []
                errors[rule.field].append(
                    rule.error_message or error
                )
                
        return errors

    def _validate_required(self, 
                         value: Any,
                         params: Dict[str, Any]) -> Optional[str]:
        """Validate required field"""
        if value is None or (isinstance(value, str) and not value.strip()):
            return "Field is required"
        return None

    def _validate_type(self, 
                      value: Any,
                      params: Dict[str, Any]) -> Optional[str]:
        """Validate value type"""
        if value is None:
            return None
            
        expected_type = params.get('type')
        if not expected_type:
            return None
            
        type_mapping = {
            'string': str,
            'integer': int,
            'float': float,
            'boolean': bool,
            'list': list,
            'dict': dict
        }
        
        expected_type_class = type_mapping.get(expected_type)
        if not expected_type_class:
            return None
            
        if not isinstance(value, expected_type_class):
            return f"Expected type {expected_type}, got {type(value).__name__}"
            
        return None

    def _validate_regex(self, 
                       value: Any,
                       params: Dict[str, Any]) -> Optional[str]:
        """Validate against regex pattern"""
        if not value or not isinstance(value, str):
            return None
            
        pattern = params.get('pattern')
        if not pattern:
            return None
            
        if not re.match(pattern, value):
            return "Value does not match required pattern"
            
        return None

    def _validate_range(self, 
                       value: Any,
                       params: Dict[str, Any]) -> Optional[str]:
        """Validate numeric range"""
        if value is None:
            return None
            
        try:
            numeric_value = float(value)
            min_value = params.get('min')
            max_value = params.get('max')
            
            if min_value is not None and numeric_value < min_value:
                return f"Value must be greater than or equal to {min_value}"
                
            if max_value is not None and numeric_value > max_value:
                return f"Value must be less than or equal to {max_value}"
                
        except (TypeError, ValueError):
            return "Value must be numeric"
            
        return None

    def _validate_enum(self, 
                      value: Any,
                      params: Dict[str, Any]) -> Optional[str]:
        """Validate against enumerated values"""
        if value is None:
            return None
            
        allowed_values = params.get('values', [])
        if value not in allowed_values:
            return f"Value must be one of: {', '.join(map(str, allowed_values))}"
            
        return None

    def _validate_ip(self, 
                    value: Any,
                    params: Dict[str, Any]) -> Optional[str]:
        """Validate IP address"""
        if not value:
            return None
            
        try:
            ip = ipaddress.ip_address(value)
            ip_version = params.get('version')
            
            if ip_version == 4 and not isinstance(ip, ipaddress.IPv4Address):
                return "Must be an IPv4 address"
                
            if ip_version == 6 and not isinstance(ip, ipaddress.IPv6Address):
                return "Must be an IPv6 address"
                
        except ValueError:
            return "Invalid IP address"
            
        return None

    def _validate_timestamp(self, 
                          value: Any,
                          params: Dict[str, Any]) -> Optional[str]:
        """Validate timestamp"""
        if not value:
            return None
            
        formats = params.get('formats', ["%Y-%m-%dT%H:%M:%S.%fZ"])
        
        for fmt in formats:
            try:
                datetime.strptime(value, fmt)
                return None
            except ValueError:
                continue
                
        return "Invalid timestamp format"

    def _validate_length(self, 
                        value: Any,
                        params: Dict[str, Any]) -> Optional[str]:
        """Validate string or list length"""
        if value is None:
            return None
            
        try:
            length = len(value)
            min_length = params.get('min')
            max_length = params.get('max')
            
            if min_length is not None and length < min_length:
                return f"Length must be at least {min_length}"
                
            if max_length is not None and length > max_length:
                return f"Length must be at most {max_length}"
                
        except TypeError:
            return "Value must have a length"
            
        return None

    def _validate_custom(self, 
                        value: Any,
                        params: Dict[str, Any]) -> Optional[str]:
        """Execute custom validation function"""
        validator_func = params.get('function')
        if not validator_func or not callable(validator_func):
            return None
            
        try:
            result = validator_func(value)
            if isinstance(result, str):
                return result
            elif not result:
                return "Custom validation failed"
        except Exception as e:
            return f"Custom validation error: {str(e)}"
            
        return None