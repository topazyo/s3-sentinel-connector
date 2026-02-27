"""Console entrypoint for s3-sentinel-connector."""

from __future__ import annotations

import argparse
import asyncio
from importlib import metadata

from src.config.config_manager import ConfigManager
from src.core.sentinel_router import SentinelRouter

from s3_sentinel import __version__
from s3_sentinel.pipeline import PipelineRunner
from s3_sentinel.replay import replay_failed_batches
from s3_sentinel.server import HealthServer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="s3-sentinel",
        description="S3 to Microsoft Sentinel connector utilities",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print package version and exit.",
    )

    subparsers = parser.add_subparsers(dest="command")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config-dir", default="config", help="Configuration directory path.")
    common.add_argument(
        "--environment",
        default="dev",
        choices=["dev", "prod"],
        help="Configuration environment to load.",
    )
    common.add_argument(
        "--log-type",
        default="firewall",
        choices=["firewall", "json"],
        help="Log parser and router type.",
    )

    run_parser = subparsers.add_parser("run", parents=[common], help="Run connector as a long-lived service.")
    run_parser.add_argument("--poll-interval", type=float, default=30.0, help="Polling interval in seconds.")
    run_parser.add_argument("--failed-batches-dir", default="failed_batches", help="Directory for failed batch payload files.")

    ingest_parser = subparsers.add_parser("ingest", parents=[common], help="Run one ingestion cycle and exit.")
    ingest_parser.add_argument("--failed-batches-dir", default="failed_batches", help="Directory for failed batch payload files.")

    validate_parser = subparsers.add_parser("validate-config", help="Validate configuration and exit.")
    validate_parser.add_argument("--config-dir", default="config", help="Configuration directory path.")
    validate_parser.add_argument(
        "--environment",
        default="dev",
        choices=["dev", "prod"],
        help="Configuration environment to validate.",
    )

    replay_parser = subparsers.add_parser("replay-failed", parents=[common], help="Replay failed batch files and archive successful replays.")
    replay_parser.add_argument("--failed-batches-dir", default="failed_batches", help="Directory with failed batch JSON files.")

    return parser


def _resolve_version() -> str:
    try:
        return metadata.version("s3-sentinel-connector")
    except metadata.PackageNotFoundError:
        return __version__


def _validate_config(config_dir: str, environment: str) -> None:
    ConfigManager(config_path=config_dir, environment=environment, enable_hot_reload=False)


async def _run_command(args: argparse.Namespace) -> int:
    runner = PipelineRunner(
        config_dir=args.config_dir,
        environment=args.environment,
        log_type=args.log_type,
        failed_batches_dir=args.failed_batches_dir,
    )
    server = HealthServer(runner.state, failed_batches_dir=args.failed_batches_dir)
    await server.start()
    try:
        await runner.run_forever(poll_interval_seconds=args.poll_interval)
    finally:
        await server.stop()
    return 0


async def _ingest_command(args: argparse.Namespace) -> int:
    runner = PipelineRunner(
        config_dir=args.config_dir,
        environment=args.environment,
        log_type=args.log_type,
        failed_batches_dir=args.failed_batches_dir,
    )
    await runner.run_once()
    return 0


async def _replay_command(args: argparse.Namespace) -> int:
    config_manager = ConfigManager(
        config_path=args.config_dir,
        environment=args.environment,
        enable_hot_reload=False,
    )
    sentinel = config_manager.get_sentinel_config()
    router = SentinelRouter(
        dcr_endpoint=sentinel.dcr_endpoint,
        rule_id=sentinel.rule_id,
        stream_name=sentinel.stream_name,
    )
    results = await replay_failed_batches(
        router=router,
        log_type=args.log_type,
        failed_batches_dir=args.failed_batches_dir,
    )
    print(
        "Replay complete:",
        f"processed={results['processed']}",
        f"archived={results['archived']}",
        f"failed={results['failed']}",
    )
    return 0 if results["failed"] == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        print(f"s3-sentinel-connector {_resolve_version()}")
        return 0

    if args.command == "validate-config":
        _validate_config(args.config_dir, args.environment)
        print("Configuration is valid")
        return 0

    if args.command == "run":
        return asyncio.run(_run_command(args))

    if args.command == "ingest":
        return asyncio.run(_ingest_command(args))

    if args.command == "replay-failed":
        return asyncio.run(_replay_command(args))

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
