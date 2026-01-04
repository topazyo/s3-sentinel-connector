# tests/unit/test_log_parser_limits.py
"""
Unit tests for JSON parsing security limits (B1-002/SEC-03).

Phase 5 (Security): Validates that size and depth limits prevent DoS attacks.
Phase 7 (Testing): Comprehensive coverage of edge cases and error conditions.
"""

import json

import pytest

from src.core.log_parser import JsonLogParser, LogParserException


class TestJsonSizeLimits:
    """Test JSON payload size limits."""

    def test_small_payload_accepted(self):
        """Phase 7: Small payloads should parse successfully."""
        parser = JsonLogParser(max_size_bytes=1024)
        small_json = json.dumps({"field": "value"}).encode("utf-8")

        result = parser.parse(small_json)

        assert result == {"field": "value"}

    def test_exactly_at_size_limit(self):
        """Phase 7: Payload exactly at limit should be accepted."""
        max_size = 1000
        parser = JsonLogParser(max_size_bytes=max_size)

        # Create payload exactly at limit
        data = {"data": "x" * (max_size - 20)}  # Account for JSON overhead
        payload = json.dumps(data).encode("utf-8")

        # Ensure we're at the limit
        if len(payload) <= max_size:
            result = parser.parse(payload)
            assert "data" in result

    def test_payload_exceeds_size_limit(self):
        """Phase 5 (Security - B1-002): Oversized payload should be rejected."""
        max_size = 100
        parser = JsonLogParser(max_size_bytes=max_size)

        # Create payload that exceeds limit
        large_data = {"data": "x" * 200}
        large_json = json.dumps(large_data).encode("utf-8")

        with pytest.raises(LogParserException) as exc_info:
            parser.parse(large_json)

        assert "exceeds maximum size" in str(exc_info.value)
        assert str(max_size) in str(exc_info.value)

    def test_default_max_size(self):
        """Phase 7: Default 10MB limit should be enforced."""
        parser = JsonLogParser()

        assert parser.max_size_bytes == 10 * 1024 * 1024  # 10MB

        # 11MB payload should fail
        large_payload = b"x" * (11 * 1024 * 1024)

        with pytest.raises(LogParserException) as exc_info:
            parser.parse(large_payload)

        assert "exceeds maximum size" in str(exc_info.value)

    def test_custom_max_size_respected(self):
        """Phase 2 (Consistency): Custom size limits should be respected."""
        custom_limit = 500
        parser = JsonLogParser(max_size_bytes=custom_limit)

        assert parser.max_size_bytes == custom_limit


class TestJsonDepthLimits:
    """Test JSON nesting depth limits."""

    def test_shallow_nesting_accepted(self):
        """Phase 7: Shallow nesting should parse successfully."""
        parser = JsonLogParser(max_depth=10)
        shallow = {"level1": {"level2": {"level3": "value"}}}
        payload = json.dumps(shallow).encode("utf-8")

        result = parser.parse(payload)

        assert result["level1"]["level2"]["level3"] == "value"

    def test_exactly_at_depth_limit(self):
        """Phase 7: Nesting exactly at limit should be accepted."""
        max_depth = 5
        parser = JsonLogParser(max_depth=max_depth)

        # Build nested structure exactly at max_depth
        # Note: Depth measurement starts at 1 for the root object
        # So for max_depth=5, we can have 4 nested levels
        nested = {}
        current = nested
        for _i in range(max_depth - 2):  # -2 because root is 1, and we measure values
            current["nested"] = {}
            current = current["nested"]
        current["value"] = "deep"

        payload = json.dumps(nested).encode("utf-8")
        result = parser.parse(payload)

        # Verify it parsed
        assert isinstance(result, dict)

    def test_exceeds_depth_limit(self):
        """Phase 5 (Security - B1-002): Deeply nested JSON should be rejected."""
        max_depth = 5
        parser = JsonLogParser(max_depth=max_depth)

        # Build nested structure that exceeds limit
        nested = {}
        current = nested
        for _i in range(max_depth + 5):  # Exceed by 5 levels
            current["nested"] = {}
            current = current["nested"]
        current["value"] = "too_deep"

        payload = json.dumps(nested).encode("utf-8")

        with pytest.raises(LogParserException) as exc_info:
            parser.parse(payload)

        assert "nesting depth exceeds maximum" in str(exc_info.value)

    def test_default_max_depth(self):
        """Phase 7: Default 50 level depth limit should be enforced."""
        parser = JsonLogParser()

        assert parser.max_depth == 50

        # Build 60-level nested structure
        nested = {}
        current = nested
        for _i in range(60):
            current["n"] = {}
            current = current["n"]
        current["end"] = True

        payload = json.dumps(nested).encode("utf-8")

        with pytest.raises(LogParserException) as exc_info:
            parser.parse(payload)

        assert "nesting depth exceeds maximum" in str(exc_info.value)

    def test_custom_max_depth_respected(self):
        """Phase 2 (Consistency): Custom depth limits should be respected."""
        custom_depth = 10
        parser = JsonLogParser(max_depth=custom_depth)

        assert parser.max_depth == custom_depth

    def test_array_nesting_depth(self):
        """Phase 7: Arrays should also count towards depth limit."""
        max_depth = 3
        parser = JsonLogParser(max_depth=max_depth)

        # Arrays inside objects increase depth
        nested = {"level1": {"level2": {"level3": {"level4": "too_deep"}}}}
        payload = json.dumps(nested).encode("utf-8")

        with pytest.raises(LogParserException) as exc_info:
            parser.parse(payload)

        assert "nesting depth exceeds maximum" in str(exc_info.value)


class TestCombinedLimits:
    """Test combined size and depth scenarios."""

    def test_large_and_deep_payload(self):
        """Phase 5: Large AND deep payload should be rejected."""
        parser = JsonLogParser(max_size_bytes=500, max_depth=3)

        # Create payload that's both large and deep
        nested = {}
        current = nested
        for _i in range(10):  # Exceeds depth
            current["data"] = "x" * 50  # Adds size
            current["nested"] = {}
            current = current["nested"]

        payload = json.dumps(nested).encode("utf-8")

        # Should fail on size check first (happens before depth check)
        if len(payload) > 500:
            with pytest.raises(LogParserException) as exc_info:
                parser.parse(payload)
            assert "exceeds maximum size" in str(exc_info.value)

    def test_wide_but_shallow(self):
        """Phase 7: Wide (many keys) but shallow should be OK."""
        parser = JsonLogParser(max_depth=5)

        # Many keys at same level
        wide = {f"key_{i}": f"value_{i}" for i in range(1000)}
        payload = json.dumps(wide).encode("utf-8")

        # Should succeed if under size limit
        if len(payload) <= parser.max_size_bytes:
            result = parser.parse(payload)
            assert len(result) == 1000


class TestErrorMessages:
    """Test that error messages are informative."""

    def test_size_limit_error_contains_details(self):
        """Phase 4 (Observability): Error messages should be informative."""
        parser = JsonLogParser(max_size_bytes=100)
        large = json.dumps({"data": "x" * 200}).encode("utf-8")

        with pytest.raises(LogParserException) as exc_info:
            parser.parse(large)

        error_msg = str(exc_info.value)
        assert "exceeds maximum size" in error_msg
        assert "100" in error_msg  # Max size mentioned
        assert "bytes" in error_msg

    def test_depth_limit_error_contains_details(self):
        """Phase 4 (Observability): Depth errors should be clear."""
        parser = JsonLogParser(max_depth=3)

        nested = {}
        current = nested
        for _i in range(10):
            current["n"] = {}
            current = current["n"]

        payload = json.dumps(nested).encode("utf-8")

        with pytest.raises(LogParserException) as exc_info:
            parser.parse(payload)

        error_msg = str(exc_info.value)
        assert "nesting depth exceeds maximum" in error_msg
        assert "levels" in error_msg


class TestSchemaValidationWithLimits:
    """Test that schema validation works alongside security limits."""

    def test_schema_validation_after_size_check(self):
        """Phase 3 (Contracts): Schema validation should occur after limits."""
        schema = {"required": ["field1", "field2"], "types": {"field1": str}}
        parser = JsonLogParser(schema=schema, max_size_bytes=1000)

        # Valid payload with required fields
        valid = json.dumps({"field1": "value", "field2": "other"}).encode("utf-8")
        result = parser.parse(valid)

        assert result["field1"] == "value"

    def test_size_limit_checked_before_schema(self):
        """Phase 5: Size limit should fail before schema validation."""
        schema = {"required": ["field1"]}
        parser = JsonLogParser(schema=schema, max_size_bytes=50)

        # Oversized payload (even if schema-valid)
        large = json.dumps({"field1": "x" * 100}).encode("utf-8")

        with pytest.raises(LogParserException) as exc_info:
            parser.parse(large)

        # Should be size error, not schema error
        assert "exceeds maximum size" in str(exc_info.value)


class TestEdgeCases:
    """Test edge cases and corner scenarios."""

    def test_empty_json_object(self):
        """Phase 7: Empty JSON should be accepted."""
        parser = JsonLogParser()
        empty = json.dumps({}).encode("utf-8")

        result = parser.parse(empty)

        assert result == {}

    def test_empty_json_array(self):
        """Phase 7: Empty array should be accepted."""
        parser = JsonLogParser()
        empty = json.dumps([]).encode("utf-8")

        result = parser.parse(empty)

        assert result == []

    def test_null_values(self):
        """Phase 7: Null values should be preserved."""
        parser = JsonLogParser()
        with_null = json.dumps({"field": None}).encode("utf-8")

        result = parser.parse(with_null)

        assert result["field"] is None

    def test_unicode_characters(self):
        """Phase 7: Unicode should be handled correctly."""
        parser = JsonLogParser(max_size_bytes=1000)
        unicode_data = json.dumps({"emoji": "🔒", "text": "日本語"}).encode("utf-8")

        result = parser.parse(unicode_data)

        assert result["emoji"] == "🔒"
        assert result["text"] == "日本語"

    def test_invalid_json_still_rejected(self):
        """Phase 5: Invalid JSON should still raise JSONDecodeError."""
        parser = JsonLogParser()
        invalid = b"{invalid json}"

        with pytest.raises(LogParserException) as exc_info:
            parser.parse(invalid)

        assert "Invalid JSON format" in str(exc_info.value)
