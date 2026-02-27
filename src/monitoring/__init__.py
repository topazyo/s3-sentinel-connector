# src/monitoring/__init__.py
"""Monitoring package composition and lifecycle management helpers."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .pipeline_monitor import PipelineMonitor

try:  # Optional to keep package importable when metrics/alerts stubs are absent
    from .metrics import ComponentMetrics
except ImportError:  # pragma: no cover - fail on use
    ComponentMetrics = None  # type: ignore

try:
    from .alerts import AlertManager
except ImportError:  # pragma: no cover - fail on use
    AlertManager = None  # type: ignore

__all__ = ["AlertManager", "ComponentMetrics", "MonitoringManager", "PipelineMonitor"]


class MonitoringManager:
    """Central monitoring management class"""

    def __init__(self, config: Dict[str, Any]) -> None:
        """
        Initialize monitoring components

        Args:
            config: Monitoring configuration

        Note:
            Phase 4 (B2-003/RES-03): __init__ is sync, task creation moved to async start()
            Call await monitoring_manager.start() from async context after initialization
        """
        self.config = config
        self.logger = logging.getLogger(__name__)

        if ComponentMetrics is None or AlertManager is None:
            raise ImportError(
                "MonitoringManager requires metrics and alerts modules to be present"
            )

        # Initialize monitoring components
        self._initialize_components()

        # Task creation deferred to async start() method (Phase 4 - B2-003)
        self.tasks = []
        self._monitoring_started = False

    def _initialize_components(self):
        """Initialize monitoring components"""
        try:
            # Initialize pipeline monitor
            self.pipeline_monitor = PipelineMonitor(
                metrics_endpoint=self.config["metrics"]["endpoint"],
                app_name=self.config["app_name"],
                environment=self.config["environment"],
            )

            # Initialize component metrics
            self.component_metrics = {
                component: ComponentMetrics(component)
                for component in self.config["components"]
            }

            # Initialize alert manager
            self.alert_manager = AlertManager(alert_configs=self.config["alerts"])

            self.logger.info("Monitoring components initialized successfully")

        except Exception as e:
            self.logger.error(f"Failed to initialize monitoring: {e!s}")
            raise

    def _start_monitoring(self):
        """
        Start monitoring tasks (internal - called by async start())

        Phase 4 (B2-003/RES-03): Creates asyncio tasks, must be called from async context
        """
        self.tasks.extend(
            [
                asyncio.create_task(self.pipeline_monitor._health_check_loop()),
                asyncio.create_task(self.pipeline_monitor._metrics_export_loop()),
                asyncio.create_task(self.alert_manager._alert_check_loop()),
            ]
        )

    async def start(self) -> None:
        """
        Start monitoring tasks (must be called from async context)

        Phase 4 (B2-003/RES-03): Async initialization pattern to avoid
        RuntimeError: no running event loop during __init__

        Usage:
            manager = MonitoringManager(config)  # Sync initialization
            await manager.start()  # Async task creation

        Raises:
            RuntimeError: If start() called multiple times
        """
        if self._monitoring_started:
            self.logger.warning(
                "Monitoring tasks already started, ignoring duplicate start() call"
            )
            return

        self._start_monitoring()
        self._monitoring_started = True
        self.logger.info("Monitoring tasks started successfully")

    async def stop(self) -> None:
        """
        Stop monitoring tasks gracefully

        Phase 4 (B2-003/RES-03): Graceful shutdown of background tasks

        Usage:
            await manager.stop()  # Cancel all monitoring tasks
        """
        if not self._monitoring_started:
            self.logger.warning("Monitoring tasks not started, nothing to stop")
            return

        self.logger.info("Stopping monitoring tasks...")

        # Cancel all tasks
        for task in self.tasks:
            if not task.done():
                task.cancel()

        # Wait for all tasks to complete cancellation
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)

        self.tasks = []
        self._monitoring_started = False
        self.logger.info("Monitoring tasks stopped successfully")

    async def record_metric(
        self,
        component: str,
        metric_name: str,
        value: float,
        labels: Optional[Dict[str, str]] = None,
    ):
        """Record metric for component"""
        try:
            # Update component metrics
            self.component_metrics[component].record_metric(metric_name, value, labels)

            # Send to pipeline monitor
            await self.pipeline_monitor.record_metric(metric_name, value, labels)

        except Exception as e:
            self.logger.error(f"Failed to record metric: {e!s}")

    async def get_component_health(self, component: str) -> Dict[str, Any]:
        """Get health status for component"""
        try:
            metrics = self.component_metrics[component].get_metrics()
            return {
                "status": "healthy" if metrics["error_rate"] < 0.05 else "degraded",
                "metrics": metrics,
                "last_check": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            self.logger.error(f"Failed to get component health: {e!s}")
            return {"status": "unknown", "error": str(e)}

    async def check_alerts(self) -> Dict[str, Any]:
        """Check current alert status"""
        return await self.alert_manager.check_alert_conditions()

    async def cleanup(self):
        """Cleanup monitoring resources"""
        if not self.tasks:
            self._monitoring_started = False
            return

        pending_tasks = []
        for task in self.tasks:
            try:
                task.cancel()
            except Exception:
                continue

            try:
                if task.done():
                    continue
            except Exception:
                pass

            if asyncio.isfuture(task) or asyncio.iscoroutine(task):
                pending_tasks.append(task)

        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)

        self.tasks = []
        self._monitoring_started = False
