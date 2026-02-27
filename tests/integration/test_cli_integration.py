"""Integration-style CLI command path coverage for operational subcommands."""

from __future__ import annotations

import argparse

from src.s3_sentinel import cli


def test_cli_run_command_receives_runtime_args(monkeypatch):
    captured = {}

    async def fake_run(args: argparse.Namespace) -> int:
        captured["args"] = args
        return 0

    monkeypatch.setattr(cli, "_run_command", fake_run)

    exit_code = cli.main(
        [
            "run",
            "--config-dir",
            "config",
            "--environment",
            "dev",
            "--log-type",
            "firewall",
            "--poll-interval",
            "5",
            "--failed-batches-dir",
            "failed_batches",
        ]
    )

    assert exit_code == 0
    assert captured["args"].command == "run"
    assert captured["args"].poll_interval == 5.0
    assert captured["args"].log_type == "firewall"


def test_cli_ingest_command_receives_one_shot_args(monkeypatch):
    captured = {}

    async def fake_ingest(args: argparse.Namespace) -> int:
        captured["args"] = args
        return 0

    monkeypatch.setattr(cli, "_ingest_command", fake_ingest)

    exit_code = cli.main(
        [
            "ingest",
            "--config-dir",
            "config",
            "--environment",
            "prod",
            "--log-type",
            "json",
            "--failed-batches-dir",
            "failed_batches",
        ]
    )

    assert exit_code == 0
    assert captured["args"].command == "ingest"
    assert captured["args"].environment == "prod"
    assert captured["args"].log_type == "json"


def test_cli_replay_failed_command_uses_directory_and_log_type(monkeypatch):
    captured = {}

    async def fake_replay(args: argparse.Namespace) -> int:
        captured["args"] = args
        return 0

    monkeypatch.setattr(cli, "_replay_command", fake_replay)

    exit_code = cli.main(
        [
            "replay-failed",
            "--config-dir",
            "config",
            "--environment",
            "prod",
            "--log-type",
            "firewall",
            "--failed-batches-dir",
            "failed_batches",
        ]
    )

    assert exit_code == 0
    assert captured["args"].command == "replay-failed"
    assert captured["args"].failed_batches_dir == "failed_batches"


def test_cli_validate_config_integration_path(monkeypatch, capsys):
    invoked = {}

    def fake_validate(config_dir: str, environment: str) -> None:
        invoked["config_dir"] = config_dir
        invoked["environment"] = environment

    monkeypatch.setattr(cli, "_validate_config", fake_validate)

    exit_code = cli.main(
        ["validate-config", "--config-dir", "config", "--environment", "prod"]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert invoked["config_dir"] == "config"
    assert invoked["environment"] == "prod"
    assert "Configuration is valid" in captured.out
