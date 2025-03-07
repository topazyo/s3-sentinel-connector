# src/monitoring/__init__.py

from typing import Dict, Any, Optional
import logging
import asyncio
from datetime import datetime
from .pipeline_monitor import PipelineMonitor
from .metrics import ComponentMetrics
from .alerts import AlertManager

class MonitoringManager:
    """Central monitoring management class"""
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize monitoring components
        
        Args:
            config: Monitoring configuration
        """
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # Initialize monitoring components
        self._initialize_components()
        
        # Start monitoring tasks
        self.tasks = []
        self._start_monitoring()

    def _initialize_components(self):
        """Initialize monitoring components"""
        try:
            # Initialize pipeline monitor
            self.pipeline_monitor = PipelineMonitor(
                metrics_endpoint=self.config['metrics']['endpoint'],
                app_name=self.config['app_name'],
                environment=self.config['environment']
            )
            
            # Initialize component metrics
            self.component_metrics = {
                component: ComponentMetrics(component)
                for component in self.config['components']
            }
            
            # Initialize alert manager
            self.alert_manager = AlertManager(
                alert_configs=self.config['alerts']
            )
            
            self.logger.info("Monitoring components initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize monitoring: {str(e)}")
            raise

    def _start_monitoring(self):
        """Start monitoring tasks"""
        self.tasks.extend([
            asyncio.create_task(self.pipeline_monitor._health_check_loop()),
            asyncio.create_task(self.pipeline_monitor._metrics_export_loop()),
            asyncio.create_task(self.alert_manager._alert_check_loop())
        ])

    async def record_metric(self, 
                          component: str,
                          metric_name: str,
                          value: float,
                          labels: Optional[Dict[str, str]] = None):
        """Record metric for component"""
        try:
            # Update component metrics
            self.component_metrics[component].record_metric(
                metric_name,
                value,
                labels
            )
            
            # Send to pipeline monitor
            await self.pipeline_monitor.record_metric(
                metric_name,
                value,
                labels
            )
            
        except Exception as e:
            self.logger.error(f"Failed to record metric: {str(e)}")

    async def get_component_health(self, component: str) -> Dict[str, Any]:
        """Get health status for component"""
        try:
            metrics = self.component_metrics[component].get_metrics()
            return {
                'status': 'healthy' if metrics['error_rate'] < 0.05 else 'degraded',
                'metrics': metrics,
                'last_check': datetime.utcnow().isoformat()
            }
        except Exception as e:
            self.logger.error(f"Failed to get component health: {str(e)}")
            return {
                'status': 'unknown',
                'error': str(e)
            }

    async def check_alerts(self) -> Dict[str, Any]:
        """Check current alert status"""
        return await self.alert_manager.check_alert_conditions()

    async def cleanup(self):
        """Cleanup monitoring resources"""
        for task in self.tasks:
            task.cancel()
        
        await asyncio.gather(*self.tasks, return_exceptions=True)