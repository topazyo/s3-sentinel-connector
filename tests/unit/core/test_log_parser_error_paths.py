"""Unit tests for parser error-path coverage (B3-006)."""

from datetime import datetime, timezone

import pytest

from src.core.log_parser import FirewallLogParser, LogParserException


class TestFirewallLogParserErrorPaths:
    """Error-path and validation coverage for FirewallLogParser."""

    def test_parse_raises_on_invalid_timestamp(self):
        parser = FirewallLogParser()
        payload = b"not-a-timestamp|192.168.1.1|10.0.0.1|ALLOW|r1|TCP|80|443|100"

        with pytest.raises(LogParserException) as exc_info:
            parser.parse(payload)

        assert "Failed to parse firewall log" in str(exc_info.value)
        assert "Unable to parse timestamp" in str(exc_info.value)

    def test_parse_raises_on_invalid_integer_field(self):
        parser = FirewallLogParser()
        payload = (
            b"2024-01-01T10:00:00Z|192.168.1.1|10.0.0.1|ALLOW|r1|TCP|bad-port|443|100"
        )

        with pytest.raises(LogParserException) as exc_info:
            parser.parse(payload)

        assert "Failed to parse firewall log" in str(exc_info.value)

    def test_parse_raises_on_non_utf8_payload(self):
        parser = FirewallLogParser()
        payload = b"\xff\xfe\xfa"

        with pytest.raises(LogParserException) as exc_info:
            parser.parse(payload)

        assert "Failed to parse firewall log" in str(exc_info.value)

    def test_validate_returns_false_when_required_field_missing(self):
        parser = FirewallLogParser()
        parsed = {
            "SourceIP": "192.168.1.1",
            "DestinationIP": "10.0.0.1",
            "FirewallAction": "allow",
        }

        assert parser.validate(parsed) is False

    def test_validate_returns_false_for_invalid_ip(self):
        parser = FirewallLogParser()
        parsed = {
            "TimeGenerated": datetime.now(timezone.utc),
            "SourceIP": "999.999.999.999",
            "DestinationIP": "10.0.0.1",
            "FirewallAction": "allow",
        }

        assert parser.validate(parsed) is False

    def test_validate_returns_false_for_invalid_action(self):
        parser = FirewallLogParser()
        parsed = {
            "TimeGenerated": datetime.now(timezone.utc),
            "SourceIP": "192.168.1.1",
            "DestinationIP": "10.0.0.1",
            "FirewallAction": "BLOCK",
        }

        assert parser.validate(parsed) is False
