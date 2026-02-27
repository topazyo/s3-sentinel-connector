"""HTTP health/readiness/metrics server for runtime operations."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from aiohttp import web
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest

from .pipeline import PipelineState

PIPELINE_CYCLES_TOTAL = Counter(
    "s3_sentinel_pipeline_cycles_total",
    "Total completed ingest cycles.",
)
PROCESSED_FILES_TOTAL = Counter(
    "s3_sentinel_processed_files_total",
    "Total successfully processed files.",
)
FAILED_FILES_TOTAL = Counter(
    "s3_sentinel_failed_files_total",
    "Total failed files across cycles.",
)
LAST_CYCLE_DURATION = Gauge(
    "s3_sentinel_last_cycle_duration_seconds",
    "Duration of most recent cycle in seconds.",
)
READINESS_GAUGE = Gauge(
    "s3_sentinel_ready",
    "Readiness status (1 ready, 0 not ready).",
)
FAILED_BATCH_FILES = Gauge(
    "s3_sentinel_failed_batch_files",
    "Number of failed batch files currently on disk.",
)
FAILED_BATCH_OLDEST_AGE = Gauge(
    "s3_sentinel_failed_batch_oldest_age_seconds",
    "Age in seconds of oldest failed batch file.",
)


class HealthServer:
    """Serves health/readiness and Prometheus metrics."""

    def __init__(
        self,
        state: PipelineState,
        failed_batches_dir: str,
        health_port: int = 8080,
        metrics_port: int = 9090,
    ) -> None:
        self._state = state
        self._failed_batches_dir = Path(failed_batches_dir)
        self._health_port = health_port
        self._metrics_port = metrics_port
        self._runner: web.AppRunner | None = None
        self._sites: list[web.TCPSite] = []

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get("/health", self.health)
        app.router.add_get("/ready", self.ready)
        app.router.add_get("/metrics", self.metrics)

        self._runner = web.AppRunner(app)
        await self._runner.setup()

        self._sites = [
            web.TCPSite(self._runner, "0.0.0.0", self._health_port),
            web.TCPSite(self._runner, "0.0.0.0", self._metrics_port),
        ]
        for site in self._sites:
            await site.start()

    async def stop(self) -> None:
        if self._runner is None:
            return
        await self._runner.cleanup()
        self._runner = None
        self._sites = []

    async def health(self, _: web.Request) -> web.Response:
        payload = {
            "status": "ok",
            "running": self._state.running,
            "started_at": self._state.started_at.isoformat(),
        }
        return web.json_response(payload, status=200)

    async def ready(self, _: web.Request) -> web.Response:
        status = 200 if self._state.ready else 503
        payload = {
            "ready": self._state.ready,
            "last_success_time": (
                self._state.last_success_time.isoformat()
                if self._state.last_success_time
                else None
            ),
            "last_error": self._state.last_error,
        }
        return web.json_response(payload, status=status)

    async def metrics(self, _: web.Request) -> web.Response:
        self._sync_metric_values()
        output = generate_latest()
        return web.Response(body=output, headers={"Content-Type": CONTENT_TYPE_LATEST})

    def _sync_metric_values(self) -> None:
        READINESS_GAUGE.set(1 if self._state.ready else 0)
        LAST_CYCLE_DURATION.set(self._state.last_cycle_duration_seconds)

        cycle_delta = self._state.cycles_total - getattr(
            self, "_last_cycles_total", 0
        )
        if cycle_delta > 0:
            PIPELINE_CYCLES_TOTAL.inc(cycle_delta)
        self._last_cycles_total = self._state.cycles_total

        processed_delta = self._state.processed_files_total - getattr(
            self, "_last_processed_total", 0
        )
        if processed_delta > 0:
            PROCESSED_FILES_TOTAL.inc(processed_delta)
        self._last_processed_total = self._state.processed_files_total

        failed_delta = self._state.failed_files_total - getattr(
            self, "_last_failed_total", 0
        )
        if failed_delta > 0:
            FAILED_FILES_TOTAL.inc(failed_delta)
        self._last_failed_total = self._state.failed_files_total

        files = list(self._failed_batches_dir.glob("*.json"))
        FAILED_BATCH_FILES.set(len(files))
        if files:
            now = datetime.now(timezone.utc).timestamp()
            oldest = min(path.stat().st_mtime for path in files)
            FAILED_BATCH_OLDEST_AGE.set(max(0.0, now - oldest))
        else:
            FAILED_BATCH_OLDEST_AGE.set(0.0)
