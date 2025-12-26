# src/monitoring/component_metrics.py

from typing import Dict, Any, Optional
from datetime import datetime, timezone
import asyncio
from dataclasses import dataclass

@dataclass
class ComponentMetrics:
    """Metrics collector for pipeline components"""
    
    component_name: str
    
    def __post_init__(self):
        self.metrics = {
            'processed_count': 0,
            'error_count': 0,
            'processing_time': 0,
            'batch_sizes': [],
            'start_time': datetime.now(timezone.utc)
        }

    def record_processing(self, 
                         count: int, 
                         duration: float,
                         batch_size: int) -> None:
        """Record processing metrics"""
        self.metrics['processed_count'] += count
        self.metrics['processing_time'] += duration
        self.metrics['batch_sizes'].append(batch_size)

    def record_error(self, error_type: str) -> None:
        """Record processing error"""
        self.metrics['error_count'] += 1
        if 'error_types' not in self.metrics:
            self.metrics['error_types'] = {}
        self.metrics['error_types'][error_type] = \
            self.metrics['error_types'].get(error_type, 0) + 1

    def record_metric(self, metric_name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        """Record a generic metric value"""
        if 'custom_metrics' not in self.metrics:
            self.metrics['custom_metrics'] = {}
        if metric_name not in self.metrics['custom_metrics']:
            self.metrics['custom_metrics'][metric_name] = []
        self.metrics['custom_metrics'][metric_name].append({
            'value': value,
            'labels': labels or {},
            'timestamp': datetime.now(timezone.utc)
        })

    def get_metrics(self) -> Dict[str, Any]:
        """Get current metrics"""
        metrics = self.metrics.copy()
        metrics['avg_processing_time'] = \
            self.metrics['processing_time'] / self.metrics['processed_count'] \
            if self.metrics['processed_count'] > 0 else 0
        metrics['avg_batch_size'] = \
            sum(self.metrics['batch_sizes']) / len(self.metrics['batch_sizes']) \
            if self.metrics['batch_sizes'] else 0
        metrics['error_rate'] = \
            self.metrics['error_count'] / self.metrics['processed_count'] \
            if self.metrics['processed_count'] > 0 else 0
        return metrics

    def reset_metrics(self) -> None:
        """Reset metrics counters"""
        self.metrics = {
            'processed_count': 0,
            'error_count': 0,
            'processing_time': 0,
            'batch_sizes': [],
            'start_time': datetime.now(timezone.utc)
        }