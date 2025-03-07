# src/monitoring/pipeline_monitor.py

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
import asyncio
from azure.monitor.ingestion import MetricsIngestionClient
from azure.identity import DefaultAzureCredential
import prometheus_client as prom
from prometheus_client import Counter, Gauge, Histogram, Summary
import json
import aiohttp

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
                 alert_configs: Optional[List[AlertConfig]] = None):
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
        
        # Initialize metrics clients
        self._initialize_clients(metrics_endpoint)
        
        # Initialize Prometheus metrics
        self._initialize_prometheus_metrics()
        
        # Initialize internal state
        self.component_health = {}
        self.last_check_times = {}
        
        # Start background tasks
        self.tasks = []
        asyncio.create_task(self._start_monitoring_tasks())

    def _initialize_clients(self, metrics_endpoint: str) -> None:
        """Initialize monitoring clients"""
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
            ['source', 'status']
        )
        self.ingestion_errors = Counter(
            'ingestion_errors_total',
            'Total number of ingestion errors',
            ['type']
        )
        
        # Gauge metrics
        self.pipeline_lag = Gauge(
            'pipeline_lag_seconds',
            'Current lag in log processing pipeline'
        )
        self.component_health_status = Gauge(
            'component_health_status',
            'Health status of pipeline components',
            ['component']
        )
        
        # Histogram metrics
        self.processing_time = Histogram(
            'log_processing_duration_seconds',
            'Time spent processing logs',
            ['operation'],
            buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0]
        )
        
        # Summary metrics
        self.batch_size = Summary(
            'batch_size_bytes',
            'Size of processed batches in bytes'
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
            timestamp = datetime.utcnow()
            metric_data = {
                'name': metric_name,
                'value': value,
                'timestamp': timestamp.isoformat(),
                'labels': labels or {},
                'app': self.app_name,
                'environment': self.environment
            }
            
            # Update Prometheus metrics
            if hasattr(self, metric_name):
                metric = getattr(self, metric_name)
                if labels:
                    metric.labels(**labels).inc(value)
                else:
                    metric.inc(value)
            
            # Send to Azure Monitor
            await self.metrics_client.ingest_metrics([metric_data])
            
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
            'last_check': datetime.utcnow(),
            'details': details or {}
        }
        
        # Update Prometheus metric
        self.component_health_status.labels(component=component).set(1 if status else 0)
        
        # Log status change
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
                self.pipeline_lag.set(lag)
                
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
                
                # Export to Prometheus
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
            'timestamp': datetime.utcnow().isoformat(),
            'environment': self.environment
        }
        
        # Log alert
        logging.warning(f"Alert triggered: {json.dumps(alert_data)}")
        
        # Send to Teams/Slack if configured
        if alert_config.action == 'teams':
            await self._send_teams_alert(alert_data)
        elif alert_config.action == 'slack':
            await self._send_slack_alert(alert_data)

    async def _send_teams_alert(self, alert_data: Dict[str, Any]) -> None:
        """Send alert to Microsoft Teams"""
        teams_webhook = self._get_teams_webhook()
        
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
            async with session.post(teams_webhook, json=message) as response:
                if response.status != 200:
                    logging.error(f"Failed to send Teams alert: {await response.text()}")

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