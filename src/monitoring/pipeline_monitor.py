# src/monitoring/pipeline_monitor.py

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiohttp
import prometheus_client as prom
from prometheus_client import Counter, Gauge, Histogram, Summary

try:  # Optional at import time to keep tests importable without Azure SDKs
    from azure.identity import DefaultAzureCredential
except ImportError:  # pragma: no cover - handled in _initialize_clients
    DefaultAzureCredential = None  # type: ignore

try:  # Optional at import time; tests monkeypatch this symbol
    from azure.monitor.ingestion import MetricsIngestionClient
except ImportError:  # pragma: no cover - handled in _initialize_clients
    MetricsIngestionClient = None  # type: ignore

@dataclass
class AlertConfig:
    """Configuration for alert thresholds"""
    name: str
    threshold: float
    window_minutes: int
    severity: str
    description: str
    action: str

class PipelineMonitor:
    def __init__(self, 
                 metrics_endpoint: str,
                 app_name: str,
                 environment: str,
                 alert_configs: Optional[List[AlertConfig]] = None,
                 s3_health_url: Optional[str] = None,
                 sentinel_health_url: Optional[str] = None,
                 teams_webhook: Optional[str] = None,
                 slack_webhook: Optional[str] = None,
                 health_timeout: float = 5.0,
                 enable_background_tasks: bool = True):
        """
        Initialize pipeline monitoring system
        
        Args:
            metrics_endpoint: Endpoint for metrics ingestion
            app_name: Application name
            environment: Deployment environment
            alert_configs: List of alert configurations
        """
        self.app_name = app_name
        self.environment = environment
        self.alert_configs = alert_configs or self._default_alert_configs()
        self.s3_health_url = s3_health_url
        self.sentinel_health_url = sentinel_health_url
        self.teams_webhook = teams_webhook
        self.slack_webhook = slack_webhook
        self.health_timeout = health_timeout
        self.enable_background_tasks = enable_background_tasks
        self._registry = prom.CollectorRegistry()
        
        # Initialize metrics clients
        self._initialize_clients(metrics_endpoint)
        
        # Initialize Prometheus metrics
        self._initialize_prometheus_metrics()
        
        # Initialize internal state
        self.component_health = {}
        self.last_check_times = {}
        self._metric_cache: Dict[str, Dict[str, Any]] = {}
        self._active_alerts: List[Dict[str, Any]] = []
        
        # Start background tasks
        self.tasks: List[asyncio.Task] = []
        if self.enable_background_tasks:
            self.tasks.extend([
                asyncio.create_task(self._health_check_loop()),
                asyncio.create_task(self._metrics_export_loop()),
                asyncio.create_task(self._alert_check_loop())
            ])

    def _initialize_clients(self, metrics_endpoint: str) -> None:
        """Initialize monitoring clients"""
        if MetricsIngestionClient is None or DefaultAzureCredential is None:
            raise ImportError(
                "azure-monitor-ingestion and azure-identity are required for PipelineMonitor"
            )

        try:
            credential = DefaultAzureCredential()
            self.metrics_client = MetricsIngestionClient(
                endpoint=metrics_endpoint,
                credential=credential
            )
            logging.info("Successfully initialized monitoring clients")
        except Exception as e:
            logging.critical(f"Failed to initialize monitoring clients: {str(e)}")
            raise

    def _initialize_prometheus_metrics(self) -> None:
        """Initialize Prometheus metrics collectors"""
        # Counter metrics
        self.logs_processed = Counter(
            'logs_processed_total',
            'Total number of logs processed',
            ['source', 'status'],
            registry=self._registry
        )
        self.ingestion_errors = Counter(
            'ingestion_errors_total',
            'Total number of ingestion errors',
            ['type'],
            registry=self._registry
        )
        
        # Gauge metrics
        self.pipeline_lag = Gauge(
            'pipeline_lag_seconds',
            'Current lag in log processing pipeline',
            registry=self._registry
        )
        self.component_health_status = Gauge(
            'component_health_status',
            'Health status of pipeline components',
            ['component'],
            registry=self._registry
        )
        
        # Histogram metrics
        self.processing_time = Histogram(
            'log_processing_duration_seconds',
            'Time spent processing logs',
            ['operation'],
            buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0],
            registry=self._registry
        )
        
        # Summary metrics
        self.batch_size = Summary(
            'batch_size_bytes',
            'Size of processed batches in bytes',
            registry=self._registry
        )

    async def _start_monitoring_tasks(self) -> None:
        """Start background monitoring tasks"""
        self.tasks = [
            asyncio.create_task(self._health_check_loop()),
            asyncio.create_task(self._metrics_export_loop()),
            asyncio.create_task(self._alert_check_loop())
        ]

    async def record_metric(self, 
                          metric_name: str, 
                          value: float,
                          labels: Optional[Dict[str, str]] = None) -> None:
        """
        Record a metric value with labels
        
        Args:
            metric_name: Name of the metric
            value: Metric value
            labels: Optional metric labels
        """
        try:
            timestamp = datetime.now(timezone.utc)
            metric_data = {
                'name': metric_name,
                'value': value,
                'timestamp': timestamp.isoformat(),
                'labels': labels or {},
                'app': self.app_name,
                'environment': self.environment
            }

            # Update Prometheus metrics with type-aware handling
            metric = getattr(self, metric_name, None)
            if metric:
                if isinstance(metric, Counter):
                    (metric.labels(**labels).inc(value) if labels else metric.inc(value))
                elif isinstance(metric, Gauge):
                    (metric.labels(**labels).set(value) if labels else metric.set(value))
                elif isinstance(metric, Histogram):
                    (metric.labels(**labels).observe(value) if labels else metric.observe(value))
                elif isinstance(metric, Summary):
                    (metric.labels(**labels).observe(value) if labels else metric.observe(value))

            # Cache latest metric for alerting/export
            self._metric_cache[metric_name] = metric_data

            # Send to Azure Monitor asynchronously to avoid blocking
            await asyncio.to_thread(self.metrics_client.ingest_metrics, [metric_data])
            
        except Exception as e:
            logging.error(f"Failed to record metric {metric_name}: {str(e)}")

    async def update_component_health(self, 
                                   component: str, 
                                   status: bool,
                                   details: Optional[Dict[str, Any]] = None) -> None:
        """
        Update health status of a pipeline component
        
        Args:
            component: Component name
            status: Health status (True=healthy, False=unhealthy)
            details: Optional health check details
        """
        self.component_health[component] = {
            'status': status,
            'last_check': datetime.now(timezone.utc),
            'details': details or {}
        }
        
        # Record gauge via metric pipeline
        await self.record_metric(
            'component_health_status',
            1 if status else 0,
            labels={'component': component}
        )

        logging.info(f"Component {component} health status: {'healthy' if status else 'unhealthy'}")

    async def _health_check_loop(self) -> None:
        """Periodic health check loop"""
        while True:
            try:
                # Check S3 connectivity
                s3_health = await self._check_s3_health()
                await self.update_component_health('s3', s3_health['status'], s3_health)
                
                # Check Sentinel connectivity
                sentinel_health = await self._check_sentinel_health()
                await self.update_component_health('sentinel', 
                                                 sentinel_health['status'], 
                                                 sentinel_health)
                
                # Check pipeline lag
                lag = await self._check_pipeline_lag()
                await self.record_metric('pipeline_lag', lag)
                
                await asyncio.sleep(60)  # Run every minute
                
            except Exception as e:
                logging.error(f"Health check loop error: {str(e)}")
                await asyncio.sleep(5)  # Short sleep on error

    async def _alert_check_loop(self) -> None:
        """Check for alert conditions"""
        while True:
            try:
                for alert_config in self.alert_configs:
                    await self._check_alert_condition(alert_config)
                
                await asyncio.sleep(30)  # Run every 30 seconds
                
            except Exception as e:
                logging.error(f"Alert check loop error: {str(e)}")
                await asyncio.sleep(5)

    async def _metrics_export_loop(self) -> None:
        """Export metrics to external systems"""
        while True:
            try:
                metrics = self._collect_current_metrics()
                
                # Export to Azure Monitor
                await self._export_to_azure_monitor(metrics)
                
                # Export to Prometheus (metrics already exposed via collectors)
                self._export_to_prometheus(metrics)
                
                await asyncio.sleep(60)  # Export every minute
                
            except Exception as e:
                logging.error(f"Metrics export error: {str(e)}")
                await asyncio.sleep(5)

    async def _check_alert_condition(self, alert_config: AlertConfig) -> None:
        """Check if alert condition is met and trigger alert if needed"""
        try:
            # Get metric value for alert
            metric_value = await self._get_metric_value(alert_config.name)
            
            if metric_value > alert_config.threshold:
                await self._trigger_alert(alert_config, metric_value)
                
        except Exception as e:
            logging.error(f"Alert check error for {alert_config.name}: {str(e)}")

    async def _trigger_alert(self, 
                           alert_config: AlertConfig, 
                           current_value: float) -> None:
        """Trigger alert through configured channels"""
        alert_data = {
            'name': alert_config.name,
            'severity': alert_config.severity,
            'threshold': alert_config.threshold,
            'current_value': current_value,
            'description': alert_config.description,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'environment': self.environment
        }
        
        # Log alert
        logging.warning(f"Alert triggered: {json.dumps(alert_data)}")
        self._active_alerts.append(alert_data)
        
        # Send to Teams/Slack if configured
        if alert_config.action == 'teams':
            await self._send_teams_alert(alert_data)
        elif alert_config.action == 'slack':
            await self._send_slack_alert(alert_data)

    async def _get_metric_value(self, metric_name: str) -> float:
        """Return latest cached metric value for alert evaluation."""
        entry = self._metric_cache.get(metric_name)
        if not entry:
            return 0.0
        return float(entry.get('value', 0.0))

    async def _send_teams_alert(self, alert_data: Dict[str, Any]) -> None:
        """Send alert to Microsoft Teams"""
        teams_webhook = self._get_teams_webhook()
        if not teams_webhook:
            logging.warning("Teams webhook not configured; skipping alert for %s", alert_data.get('name'))
            return
        
        message = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "summary": f"Alert: {alert_data['name']}",
            "sections": [{
                "activityTitle": f"🚨 Alert: {alert_data['name']}",
                "facts": [
                    {"name": "Severity", "value": alert_data['severity']},
                    {"name": "Threshold", "value": str(alert_data['threshold'])},
                    {"name": "Current Value", "value": str(alert_data['current_value'])},
                    {"name": "Environment", "value": alert_data['environment']}
                ],
                "text": alert_data['description']
            }]
        }
        
        async with aiohttp.ClientSession() as session:
            post_ctx = session.post(teams_webhook, json=message)
            if asyncio.iscoroutine(post_ctx):
                post_ctx = await post_ctx

            async with post_ctx as response:
                if response.status != 200:
                    logging.error(f"Failed to send Teams alert: {await response.text()}")

    async def _send_slack_alert(self, alert_data: Dict[str, Any]) -> None:
        """Send alert to Slack if webhook configured."""
        webhook = self.slack_webhook
        if not webhook:
            logging.warning("Slack webhook not configured; skipping alert for %s", alert_data.get('name'))
            return

        payload = {
            "text": f"*{alert_data['name']}* (severity: {alert_data['severity']})\n"
                    f"Threshold: {alert_data['threshold']} Current: {alert_data['current_value']}\n"
                    f"Env: {alert_data['environment']}\n{alert_data['description']}"
        }

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.health_timeout)) as session:
            post_ctx = session.post(webhook, json=payload)
            if asyncio.iscoroutine(post_ctx):
                post_ctx = await post_ctx

            async with post_ctx as resp:
                if resp.status >= 400:
                    logging.error("Failed to send Slack alert (%s): %s", alert_data.get('name'), await resp.text())

    def _default_alert_configs(self) -> List[AlertConfig]:
        """Default alert configurations"""
        return [
            AlertConfig(
                name='pipeline_lag',
                threshold=300,  # 5 minutes
                window_minutes=5,
                severity='high',
                description='Pipeline processing lag exceeds threshold',
                action='teams'
            ),
            AlertConfig(
                name='error_rate',
                threshold=0.05,  # 5% error rate
                window_minutes=5,
                severity='high',
                description='Error rate exceeds threshold',
                action='teams'
            ),
            AlertConfig(
                name='component_health',
                threshold=0,
                window_minutes=5,
                severity='critical',
                description='Component health check failed',
                action='teams'
            )
        ]

    def get_monitoring_dashboard(self) -> Dict[str, Any]:
        """Get monitoring dashboard data"""
        return {
            'component_health': self.component_health,
            'metrics': self._collect_current_metrics(),
            'alerts': self._get_active_alerts(),
            'last_updated': datetime.utcnow().isoformat()
        }

    def _collect_current_metrics(self) -> List[Dict[str, Any]]:
        """Collect latest metric snapshots from the in-memory cache."""
        return list(self._metric_cache.values())

    async def _export_to_azure_monitor(self, metrics: List[Dict[str, Any]]) -> None:
        """Export cached metrics to Azure Monitor asynchronously."""
        if not metrics:
            return
        try:
            await asyncio.to_thread(self.metrics_client.ingest_metrics, metrics)
        except Exception as e:
            logging.error(f"Azure Monitor export failed: {str(e)}")

    def _export_to_prometheus(self, metrics: List[Dict[str, Any]]) -> None:
        """Prometheus client exposes metrics via collector registry; no action needed."""
        return

    async def _check_s3_health(self) -> Dict[str, Any]:
        """Check S3 connectivity via configured health endpoint when available."""
        if not self.s3_health_url:
            return {'status': True, 'checked_at': datetime.now(timezone.utc).isoformat(), 'detail': 'no s3 health url configured'}

        try:
            session_ctx = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.health_timeout))
            if asyncio.iscoroutine(session_ctx):
                session_ctx = await session_ctx

            async with session_ctx as session:
                resp_ctx = session.get(self.s3_health_url)
                if asyncio.iscoroutine(resp_ctx):
                    resp_ctx = await resp_ctx

                async with resp_ctx as resp:
                    ok = resp.status < 400
                    return {
                        'status': ok,
                        'checked_at': datetime.now(timezone.utc).isoformat(),
                        'detail': f'status={resp.status}'
                    }
        except Exception as e:
            return {'status': False, 'checked_at': datetime.now(timezone.utc).isoformat(), 'error': str(e)}

    async def _check_sentinel_health(self) -> Dict[str, Any]:
        """Check Sentinel connectivity via configured health endpoint when available."""
        if not self.sentinel_health_url:
            return {'status': True, 'checked_at': datetime.now(timezone.utc).isoformat(), 'detail': 'no sentinel health url configured'}

        try:
            session_ctx = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.health_timeout))
            if asyncio.iscoroutine(session_ctx):
                session_ctx = await session_ctx

            async with session_ctx as session:
                resp_ctx = session.get(self.sentinel_health_url)
                if asyncio.iscoroutine(resp_ctx):
                    resp_ctx = await resp_ctx

                async with resp_ctx as resp:
                    ok = resp.status < 400
                    return {
                        'status': ok,
                        'checked_at': datetime.now(timezone.utc).isoformat(),
                        'detail': f'status={resp.status}'
                    }
        except Exception as e:
            return {'status': False, 'checked_at': datetime.now(timezone.utc).isoformat(), 'error': str(e)}

    async def _check_pipeline_lag(self) -> float:
        """Placeholder lag computation; returns 0 when no data available."""
        return 0.0

    def _get_teams_webhook(self) -> Optional[str]:
        """Retrieve Teams webhook URL if configured."""
        return self.teams_webhook

    def _get_active_alerts(self) -> List[Dict[str, Any]]:
        """Return a snapshot of cached alerts."""
        return list(self._active_alerts)