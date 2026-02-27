"""Runtime pipeline orchestration for S3 -> parser -> Sentinel routing."""

from __future__ import annotations

import asyncio
import logging
import signal
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.config.config_manager import ConfigManager
from src.core.log_parser import FirewallLogParser, JsonLogParser, LogParser
from src.core.s3_handler import S3Handler
from src.core.sentinel_router import SentinelRouter


@dataclass
class PipelineState:
    """Mutable runtime state used by health and metrics endpoints."""

    started_at: datetime
    last_success_time: Optional[datetime] = None
    last_error: Optional[str] = None
    running: bool = False
    ready: bool = False
    cycles_total: int = 0
    processed_files_total: int = 0
    failed_files_total: int = 0
    last_cycle_duration_seconds: float = 0.0


class PipelineRunner:
    """Runs ingestion cycles and updates shared runtime state."""

    def __init__(
        self,
        config_dir: str,
        environment: str,
        log_type: str,
        failed_batches_dir: str,
    ) -> None:
        self.config_dir = config_dir
        self.environment = environment
        self.log_type = log_type
        self.failed_batches_dir = Path(failed_batches_dir)
        self.logger = logging.getLogger(__name__)
        self.state = PipelineState(started_at=datetime.now(timezone.utc))
        self.stop_event = asyncio.Event()

        self._config_manager = ConfigManager(
            config_path=self.config_dir,
            environment=self.environment,
            enable_hot_reload=False,
        )
        aws = self._config_manager.get_aws_config()
        sentinel = self._config_manager.get_sentinel_config()

        self._s3_handler = S3Handler(
            aws_access_key=aws.access_key_id,
            aws_secret_key=aws.secret_access_key,
            region=aws.region,
            batch_size=aws.batch_size,
            max_retries=aws.max_retries,
            rate_limit=self._config_manager.get_config("aws").get("rate_limit"),
        )
        self._router = SentinelRouter(
            dcr_endpoint=sentinel.dcr_endpoint,
            rule_id=sentinel.rule_id,
            stream_name=sentinel.stream_name,
            batch_timeout=30,
        )
        self._parser = self._build_parser(log_type)

    @staticmethod
    def _build_parser(log_type: str) -> LogParser:
        if log_type == "firewall":
            return FirewallLogParser()
        if log_type == "json":
            return JsonLogParser()
        raise ValueError(f"Unsupported log type: {log_type}")

    def install_signal_handlers(self) -> None:
        """Install SIGINT/SIGTERM handlers for graceful shutdown."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        for sig_name in ("SIGINT", "SIGTERM"):
            sig = getattr(signal, sig_name, None)
            if sig is None:
                continue
            try:
                loop.add_signal_handler(sig, self.stop_event.set)
            except (NotImplementedError, RuntimeError):
                continue

    async def run_once(self) -> dict[str, Any]:
        """Run one ingest cycle."""
        started = time.monotonic()
        self.state.running = True
        self.state.cycles_total += 1

        aws = self._config_manager.get_aws_config()
        bucket = aws.bucket_name
        prefix = aws.prefix

        try:
            objects = await self._s3_handler.list_objects_async(bucket=bucket, prefix=prefix)

            async def _route_callback(parsed_batch: list[dict[str, Any]], callback_log_type: str) -> None:
                await self._router.route_logs(callback_log_type, parsed_batch)

            results = await self._s3_handler.process_files_batch_async(
                bucket=bucket,
                objects=objects,
                parser=self._parser,
                callback=_route_callback,
                log_type=self.log_type,
            )

            processed_count = len(results.get("successful", []))
            failed_count = len(results.get("failed", []))
            self.state.processed_files_total += processed_count
            self.state.failed_files_total += failed_count
            self.state.last_success_time = datetime.now(timezone.utc)
            self.state.last_error = None
            self.state.ready = True
            return results
        except Exception as exc:
            self.state.last_error = str(exc)
            self.state.ready = False
            self.logger.exception("Pipeline cycle failed: %s", exc)
            raise
        finally:
            self.state.last_cycle_duration_seconds = time.monotonic() - started

    async def run_forever(self, poll_interval_seconds: float) -> None:
        """Run ingest cycles until shutdown is requested."""
        self.install_signal_handlers()
        self.state.running = True
        while not self.stop_event.is_set():
            try:
                await self.run_once()
            except Exception:
                await asyncio.sleep(min(poll_interval_seconds, 5.0))
                continue

            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=poll_interval_seconds)
            except TimeoutError:
                pass

        self.state.running = False
