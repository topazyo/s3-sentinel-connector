# src/utils/transformations.py
"""Data transformation helpers for schema normalization and type coercion."""

import json
from datetime import datetime
from typing import Any, Dict, List


class DataTransformer:
    """Applies configured field-level transformations to parsed records."""

    def __init__(self) -> None:
        """Initialize data transformer"""
        self._initialize_transformers()

    def _initialize_transformers(self):
        """Initialize transformation functions"""
        self.transformers = {
            "timestamp": self._transform_timestamp,
            "ip": self._transform_ip,
            "integer": self._transform_integer,
            "float": self._transform_float,
            "boolean": self._transform_boolean,
            "string": self._transform_string,
            "json": self._transform_json,
            "list": self._transform_list,
            "map": self._transform_map,
        }

    def transform(
        self, data: Dict[str, Any], transformations: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Transform data according to transformation rules

        Args:
            data: Data to transform
            transformations: Transformation rules

        Returns:
            Transformed data
        """
        result = {}

        for field, transform_config in transformations.items():
            value = data.get(field)

            # Skip if field doesn't exist and not required
            if value is None and not transform_config.get("required", False):
                continue

            # Apply transformations
            transform_type = transform_config.get("type")
            transformer = self.transformers.get(transform_type)

            if transformer:
                try:
                    transformed_value = transformer(
                        value, transform_config.get("parameters", {})
                    )

                    # Store transformed value
                    target_field = transform_config.get("target_field", field)
                    result[target_field] = transformed_value

                except Exception as e:
                    if transform_config.get("required", False):
                        raise ValueError(
                            f"Failed to transform field {field}: {e!s}"
                        ) from e
                    continue

        return result

    def _transform_timestamp(self, value: Any, params: Dict[str, Any]) -> str:
        """Transform timestamp to standard format"""
        if isinstance(value, datetime):
            return value.isoformat()

        input_formats = params.get(
            "input_formats",
            ["%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%d %H:%M:%S", "%b %d %Y %H:%M:%S"],
        )

        output_format = params.get("output_format", "%Y-%m-%dT%H:%M:%S.%fZ")

        for fmt in input_formats:
            try:
                dt = datetime.strptime(value, fmt)
                return dt.strftime(output_format)
            except ValueError:
                continue

        raise ValueError(f"Unable to parse timestamp: {value}")

    def _transform_ip(self, value: Any, params: Dict[str, Any]) -> str:
        """Transform IP address"""
        import ipaddress

        try:
            ip = ipaddress.ip_address(value)
            return str(ip)
        except ValueError as e:
            raise ValueError(f"Invalid IP address: {value}") from e

    def _transform_integer(self, value: Any, params: Dict[str, Any]) -> int:
        """Transform value to integer"""
        try:
            return int(value)
        except (TypeError, ValueError) as e:
            raise ValueError(f"Unable to convert to integer: {value}") from e

    def _transform_float(self, value: Any, params: Dict[str, Any]) -> float:
        """Transform value to float"""
        try:
            return float(value)
        except (TypeError, ValueError) as e:
            raise ValueError(f"Unable to convert to float: {value}") from e

    def _transform_boolean(self, value: Any, params: Dict[str, Any]) -> bool:
        """Transform value to boolean"""
        if isinstance(value, bool):
            return value

        true_values = params.get("true_values", ["true", "1", "yes", "on"])
        false_values = params.get("false_values", ["false", "0", "no", "off"])

        str_value = str(value).lower()

        if str_value in true_values:
            return True
        elif str_value in false_values:
            return False

        raise ValueError(f"Unable to convert to boolean: {value}")

    def _transform_string(self, value: Any, params: Dict[str, Any]) -> str:
        """Transform value to string"""
        if value is None:
            return ""

        # Apply string transformations
        result = str(value)

        if params.get("strip", True):
            result = result.strip()

        if params.get("upper", False):
            result = result.upper()

        if params.get("lower", False):
            result = result.lower()

        if params.get("replace"):
            for old, new in params["replace"].items():
                result = result.replace(old, new)

        return result

    def _transform_json(self, value: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        """Transform JSON string to dictionary"""
        if isinstance(value, dict):
            return value

        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError) as e:
            raise ValueError(f"Unable to parse JSON: {value}") from e

    def _transform_list(self, value: Any, params: Dict[str, Any]) -> List[Any]:
        """Transform value to list"""
        if isinstance(value, list):
            return value

        if isinstance(value, str):
            separator = params.get("separator", ",")
            return [item.strip() for item in value.split(separator)]

        raise ValueError(f"Unable to convert to list: {value}")

    def _transform_map(self, value: Any, params: Dict[str, Any]) -> Any:
        """Transform value using mapping"""
        mapping = params.get("mapping", {})
        default = params.get("default")

        return mapping.get(value, default)
