# tests/unit/utils/test_validation.py
"""Unit tests for DataValidator — covers all validator types, error messages,
and ValidationRule dataclass.  Phase 7 gate: module was previously at 0% coverage."""

import pytest

from src.utils.validation import DataValidator, ValidationRule

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def validator():
    return DataValidator()


def _rule(field, rule_type, parameters=None, error_message=None):
    return ValidationRule(
        field=field,
        rule_type=rule_type,
        parameters=parameters or {},
        error_message=error_message,
    )


# ---------------------------------------------------------------------------
# validate() — top-level orchestration
# ---------------------------------------------------------------------------


class TestValidateOrchestration:
    def test_no_rules_returns_empty(self, validator):
        assert validator.validate({"x": 1}, []) == {}

    def test_unknown_rule_type_is_skipped(self, validator):
        rule = _rule("x", "nonexistent_rule")
        assert validator.validate({"x": 1}, [rule]) == {}

    def test_passing_rules_return_empty_dict(self, validator):
        rule = _rule("name", "required")
        errors = validator.validate({"name": "alice"}, [rule])
        assert errors == {}

    def test_custom_error_message_overrides_default(self, validator):
        rule = _rule("name", "required", error_message="Name is mandatory")
        errors = validator.validate({"name": None}, [rule])
        assert errors["name"] == ["Name is mandatory"]

    def test_multiple_errors_on_same_field_accumulate(self, validator):
        rules = [
            _rule("age", "type", {"type": "integer"}),
            _rule("age", "range", {"min": 0, "max": 150}),
        ]
        errors = validator.validate({"age": "old"}, rules)
        # "old" fails type check; range validator also tries float conversion and fails
        assert "age" in errors
        assert len(errors["age"]) >= 1

    def test_multiple_fields_separate_errors(self, validator):
        rules = [
            _rule("a", "required"),
            _rule("b", "required"),
        ]
        errors = validator.validate({"a": None, "b": None}, rules)
        assert "a" in errors
        assert "b" in errors


# ---------------------------------------------------------------------------
# Required validator
# ---------------------------------------------------------------------------


class TestRequiredValidator:
    def test_none_fails(self, validator):
        errors = validator.validate({"f": None}, [_rule("f", "required")])
        assert "f" in errors

    def test_empty_string_fails(self, validator):
        errors = validator.validate({"f": "   "}, [_rule("f", "required")])
        assert "f" in errors

    def test_non_empty_string_passes(self, validator):
        errors = validator.validate({"f": "value"}, [_rule("f", "required")])
        assert errors == {}

    def test_zero_passes(self, validator):
        """Numeric 0 is not None or empty string — should pass required."""
        errors = validator.validate({"f": 0}, [_rule("f", "required")])
        assert errors == {}


# ---------------------------------------------------------------------------
# Type validator
# ---------------------------------------------------------------------------


class TestTypeValidator:
    @pytest.mark.parametrize(
        "value,type_name",
        [
            ("hello", "string"),
            (42, "integer"),
            (3.14, "float"),
            (True, "boolean"),
            ([1, 2], "list"),
            ({"k": "v"}, "dict"),
        ],
    )
    def test_correct_type_passes(self, validator, value, type_name):
        errors = validator.validate(
            {"f": value}, [_rule("f", "type", {"type": type_name})]
        )
        assert errors == {}

    def test_wrong_type_fails(self, validator):
        errors = validator.validate(
            {"f": "hello"}, [_rule("f", "type", {"type": "integer"})]
        )
        assert "f" in errors
        assert "Expected type integer" in errors["f"][0]

    def test_none_value_passes_type_check(self, validator):
        """None values skip type validation (required check handles that)."""
        errors = validator.validate(
            {"f": None}, [_rule("f", "type", {"type": "integer"})]
        )
        assert errors == {}

    def test_unknown_type_name_passes(self, validator):
        """If type name is not in mapping, validator returns None (no error)."""
        errors = validator.validate({"f": "x"}, [_rule("f", "type", {"type": "uuid"})])
        assert errors == {}

    def test_missing_type_param_passes(self, validator):
        errors = validator.validate({"f": "x"}, [_rule("f", "type", {})])
        assert errors == {}


# ---------------------------------------------------------------------------
# Regex validator
# ---------------------------------------------------------------------------


class TestRegexValidator:
    def test_matching_pattern_passes(self, validator):
        errors = validator.validate(
            {"ip": "192.168.1.1"},
            [_rule("ip", "regex", {"pattern": r"^\d+\.\d+\.\d+\.\d+$"})],
        )
        assert errors == {}

    def test_non_matching_pattern_fails(self, validator):
        errors = validator.validate(
            {"ip": "not-an-ip"},
            [_rule("ip", "regex", {"pattern": r"^\d+\.\d+\.\d+\.\d+$"})],
        )
        assert "ip" in errors

    def test_none_value_skips_regex(self, validator):
        errors = validator.validate(
            {"ip": None},
            [_rule("ip", "regex", {"pattern": r"^\d+$"})],
        )
        assert errors == {}

    def test_no_pattern_param_skips(self, validator):
        errors = validator.validate({"f": "value"}, [_rule("f", "regex", {})])
        assert errors == {}


# ---------------------------------------------------------------------------
# Range validator
# ---------------------------------------------------------------------------


class TestRangeValidator:
    def test_within_range_passes(self, validator):
        errors = validator.validate(
            {"port": 8080},
            [_rule("port", "range", {"min": 1, "max": 65535})],
        )
        assert errors == {}

    def test_below_min_fails(self, validator):
        errors = validator.validate(
            {"port": 0},
            [_rule("port", "range", {"min": 1})],
        )
        assert "port" in errors

    def test_above_max_fails(self, validator):
        errors = validator.validate(
            {"port": 70000},
            [_rule("port", "range", {"max": 65535})],
        )
        assert "port" in errors

    def test_non_numeric_fails(self, validator):
        errors = validator.validate(
            {"port": "high"},
            [_rule("port", "range", {"min": 0})],
        )
        assert "port" in errors

    def test_none_value_skips(self, validator):
        errors = validator.validate({"f": None}, [_rule("f", "range", {"min": 0})])
        assert errors == {}

    def test_string_numeric_passes(self, validator):
        """String "80" should coerce to float 80 and pass range check."""
        errors = validator.validate(
            {"port": "80"},
            [_rule("port", "range", {"min": 1, "max": 65535})],
        )
        assert errors == {}


# ---------------------------------------------------------------------------
# Enum validator
# ---------------------------------------------------------------------------


class TestEnumValidator:
    def test_value_in_enum_passes(self, validator):
        errors = validator.validate(
            {"action": "ALLOW"},
            [_rule("action", "enum", {"values": ["ALLOW", "DENY"]})],
        )
        assert errors == {}

    def test_value_not_in_enum_fails(self, validator):
        errors = validator.validate(
            {"action": "MAYBE"},
            [_rule("action", "enum", {"values": ["ALLOW", "DENY"]})],
        )
        assert "action" in errors

    def test_none_value_skips(self, validator):
        errors = validator.validate(
            {"f": None}, [_rule("f", "enum", {"values": ["a"]})]
        )
        assert errors == {}


# ---------------------------------------------------------------------------
# IP validator
# ---------------------------------------------------------------------------


class TestIpValidator:
    def test_valid_ipv4_passes(self, validator):
        errors = validator.validate({"ip": "10.0.0.1"}, [_rule("ip", "ip")])
        assert errors == {}

    def test_valid_ipv6_passes(self, validator):
        errors = validator.validate({"ip": "2001:db8::1"}, [_rule("ip", "ip")])
        assert errors == {}

    def test_invalid_ip_fails(self, validator):
        errors = validator.validate({"ip": "999.999.999.999"}, [_rule("ip", "ip")])
        assert "ip" in errors

    def test_ipv4_version_constraint(self, validator):
        errors = validator.validate(
            {"ip": "::1"},
            [_rule("ip", "ip", {"version": 4})],
        )
        assert "ip" in errors

    def test_ipv6_version_constraint(self, validator):
        errors = validator.validate(
            {"ip": "192.168.1.1"},
            [_rule("ip", "ip", {"version": 6})],
        )
        assert "ip" in errors

    def test_empty_value_skips(self, validator):
        errors = validator.validate({"ip": ""}, [_rule("ip", "ip")])
        assert errors == {}


# ---------------------------------------------------------------------------
# Timestamp validator
# ---------------------------------------------------------------------------


class TestTimestampValidator:
    def test_valid_iso_passes(self, validator):
        errors = validator.validate(
            {"ts": "2024-01-15T12:30:00.000000Z"},
            [_rule("ts", "timestamp")],
        )
        assert errors == {}

    def test_invalid_format_fails(self, validator):
        errors = validator.validate(
            {"ts": "15/01/2024"},
            [_rule("ts", "timestamp")],
        )
        assert "ts" in errors

    def test_custom_formats(self, validator):
        errors = validator.validate(
            {"ts": "2024-01-15"},
            [_rule("ts", "timestamp", {"formats": ["%Y-%m-%d"]})],
        )
        assert errors == {}

    def test_empty_value_skips(self, validator):
        errors = validator.validate({"ts": ""}, [_rule("ts", "timestamp")])
        assert errors == {}


# ---------------------------------------------------------------------------
# Length validator
# ---------------------------------------------------------------------------


class TestLengthValidator:
    def test_within_length_passes(self, validator):
        errors = validator.validate(
            {"name": "alice"},
            [_rule("name", "length", {"min": 1, "max": 50})],
        )
        assert errors == {}

    def test_below_min_length_fails(self, validator):
        errors = validator.validate(
            {"name": ""},
            [_rule("name", "length", {"min": 1})],
        )
        assert "name" in errors

    def test_above_max_length_fails(self, validator):
        errors = validator.validate(
            {"name": "a" * 101},
            [_rule("name", "length", {"max": 100})],
        )
        assert "name" in errors

    def test_none_value_skips(self, validator):
        errors = validator.validate({"f": None}, [_rule("f", "length", {"min": 1})])
        assert errors == {}

    def test_list_length_checked(self, validator):
        errors = validator.validate(
            {"tags": ["a", "b", "c"]},
            [_rule("tags", "length", {"max": 2})],
        )
        assert "tags" in errors

    def test_no_len_type_fails(self, validator):
        """Integers have no len() — should return error."""
        errors = validator.validate(
            {"f": 42},
            [_rule("f", "length", {"min": 1})],
        )
        assert "f" in errors


# ---------------------------------------------------------------------------
# Custom validator
# ---------------------------------------------------------------------------


class TestCustomValidator:
    def test_callable_returning_true_passes(self, validator):
        """Callable must return a truthy non-string value to indicate pass."""
        errors = validator.validate(
            {"f": "good"},
            [_rule("f", "custom", {"function": lambda v: True})],
        )
        assert errors == {}

    def test_callable_returning_none_fails(self, validator):
        """None is falsy — treated as validation failure by _validate_custom."""
        errors = validator.validate(
            {"f": "good"},
            [_rule("f", "custom", {"function": lambda v: None})],
        )
        assert "f" in errors

    def test_callable_returning_string_fails(self, validator):
        errors = validator.validate(
            {"f": "bad"},
            [_rule("f", "custom", {"function": lambda v: "Custom error"})],
        )
        assert "f" in errors
        assert "Custom error" in errors["f"][0]

    def test_callable_returning_false_fails(self, validator):
        errors = validator.validate(
            {"f": "x"},
            [_rule("f", "custom", {"function": lambda v: False})],
        )
        assert "f" in errors

    def test_no_callable_skips(self, validator):
        errors = validator.validate({"f": "x"}, [_rule("f", "custom", {})])
        assert errors == {}

    def test_callable_raises_returns_error(self, validator):
        def bad(v):
            raise RuntimeError("boom")

        errors = validator.validate(
            {"f": "x"}, [_rule("f", "custom", {"function": bad})]
        )
        assert "f" in errors


# ---------------------------------------------------------------------------
# ValidationRule dataclass
# ---------------------------------------------------------------------------


class TestValidationRuleDataclass:
    def test_defaults(self):
        rule = ValidationRule(field="x", rule_type="required")
        assert rule.parameters is None
        assert rule.error_message is None

    def test_with_all_fields(self):
        rule = ValidationRule(
            field="port",
            rule_type="range",
            parameters={"min": 1, "max": 65535},
            error_message="Port out of range",
        )
        assert rule.field == "port"
        assert rule.parameters["min"] == 1
