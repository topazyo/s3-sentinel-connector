# src/monitoring/alerts.py
"""
Alert management module for monitoring pipeline health
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class AlertCondition:
    """Definition of an alert condition"""

    name: str
    metric_name: str
    threshold: float
    operator: str  # 'gt', 'lt', 'gte', 'lte', 'eq'
    duration: int  # seconds the condition must be true
    severity: str  # 'critical', 'warning', 'info'


class AlertManager:
    """Manages alert conditions and notifications"""

    def __init__(
        self,
        alert_configs: List[Dict[str, Any]],
        notification_handlers: Optional[List] = None,
    ) -> None:
        """
        Initialize alert manager

        Args:
            alert_configs: List of alert configuration dictionaries
            notification_handlers: Optional list of async callables taking alert dict
        """
        self.alert_configs = alert_configs
        self.logger = logging.getLogger(__name__)
        self.notification_handlers = notification_handlers or []

        # Parse alert conditions
        self.conditions = self._parse_alert_configs(alert_configs)

        # Track active alerts
        self.active_alerts: Dict[str, Dict[str, Any]] = {}

        # Condition state tracking
        self.condition_states: Dict[str, datetime] = {}

        # Metric cache for evaluation
        self.metric_cache: Dict[str, float] = {}

        self.logger.info(
            f"AlertManager initialized with {len(self.conditions)} conditions"
        )

    def _parse_alert_configs(
        self, configs: List[Dict[str, Any]]
    ) -> List[AlertCondition]:
        """Parse alert configurations into AlertCondition objects"""
        conditions = []
        for config in configs:
            try:
                condition = AlertCondition(
                    name=config.get("name", "unnamed_alert"),
                    metric_name=config.get("metric", ""),
                    threshold=float(config.get("threshold", 0)),
                    operator=config.get("operator", "gt"),
                    duration=int(config.get("duration", 60)),
                    severity=config.get("severity", "warning"),
                )
                conditions.append(condition)
            except (ValueError, KeyError) as e:
                self.logger.error(f"Failed to parse alert config: {config}, error: {e}")

        return conditions

    async def _alert_check_loop(self) -> None:
        """Background loop to check alert conditions"""
        while True:
            try:
                await self._check_all_conditions()
                await asyncio.sleep(30)  # Check every 30 seconds
            except asyncio.CancelledError:
                self.logger.info("Alert check loop cancelled")
                break
            except Exception as e:
                self.logger.error(f"Alert check loop error: {e!s}")
                await asyncio.sleep(30)

    async def _check_all_conditions(self) -> None:
        """Check all alert conditions against current metrics"""
        for condition in self.conditions:
            try:
                await self._check_condition(condition)
            except Exception as e:
                self.logger.error(f"Error checking condition {condition.name}: {e}")

    async def _check_condition(self, condition: AlertCondition) -> None:
        """Check a single alert condition"""
        # Get metric value from cache
        metric_value = self.metric_cache.get(condition.metric_name)
        if metric_value is None:
            return

        # Evaluate condition
        is_triggered = self._evaluate_condition(
            metric_value, condition.threshold, condition.operator
        )

        now = datetime.now(timezone.utc)

        if is_triggered:
            # Track when condition first became true
            if condition.name not in self.condition_states:
                self.condition_states[condition.name] = now

            # Check if duration threshold met
            since = self.condition_states[condition.name]
            if isinstance(since, datetime) and since.tzinfo is None:
                since = since.replace(tzinfo=timezone.utc)
                self.condition_states[condition.name] = since
            time_in_state = (now - since).total_seconds()
            if time_in_state >= condition.duration:
                # Fire alert if not already active
                if condition.name not in self.active_alerts:
                    await self._fire_alert(condition, metric_value)
        else:
            # Condition no longer true - clear state and resolve alert
            if condition.name in self.condition_states:
                del self.condition_states[condition.name]
            if condition.name in self.active_alerts:
                await self._resolve_alert(condition.name)

    def _evaluate_condition(
        self, value: float, threshold: float, operator: str
    ) -> bool:
        """Evaluate if a condition is met"""
        if operator == "gt":
            return value > threshold
        elif operator == "lt":
            return value < threshold
        elif operator == "gte":
            return value >= threshold
        elif operator == "lte":
            return value <= threshold
        elif operator == "eq":
            return abs(value - threshold) < 0.001  # Float equality with tolerance
        else:
            self.logger.warning(f"Unknown operator: {operator}")
            return False

    async def _fire_alert(self, condition: AlertCondition, value: float) -> None:
        """Fire an alert"""
        alert = {
            "name": condition.name,
            "metric": condition.metric_name,
            "value": value,
            "threshold": condition.threshold,
            "severity": condition.severity,
            "fired_at": datetime.now(timezone.utc),
            "message": f"{condition.metric_name} is {value} (threshold: {condition.threshold})",
        }

        self.active_alerts[condition.name] = alert

        # Log alert
        log_method = {
            "critical": self.logger.critical,
            "warning": self.logger.warning,
            "info": self.logger.info,
        }.get(condition.severity, self.logger.warning)

        log_method(f"ALERT FIRED: {alert['message']}")

        # Dispatch to any configured async notification handlers
        if self.notification_handlers:
            results = await asyncio.gather(
                *(handler(alert) for handler in self.notification_handlers),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, Exception):
                    self.logger.error(f"Alert notification handler failed: {result}")

    async def _resolve_alert(self, alert_name: str) -> None:
        """Resolve an active alert"""
        if alert_name in self.active_alerts:
            alert = self.active_alerts[alert_name]
            self.logger.info(f"ALERT RESOLVED: {alert['name']} - {alert['message']}")
            del self.active_alerts[alert_name]

    def update_metric(self, metric_name: str, value: float) -> None:
        """Update a metric value in the cache"""
        self.metric_cache[metric_name] = value

    async def check_alert_conditions(self) -> Dict[str, Any]:
        """
        Check current alert conditions and return status

        Returns:
            Dictionary with active alerts and overall status
        """
        return {
            "active_alerts": list(self.active_alerts.values()),
            "alert_count": len(self.active_alerts),
            "conditions_tracked": len(self.conditions),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    def get_active_alerts(self) -> List[Dict[str, Any]]:
        """Get list of currently active alerts"""
        return list(self.active_alerts.values())

    def clear_all_alerts(self) -> None:
        """Clear all active alerts (for testing)"""
        self.active_alerts.clear()
        self.condition_states.clear()
