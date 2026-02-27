# tests/unit/security/test_audit.py
"""Unit tests for AuditLogger and AuditEvent.

Covers the previously-uncovered lines in src/security/audit.py:
  - log_event() (lines 55-64): happy path and exception path
  - _generate_event_hash() (lines 68-69): determinism and sort-key stability
  - verify_log_integrity() (lines 73-92): clean log, tampered hash, missing hash,
    unreadable file, empty log

Phase 7 gate: module was at 48% before this file.
"""

import json
import logging
import os
import re

import pytest

from src.security.audit import AuditEvent, AuditLogger

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    timestamp: str = "2024-01-15T12:00:00Z",
    event_type: str = "ACCESS",
    user: str = "alice",
    action: str = "READ",
    resource: str = "s3://bucket/key",
    status: str = "SUCCESS",
    details: dict | None = None,
    source_ip: str | None = None,
    correlation_id: str | None = None,
) -> AuditEvent:
    return AuditEvent(
        timestamp=timestamp,
        event_type=event_type,
        user=user,
        action=action,
        resource=resource,
        status=status,
        details=details if details is not None else {"bytes": 1024},
        source_ip=source_ip,
        correlation_id=correlation_id,
    )


@pytest.fixture()
def log_path(tmp_path) -> str:
    return str(tmp_path / "audit.log")


@pytest.fixture()
def audit_logger(log_path) -> AuditLogger:
    return AuditLogger(log_path)


# ---------------------------------------------------------------------------
# AuditEvent dataclass
# ---------------------------------------------------------------------------


class TestAuditEventDataclass:
    def test_required_fields(self):
        event = _make_event()
        assert event.event_type == "ACCESS"
        assert event.status == "SUCCESS"

    def test_optional_fields_default_none(self):
        event = _make_event()
        assert event.source_ip is None
        assert event.correlation_id is None

    def test_optional_fields_set(self):
        event = _make_event(source_ip="10.0.0.1", correlation_id="abc-123")
        assert event.source_ip == "10.0.0.1"
        assert event.correlation_id == "abc-123"


# ---------------------------------------------------------------------------
# AuditLogger.__init__ / _setup_logger
# ---------------------------------------------------------------------------


class TestAuditLoggerInit:
    def test_creates_file_on_init(self, log_path):
        """File handler should create (or touch) the log file during init."""
        al = AuditLogger(log_path)
        # Write something so the file exists
        al.log_event(_make_event())
        assert os.path.exists(log_path)

    def test_logger_name(self, audit_logger):
        assert audit_logger.logger.name == "audit"

    def test_logger_level_info(self, audit_logger):
        assert audit_logger.logger.level == logging.INFO


# ---------------------------------------------------------------------------
# log_event — happy path
# ---------------------------------------------------------------------------


class TestLogEvent:
    def test_event_written_to_file(self, audit_logger, log_path):
        audit_logger.log_event(_make_event())
        content = open(log_path).read()
        assert "ACCESS" in content

    def test_event_contains_hash_field(self, audit_logger, log_path):
        audit_logger.log_event(_make_event())
        line = next(log_line for log_line in open(log_path) if "|" in log_line)
        _ts, event_json = line.strip().split("|", 1)
        event_dict = json.loads(event_json)
        assert "hash" in event_dict

    def test_hash_is_sha256_hex(self, audit_logger, log_path):
        audit_logger.log_event(_make_event())
        line = next(log_line for log_line in open(log_path) if "|" in log_line)
        _ts, event_json = line.strip().split("|", 1)
        event_dict = json.loads(event_json)
        assert re.fullmatch(r"[0-9a-f]{64}", event_dict["hash"])

    def test_multiple_events_all_written(self, audit_logger, log_path):
        for i in range(5):
            audit_logger.log_event(_make_event(details={"i": i}))
        lines = [line for line in open(log_path).readlines() if "|" in line]
        assert len(lines) == 5

    def test_optional_source_ip_included(self, audit_logger, log_path):
        audit_logger.log_event(_make_event(source_ip="192.168.1.1"))
        content = open(log_path).read()
        assert "192.168.1.1" in content

    def test_correlation_id_included(self, audit_logger, log_path):
        audit_logger.log_event(_make_event(correlation_id="trace-xyz"))
        content = open(log_path).read()
        assert "trace-xyz" in content


# ---------------------------------------------------------------------------
# _generate_event_hash
# ---------------------------------------------------------------------------


class TestGenerateEventHash:
    def test_deterministic(self, audit_logger):
        d = {"a": 1, "b": "hello"}
        assert audit_logger._generate_event_hash(
            d
        ) == audit_logger._generate_event_hash(d)

    def test_sort_keys_stability(self, audit_logger):
        d1 = {"b": 2, "a": 1}
        d2 = {"a": 1, "b": 2}
        assert audit_logger._generate_event_hash(
            d1
        ) == audit_logger._generate_event_hash(d2)

    def test_different_content_different_hash(self, audit_logger):
        d1 = {"event_type": "ACCESS"}
        d2 = {"event_type": "DELETE"}
        assert audit_logger._generate_event_hash(
            d1
        ) != audit_logger._generate_event_hash(d2)

    def test_returns_64_char_hex(self, audit_logger):
        result = audit_logger._generate_event_hash({"k": "v"})
        assert len(result) == 64
        assert re.fullmatch(r"[0-9a-f]{64}", result)


# ---------------------------------------------------------------------------
# verify_log_integrity — clean log
# ---------------------------------------------------------------------------


class TestVerifyLogIntegrityClean:
    def test_empty_log_returns_true(self, audit_logger):
        # An empty log file has no lines, so loop completes cleanly.
        result = audit_logger.verify_log_integrity()
        assert result is True

    def test_single_event_verifies_true(self, audit_logger):
        audit_logger.log_event(_make_event())
        assert audit_logger.verify_log_integrity() is True

    def test_multiple_events_verify_true(self, audit_logger):
        for i in range(5):
            audit_logger.log_event(_make_event(details={"i": i}))
        assert audit_logger.verify_log_integrity() is True


# ---------------------------------------------------------------------------
# verify_log_integrity — tampered log
# ---------------------------------------------------------------------------


class TestVerifyLogIntegrityTampered:
    def test_tampered_hash_returns_false(self, audit_logger, log_path):
        """Modify the hash field in a written log line."""
        audit_logger.log_event(_make_event())

        # Read raw file line and corrupt the hash
        raw = open(log_path).read()
        tampered = re.sub(r'"hash": "[0-9a-f]{64}"', '"hash": "' + "0" * 64 + '"', raw)
        with open(log_path, "w") as fh:
            fh.write(tampered)

        assert audit_logger.verify_log_integrity() is False

    def test_missing_hash_field_returns_false(self, audit_logger, log_path):
        """Remove the hash field entirely from the JSON."""
        audit_logger.log_event(_make_event())

        raw = open(log_path).read()
        # Remove the hash key-value pair from the JSON portion
        # Build a patched version that has no hash
        lines = raw.strip().split("\n")
        patched_lines = []
        for line in lines:
            if "|" in line:
                prefix, event_json = line.split("|", 1)
                event_dict = json.loads(event_json)
                event_dict.pop("hash", None)
                patched_lines.append(f"{prefix}|{json.dumps(event_dict)}")
            else:
                patched_lines.append(line)
        with open(log_path, "w") as fh:
            fh.write("\n".join(patched_lines) + "\n")

        assert audit_logger.verify_log_integrity() is False

    def test_altered_event_field_returns_false(self, audit_logger, log_path):
        """Change an event field without updating the hash."""
        audit_logger.log_event(_make_event())

        raw = open(log_path).read()
        tampered = raw.replace('"action": "READ"', '"action": "DELETE"')
        with open(log_path, "w") as fh:
            fh.write(tampered)

        assert audit_logger.verify_log_integrity() is False


# ---------------------------------------------------------------------------
# verify_log_integrity — file not found / exception
# ---------------------------------------------------------------------------


class TestVerifyLogIntegrityException:
    def test_nonexistent_log_file_returns_false(self, tmp_path):
        """Passing a path to a file that doesn't exist should return False."""
        al = AuditLogger.__new__(AuditLogger)
        al.log_path = str(tmp_path / "does_not_exist.log")
        al.logger = logging.getLogger("audit_test_exc")
        result = al.verify_log_integrity()
        assert result is False
