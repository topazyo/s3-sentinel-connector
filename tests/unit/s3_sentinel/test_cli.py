"""Unit tests for s3_sentinel.cli."""

from __future__ import annotations

import asyncio
from importlib import metadata

import pytest

from s3_sentinel import cli


def test_main_prints_version_from_metadata(monkeypatch, capsys):
    monkeypatch.setattr(metadata, "version", lambda _: "9.9.9")

    exit_code = cli.main(["--version"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip() == "s3-sentinel-connector 9.9.9"


def test_main_prints_version_from_fallback_when_not_installed(monkeypatch, capsys):
    def _raise_not_found(_: str):
        raise metadata.PackageNotFoundError

    monkeypatch.setattr(metadata, "version", _raise_not_found)

    exit_code = cli.main(["--version"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip() == "s3-sentinel-connector 1.1.0"


def test_main_prints_help_without_args(capsys):
    exit_code = cli.main([])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "S3 to Microsoft Sentinel connector utilities" in captured.out


def test_main_validate_config_invokes_validator(monkeypatch, capsys):
    calls = {"count": 0}

    def _fake_validate(config_dir: str, environment: str) -> None:
        calls["count"] += 1
        assert config_dir == "config"
        assert environment == "dev"

    monkeypatch.setattr(cli, "_validate_config", _fake_validate)

    exit_code = cli.main(["validate-config"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert calls["count"] == 1
    assert "Configuration is valid" in captured.out


def test_main_run_dispatches_async_command(monkeypatch):
    async def _fake_run(_: object) -> int:
        return 0

    monkeypatch.setattr(cli, "_run_command", _fake_run)

    def _fake_asyncio_run(coro):
        coro.close()
        return 0

    monkeypatch.setattr(asyncio, "run", _fake_asyncio_run)

    exit_code = cli.main(["run"])
    assert exit_code == 0


def test_main_ingest_dispatches_async_command(monkeypatch):
    async def _fake_ingest(_: object) -> int:
        return 0

    monkeypatch.setattr(cli, "_ingest_command", _fake_ingest)

    def _fake_asyncio_run(coro):
        coro.close()
        return 0

    monkeypatch.setattr(asyncio, "run", _fake_asyncio_run)

    exit_code = cli.main(["ingest"])
    assert exit_code == 0


def test_main_replay_dispatches_async_command(monkeypatch):
    async def _fake_replay(_: object) -> int:
        return 0

    monkeypatch.setattr(cli, "_replay_command", _fake_replay)

    def _fake_asyncio_run(coro):
        coro.close()
        return 0

    monkeypatch.setattr(asyncio, "run", _fake_asyncio_run)

    exit_code = cli.main(["replay-failed"])
    assert exit_code == 0
