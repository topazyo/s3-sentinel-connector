# tests/unit/utils/test_transformations.py
"""Unit tests for DataTransformer — covers all transform types, error paths, and
required-field enforcement.  Phase 7 gate: this module was previously at 0% coverage."""

from datetime import datetime

import pytest

from src.utils.transformations import DataTransformer

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def transformer():
    return DataTransformer()


# ---------------------------------------------------------------------------
# transform() — top-level orchestration
# ---------------------------------------------------------------------------


class TestTransformOrchestration:
    def test_optional_field_missing_is_skipped(self, transformer):
        result = transformer.transform(
            {},
            {"src": {"type": "string", "required": False}},
        )
        assert "src" not in result

    def test_required_field_missing_raises(self, transformer):
        with pytest.raises(ValueError, match="Failed to transform field src"):
            transformer.transform(
                {},
                {"src": {"type": "integer", "required": True}},
            )

    def test_target_field_rename(self, transformer):
        result = transformer.transform(
            {"raw": "42"},
            {"raw": {"type": "integer", "target_field": "count"}},
        )
        assert result == {"count": 42}

    def test_unknown_type_skips_field(self, transformer):
        """Unknown transform type has no transformer — field silently skipped."""
        result = transformer.transform(
            {"x": "value"},
            {"x": {"type": "nonexistent"}},
        )
        assert "x" not in result

    def test_transform_error_on_optional_field_continues(self, transformer):
        """Transformation failure on an optional field does not raise — field is skipped."""
        result = transformer.transform(
            {"port": "not-an-int"},
            {"port": {"type": "integer", "required": False}},
        )
        assert "port" not in result

    def test_multiple_fields_transformed(self, transformer):
        result = transformer.transform(
            {"port": "443", "host": "  example.com  "},
            {
                "port": {"type": "integer"},
                "host": {"type": "string"},
            },
        )
        assert result == {"port": 443, "host": "example.com"}


# ---------------------------------------------------------------------------
# Timestamp transformer
# ---------------------------------------------------------------------------


class TestTimestampTransformer:
    def test_datetime_object_iso(self, transformer):
        dt = datetime(2024, 1, 15, 12, 30, 0)
        result = transformer.transform(
            {"ts": dt},
            {"ts": {"type": "timestamp"}},
        )
        assert result["ts"] == dt.isoformat()

    def test_string_default_format(self, transformer):
        result = transformer.transform(
            {"ts": "2024-01-15T12:30:00.000000Z"},
            {"ts": {"type": "timestamp"}},
        )
        assert "2024-01-15" in result["ts"]

    def test_string_space_separated_format(self, transformer):
        result = transformer.transform(
            {"ts": "2024-01-15 12:30:00"},
            {"ts": {"type": "timestamp"}},
        )
        assert "2024-01-15" in result["ts"]

    def test_custom_input_and_output_format(self, transformer):
        result = transformer.transform(
            {"ts": "Jan 15 2024 12:30:00"},
            {
                "ts": {
                    "type": "timestamp",
                    "parameters": {
                        "input_formats": ["%b %d %Y %H:%M:%S"],
                        "output_format": "%Y-%m-%d",
                    },
                }
            },
        )
        assert result["ts"] == "2024-01-15"

    def test_unparseable_timestamp_raises(self, transformer):
        with pytest.raises(ValueError, match="Unable to parse timestamp"):
            transformer.transform(
                {"ts": "not-a-date"},
                {"ts": {"type": "timestamp", "required": True}},
            )


# ---------------------------------------------------------------------------
# IP transformer
# ---------------------------------------------------------------------------


class TestIpTransformer:
    def test_valid_ipv4(self, transformer):
        result = transformer.transform({"ip": "192.168.1.1"}, {"ip": {"type": "ip"}})
        assert result["ip"] == "192.168.1.1"

    def test_valid_ipv6(self, transformer):
        result = transformer.transform({"ip": "::1"}, {"ip": {"type": "ip"}})
        assert result["ip"] == "::1"

    def test_invalid_ip_raises(self, transformer):
        with pytest.raises(ValueError, match="Invalid IP address"):
            transformer.transform(
                {"ip": "not.an.ip"},
                {"ip": {"type": "ip", "required": True}},
            )


# ---------------------------------------------------------------------------
# Numeric transformers
# ---------------------------------------------------------------------------


class TestNumericTransformers:
    def test_integer_from_string(self, transformer):
        result = transformer.transform({"n": "99"}, {"n": {"type": "integer"}})
        assert result["n"] == 99

    def test_integer_invalid_raises(self, transformer):
        with pytest.raises(ValueError, match="Unable to convert to integer"):
            transformer.transform(
                {"n": "abc"},
                {"n": {"type": "integer", "required": True}},
            )

    def test_float_from_string(self, transformer):
        result = transformer.transform({"f": "3.14"}, {"f": {"type": "float"}})
        assert abs(result["f"] - 3.14) < 0.001

    def test_float_invalid_raises(self, transformer):
        with pytest.raises(ValueError, match="Unable to convert to float"):
            transformer.transform(
                {"f": "xyz"},
                {"f": {"type": "float", "required": True}},
            )


# ---------------------------------------------------------------------------
# Boolean transformer
# ---------------------------------------------------------------------------


class TestBooleanTransformer:
    @pytest.mark.parametrize("value", [True, False])
    def test_bool_passthrough(self, transformer, value):
        result = transformer.transform({"b": value}, {"b": {"type": "boolean"}})
        assert result["b"] is value

    @pytest.mark.parametrize(
        "val,expected",
        [
            ("true", True),
            ("1", True),
            ("yes", True),
            ("on", True),
            ("false", False),
            ("0", False),
            ("no", False),
            ("off", False),
        ],
    )
    def test_string_to_bool(self, transformer, val, expected):
        result = transformer.transform({"b": val}, {"b": {"type": "boolean"}})
        assert result["b"] is expected

    def test_invalid_boolean_raises(self, transformer):
        with pytest.raises(ValueError, match="Unable to convert to boolean"):
            transformer.transform(
                {"b": "maybe"},
                {"b": {"type": "boolean", "required": True}},
            )

    def test_custom_true_false_values(self, transformer):
        result = transformer.transform(
            {"b": "enabled"},
            {
                "b": {
                    "type": "boolean",
                    "parameters": {
                        "true_values": ["enabled"],
                        "false_values": ["disabled"],
                    },
                }
            },
        )
        assert result["b"] is True


# ---------------------------------------------------------------------------
# String transformer
# ---------------------------------------------------------------------------


class TestStringTransformer:
    def test_strip_default(self, transformer):
        result = transformer.transform({"s": "  hello  "}, {"s": {"type": "string"}})
        assert result["s"] == "hello"

    def test_upper(self, transformer):
        result = transformer.transform(
            {"s": "hello"},
            {"s": {"type": "string", "parameters": {"upper": True}}},
        )
        assert result["s"] == "HELLO"

    def test_lower(self, transformer):
        result = transformer.transform(
            {"s": "HELLO"},
            {"s": {"type": "string", "parameters": {"lower": True}}},
        )
        assert result["s"] == "hello"

    def test_replace(self, transformer):
        result = transformer.transform(
            {"s": "foo bar"},
            {"s": {"type": "string", "parameters": {"replace": {"foo": "baz"}}}},
        )
        assert result["s"] == "baz bar"

    def test_none_optional_field_skipped(self, transformer):
        """The orchestrator skips optional None fields before calling _transform_string."""
        result = transformer.transform(
            {"s": None},
            {"s": {"type": "string"}},
        )
        assert "s" not in result

    def test_none_required_field_returns_empty_string(self, transformer):
        """When required=True, None is passed to _transform_string which returns ''."""
        result = transformer.transform(
            {"s": None},
            {"s": {"type": "string", "required": True}},
        )
        assert result["s"] == ""


# ---------------------------------------------------------------------------
# JSON transformer
# ---------------------------------------------------------------------------


class TestJsonTransformer:
    def test_dict_passthrough(self, transformer):
        d = {"key": "val"}
        result = transformer.transform({"j": d}, {"j": {"type": "json"}})
        assert result["j"] == d

    def test_json_string_parsed(self, transformer):
        result = transformer.transform(
            {"j": '{"key": "val"}'},
            {"j": {"type": "json"}},
        )
        assert result["j"] == {"key": "val"}

    def test_invalid_json_raises(self, transformer):
        with pytest.raises(ValueError, match="Unable to parse JSON"):
            transformer.transform(
                {"j": "not-json"},
                {"j": {"type": "json", "required": True}},
            )


# ---------------------------------------------------------------------------
# List transformer
# ---------------------------------------------------------------------------


class TestListTransformer:
    def test_list_passthrough(self, transformer):
        lst = [1, 2, 3]
        result = transformer.transform({"l": lst}, {"l": {"type": "list"}})
        assert result["l"] == lst

    def test_comma_separated_string(self, transformer):
        result = transformer.transform({"l": "a, b, c"}, {"l": {"type": "list"}})
        assert result["l"] == ["a", "b", "c"]

    def test_custom_separator(self, transformer):
        result = transformer.transform(
            {"l": "a|b|c"},
            {"l": {"type": "list", "parameters": {"separator": "|"}}},
        )
        assert result["l"] == ["a", "b", "c"]

    def test_non_list_non_string_raises(self, transformer):
        with pytest.raises(ValueError, match="Unable to convert to list"):
            transformer.transform(
                {"l": 42},
                {"l": {"type": "list", "required": True}},
            )


# ---------------------------------------------------------------------------
# Map transformer
# ---------------------------------------------------------------------------


class TestMapTransformer:
    def test_mapping_found(self, transformer):
        result = transformer.transform(
            {"action": "ALLOW"},
            {
                "action": {
                    "type": "map",
                    "parameters": {"mapping": {"ALLOW": "permit", "DENY": "block"}},
                }
            },
        )
        assert result["action"] == "permit"

    def test_mapping_default(self, transformer):
        result = transformer.transform(
            {"action": "UNKNOWN"},
            {
                "action": {
                    "type": "map",
                    "parameters": {
                        "mapping": {"ALLOW": "permit"},
                        "default": "unknown",
                    },
                }
            },
        )
        assert result["action"] == "unknown"

    def test_mapping_no_match_no_default_returns_none(self, transformer):
        result = transformer.transform(
            {"action": "UNKNOWN"},
            {
                "action": {
                    "type": "map",
                    "parameters": {"mapping": {"ALLOW": "permit"}},
                }
            },
        )
        assert result["action"] is None
