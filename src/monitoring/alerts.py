# src/monitoring/alerts.py

from typing import Dict, Any, List
import logging
import time
import asyncio

class AlertManager:
    def __init__(self, alert_configs: List[Dict[str, Any]]):
        self.alert_configs = alert_configs
        self.logger = logging.getLogger(__name__)
        self.active_alerts: Dict[str, Dict[str, Any]] = {}

        self.logger.info("AlertManager initialized.")
        # In a real scenario, you might validate alert_configs here

    def check_metric(self, metric_name: str, metric_value: float, component_name: str = "general"):
        self.logger.debug(f"Checking metric: {metric_name}, value: {metric_value}, component: {component_name}")
        for config in self.alert_configs:
            if config.get('metric') == metric_name:
                threshold = config.get('threshold', 0) # Default threshold to avoid NoneType error
                operator = config.get('operator', '>')

                triggered = False
                try:
                    if operator == '>' and metric_value > threshold:
                        triggered = True
                    elif operator == '<' and metric_value < threshold:
                        triggered = True
                    # Add other operators as needed (>=, <=, ==, !=)
                except TypeError:
                    self.logger.error(f"Type error comparing metric value {metric_value} with threshold {threshold} for alert {config.get('name')}")
                    continue # Skip this alert evaluation

                alert_key = f"{config.get('name', 'unknown_alert')}_{component_name}"

                if triggered:
                    if alert_key not in self.active_alerts:
                        alert_details = {
                            "name": config.get('name', 'unknown_alert'),
                            "component": component_name,
                            "metric": metric_name,
                            "value": metric_value,
                            "threshold": threshold,
                            "severity": config.get('severity', 'warning'),
                            "timestamp": time.time(),
                            "message": f"Alert '{config.get('name')}' triggered for '{component_name}': {metric_name} ({metric_value}) {operator} {threshold}"
                        }
                        self.active_alerts[alert_key] = alert_details
                        self.logger.warning(alert_details["message"])
                        self.send_notification(alert_details)
                else:
                    if alert_key in self.active_alerts:
                        self.logger.info(f"Alert '{config.get('name')}' for '{component_name}' resolved.")
                        del self.active_alerts[alert_key]
                        # Optionally send a resolution notification

    async def _alert_check_loop(self):
        self.logger.info("AlertManager async check loop started (placeholder).")
        # This is a placeholder for more complex, ongoing alert evaluations
        # For example, alerts based on sustained conditions over time.
        # For now, check_metric handles immediate, stateless alerts.
        # In a real implementation, this might query data sources, etc.
        while True:
            await asyncio.sleep(60) # Example check interval
            self.logger.debug("AlertManager periodic check...")
            # Add logic for time-window based alerts or re-notifications if necessary

    def get_active_alerts(self) -> List[Dict[str, Any]]:
        return list(self.active_alerts.values())

    def send_notification(self, alert_details: Dict[str, Any]):
        # Placeholder for sending notifications (e.g., email, Slack, PagerDuty).
        # In a real system, this would integrate with notification services.
        self.logger.info(f"NOTIFICATION (placeholder): {alert_details['message']}")

if __name__ == '__main__':
    # Basic example for testing the AlertManager class
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    example_alert_configs = [
        {
            "name": "high_cpu",
            "metric": "cpu.usage_percent",
            "threshold": 80.0,
            "operator": ">",
            "severity": "critical"
        },
        {
            "name": "low_disk_space",
            "metric": "disk.free_gb",
            "threshold": 10.0,
            "operator": "<",
            "severity": "warning"
        }
    ]
    
    manager = AlertManager(alert_configs=example_alert_configs)
    
    print("--- Simulating Metric Checks ---")
    manager.check_metric(metric_name="cpu.usage_percent", metric_value=85.0, component_name="api_server_1")
    manager.check_metric(metric_name="cpu.usage_percent", metric_value=90.0, component_name="worker_node_5")
    manager.check_metric(metric_name="disk.free_gb", metric_value=5.0, component_name="db_server_main")
    manager.check_metric(metric_name="cpu.usage_percent", metric_value=75.0, component_name="api_server_1") # CPU resolved
    
    print("\n--- Current Active Alerts ---")
    for alert in manager.get_active_alerts():
        print(alert)
        
    print("\n--- Example of running the async loop (conceptual) ---")
    print("To test _alert_check_loop, you would typically run it within an asyncio event loop.")
    # async def run_loop():
    #     asyncio.create_task(manager._alert_check_loop())
    #     # Let it run for a few seconds then cancel for this example
    #     await asyncio.sleep(5) 
    #     for task in asyncio.all_tasks():
    #         if task is not asyncio.current_task():
    #             task.cancel()
    # try:
    #     # asyncio.run(run_loop()) # Uncomment to run a brief test
    #     pass
    # except asyncio.CancelledError:
    #     print("Async loop example tasks cancelled.")
    # except KeyboardInterrupt:
    #     print("Async loop example interrupted.")
    print("AlertManager example finished.")
