# src/security/config_validator.py

from typing import Dict, Any, List, Optional
import re
import ipaddress
from dataclasses import dataclass
import yaml
import json
from pathlib import Path
import logging

@dataclass
class SecurityPolicy:
    """Security policy configuration"""
    min_password_length: int = 12
    require_special_chars: bool = True
    require_numbers: bool = True
    max_credential_age_days: int = 90
    allowed_ip_ranges: List[str] = None
    required_encryption: bool = True
    min_encryption_bits: int = 256

class ConfigurationValidator:
    def __init__(self, policy: Optional[SecurityPolicy] = None):
        """
        Initialize configuration validator
        
        Args:
            policy: Security policy configuration
        """
        self.policy = policy or SecurityPolicy()
        self.logger = logging.getLogger(__name__)
        
        # Initialize validation rules
        self._initialize_validation_rules()

    def _initialize_validation_rules(self):
        """Initialize validation rules"""
        self.validation_rules = {
            'credential': self._validate_credential,
            'encryption': self._validate_encryption,
            'network': self._validate_network,
            'permissions': self._validate_permissions
        }

    def validate_configuration(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate configuration against security policy
        
        Args:
            config: Configuration dictionary to validate
            
        Returns:
            Dictionary with validation results
        """
        results = {
            'valid': True,
            'violations': [],
            'warnings': []
        }
        
        try:
            # Validate credentials configuration
            if 'credentials' in config:
                cred_results = self._validate_credential_config(config['credentials'])
                self._update_results(results, cred_results)
            
            # Validate encryption configuration
            if 'encryption' in config:
                enc_results = self._validate_encryption_config(config['encryption'])
                self._update_results(results, enc_results)
            
            # Validate network configuration
            if 'network' in config:
                net_results = self._validate_network_config(config['network'])
                self._update_results(results, net_results)
            
            # Check for sensitive data exposure
            self._check_sensitive_data(config, results)
            
        except Exception as e:
            self.logger.error(f"Configuration validation failed: {str(e)}")
            results['valid'] = False
            results['violations'].append(f"Validation error: {str(e)}")
            
        return results

    def _validate_credential_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Validate credential-related configuration"""
        results = {'valid': True, 'violations': [], 'warnings': []}
        
        # Check credential strength requirements
        if 'min_length' in config:
            if config['min_length'] < self.policy.min_password_length:
                results['violations'].append(
                    f"Password length must be at least {self.policy.min_password_length}"
                )
        
        # Check credential rotation policy
        if 'rotation_days' in config:
            if config['rotation_days'] > self.policy.max_credential_age_days:
                results['violations'].append(
                    f"Credential rotation period exceeds {self.policy.max_credential_age_days} days"
                )
        
        # Check encryption requirements
        if not config.get('encrypt_at_rest', True):
            results['violations'].append("Credentials must be encrypted at rest")
        
        return results

    def _validate_encryption_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Validate encryption configuration"""
        results = {'valid': True, 'violations': [], 'warnings': []}
        
        # Check encryption algorithm
        if 'algorithm' in config:
            if not self._is_secure_algorithm(config['algorithm']):
                results['violations'].append(
                    f"Insecure encryption algorithm: {config['algorithm']}"
                )
        
        # Check key strength
        if 'key_bits' in config:
            if config['key_bits'] < self.policy.min_encryption_bits:
                results['violations'].append(
                    f"Encryption key strength must be at least {self.policy.min_encryption_bits} bits"
                )
        
        return results

    def _validate_network_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Validate network configuration"""
        results = {'valid': True, 'violations': [], 'warnings': []}
        
        # Validate IP ranges
        if 'allowed_ips' in config:
            for ip_range in config['allowed_ips']:
                try:
                    ipaddress.ip_network(ip_range)
                except ValueError:
                    results['violations'].append(f"Invalid IP range: {ip_range}")
        
        # Check for secure protocols
        if 'protocols' in config:
            insecure_protocols = ['http', 'ftp', 'telnet']
            for protocol in config['protocols']:
                if protocol.lower() in insecure_protocols:
                    results['violations'].append(f"Insecure protocol: {protocol}")
        
        return results

    def _check_sensitive_data(self, config: Dict[str, Any], 
                            results: Dict[str, Any]) -> None:
        """Check for sensitive data in configuration"""
        sensitive_patterns = [
            r'password[s]?',
            r'secret[s]?',
            r'key[s]?',
            r'token[s]?',
            r'credential[s]?'
        ]
        
        def check_value(value: Any, path: str):
            if isinstance(value, str):
                # Check if value matches sensitive patterns
                for pattern in sensitive_patterns:
                    if re.search(pattern, value, re.IGNORECASE):
                        results['warnings'].append(
                            f"Possible sensitive data in {path}"
                        )
        
        def traverse_dict(d: Dict[str, Any], parent_path: str = ""):
            for key, value in d.items():
                current_path = f"{parent_path}.{key}" if parent_path else key
                
                if isinstance(value, dict):
                    traverse_dict(value, current_path)
                elif isinstance(value, list):
                    for i, item in enumerate(value):
                        if isinstance(item, dict):
                            traverse_dict(item, f"{current_path}[{i}]")
                        else:
                            check_value(item, f"{current_path}[{i}]")
                else:
                    check_value(value, current_path)
        
        traverse_dict(config)

    def _is_secure_algorithm(self, algorithm: str) -> bool:
        """Check if encryption algorithm is secure"""
        secure_algorithms = [
            'AES-256-GCM',
            'AES-256-CBC',
            'ChaCha20-Poly1305'
        ]
        return algorithm in secure_algorithms

    def _update_results(self, target: Dict[str, Any], 
                       source: Dict[str, Any]) -> None:
        """Update validation results"""
        if source.get('violations', []):
            target['valid'] = False
            target['violations'].extend(source['violations'])
        
        if source.get('warnings', []):
            target['warnings'].extend(source['warnings'])

    def validate_file(self, file_path: str) -> Dict[str, Any]:
        """
        Validate configuration file
        
        Args:
            file_path: Path to configuration file
            
        Returns:
            Validation results
        """
        try:
            path = Path(file_path)
            
            if path.suffix == '.yaml' or path.suffix == '.yml':
                with open(path) as f:
                    config = yaml.safe_load(f)
            elif path.suffix == '.json':
                with open(path) as f:
                    config = json.load(f)
            else:
                raise ValueError(f"Unsupported file format: {path.suffix}")
            
            return self.validate_configuration(config)
            
        except Exception as e:
            self.logger.error(f"Failed to validate configuration file: {str(e)}")
            return {
                'valid': False,
                'violations': [f"File validation error: {str(e)}"],
                'warnings': []
            }