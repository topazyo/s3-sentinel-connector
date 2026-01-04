# src/security/config_validator.py

import ipaddress
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


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
    def __init__(self, policy: Optional[SecurityPolicy] = None) -> None:
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
            "credential": self._validate_credential_config,
            "encryption": self._validate_encryption_config,
            "network": self._validate_network_config,
            "permissions": self._validate_permissions,
        }

    def _validate_credential(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Backward-compatible credential validation hook."""
        return self._validate_credential_config(config)

    def validate_configuration(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate configuration against security policy

        Args:
            config: Configuration dictionary to validate

        Returns:
            Dictionary with validation results
        """
        results = {"valid": True, "violations": [], "warnings": []}

        try:
            # Validate credentials configuration
            if "credentials" in config:
                cred_results = self._validate_credential_config(config["credentials"])
                self._update_results(results, cred_results)

            # Validate encryption configuration
            if "encryption" in config:
                enc_results = self._validate_encryption_config(config["encryption"])
                self._update_results(results, enc_results)

            # Validate network configuration
            if "network" in config:
                net_results = self._validate_network_config(config["network"])
                self._update_results(results, net_results)

            # Check for sensitive data exposure
            self._check_sensitive_data(config, results)

        except Exception as e:
            self.logger.error(f"Configuration validation failed: {e!s}")
            results["valid"] = False
            results["violations"].append(f"Validation error: {e!s}")

        return results

    def _validate_credential_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Validate credential-related configuration"""
        results = {"valid": True, "violations": [], "warnings": []}

        # Check credential strength requirements
        if "min_length" in config:
            if config["min_length"] < self.policy.min_password_length:
                results["violations"].append(
                    f"Password length must be at least {self.policy.min_password_length}"
                )

        # Check credential rotation policy
        if "rotation_days" in config:
            if config["rotation_days"] > self.policy.max_credential_age_days:
                results["violations"].append(
                    f"Credential rotation period exceeds {self.policy.max_credential_age_days} days"
                )

        # Check encryption requirements
        if not config.get("encrypt_at_rest", True):
            results["violations"].append("Credentials must be encrypted at rest")

        return results

    def _validate_encryption_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Validate encryption configuration"""
        results = {"valid": True, "violations": [], "warnings": []}

        # Check encryption algorithm
        if "algorithm" in config:
            if not self._is_secure_algorithm(config["algorithm"]):
                results["violations"].append(
                    f"Insecure encryption algorithm: {config['algorithm']}"
                )

        # Check key strength
        if "key_bits" in config:
            if config["key_bits"] < self.policy.min_encryption_bits:
                results["violations"].append(
                    f"Encryption key strength must be at least {self.policy.min_encryption_bits} bits"
                )

        return results

    def _validate_network_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Validate network configuration"""
        results = {"valid": True, "violations": [], "warnings": []}

        # Validate IP ranges
        if "allowed_ips" in config:
            for ip_range in config["allowed_ips"]:
                try:
                    ipaddress.ip_network(ip_range)
                except ValueError:
                    results["violations"].append(f"Invalid IP range: {ip_range}")

        # Check for secure protocols
        if "protocols" in config:
            insecure_protocols = ["http", "ftp", "telnet"]
            for protocol in config["protocols"]:
                if protocol.lower() in insecure_protocols:
                    results["violations"].append(f"Insecure protocol: {protocol}")

        return results

    def _validate_permissions(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate RBAC permission structure and definitions.

        Args:
            config: Configuration containing permissions/roles

        Returns:
            Validation results with violations and warnings
        """
        results = {"valid": True, "violations": [], "warnings": []}

        # Check for permissions configuration
        permissions_config = config.get("permissions", {})
        roles_config = config.get("roles", {})

        if not permissions_config and not roles_config:
            results["warnings"].append("No permissions or roles configuration found")
            return results

        # Validate roles structure
        if roles_config:
            for role_name, role_data in roles_config.items():
                if not isinstance(role_data, dict):
                    results["violations"].append(
                        f"Role '{role_name}' must be a dictionary"
                    )
                    results["valid"] = False
                    continue

                # Check required fields
                if "permissions" not in role_data:
                    results["violations"].append(
                        f"Role '{role_name}' missing 'permissions' field"
                    )
                    results["valid"] = False

                # Validate permissions list
                perms = role_data.get("permissions", [])
                if not isinstance(perms, list):
                    results["violations"].append(
                        f"Role '{role_name}' permissions must be a list"
                    )
                    results["valid"] = False
                elif not perms:
                    results["warnings"].append(
                        f"Role '{role_name}' has no permissions defined"
                    )

                # Check for wildcard permissions (security concern)
                if "*" in perms or "admin:*" in perms:
                    results["warnings"].append(
                        f"Role '{role_name}' has wildcard permissions - review for security"
                    )

        # Validate permission definitions
        if permissions_config:
            for perm_name, perm_data in permissions_config.items():
                if not isinstance(perm_data, dict):
                    results["violations"].append(
                        f"Permission '{perm_name}' must be a dictionary"
                    )
                    results["valid"] = False
                    continue

                # Check for resource and action
                if "resource" not in perm_data:
                    results["violations"].append(
                        f"Permission '{perm_name}' missing 'resource' field"
                    )
                    results["valid"] = False

                if "actions" not in perm_data:
                    results["violations"].append(
                        f"Permission '{perm_name}' missing 'actions' field"
                    )
                    results["valid"] = False

                # Validate actions
                actions = perm_data.get("actions", [])
                if not isinstance(actions, list):
                    results["violations"].append(
                        f"Permission '{perm_name}' actions must be a list"
                    )
                    results["valid"] = False
                elif not actions:
                    results["warnings"].append(
                        f"Permission '{perm_name}' has no actions defined"
                    )

                # Check for valid action types
                valid_actions = ["read", "write", "delete", "execute", "admin"]
                for action in actions:
                    if action not in valid_actions and action != "*":
                        results["warnings"].append(
                            f"Permission '{perm_name}' has non-standard action: {action}"
                        )

        return results

    def _check_sensitive_data(
        self, config: Dict[str, Any], results: Dict[str, Any]
    ) -> None:
        """Check for sensitive data in configuration"""
        sensitive_patterns = [
            r"password[s]?",
            r"secret[s]?",
            r"key[s]?",
            r"token[s]?",
            r"credential[s]?",
        ]

        def check_value(value: Any, path: str):
            if isinstance(value, str):
                # Check if value matches sensitive patterns
                for pattern in sensitive_patterns:
                    if re.search(pattern, value, re.IGNORECASE):
                        results["warnings"].append(f"Possible sensitive data in {path}")

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
        secure_algorithms = ["AES-256-GCM", "AES-256-CBC", "ChaCha20-Poly1305"]
        return algorithm in secure_algorithms

    def _update_results(self, target: Dict[str, Any], source: Dict[str, Any]) -> None:
        """Update validation results"""
        if source.get("violations", []):
            target["valid"] = False
            target["violations"].extend(source["violations"])

        if source.get("warnings", []):
            target["warnings"].extend(source["warnings"])

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

            if path.suffix == ".yaml" or path.suffix == ".yml":
                with open(path) as f:
                    config = yaml.safe_load(f)
            elif path.suffix == ".json":
                with open(path) as f:
                    config = json.load(f)
            else:
                raise ValueError(f"Unsupported file format: {path.suffix}")

            return self.validate_configuration(config)

        except Exception as e:
            self.logger.error(f"Failed to validate configuration file: {e!s}")
            return {
                "valid": False,
                "violations": [f"File validation error: {e!s}"],
                "warnings": [],
            }
