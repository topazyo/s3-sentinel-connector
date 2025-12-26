# src/monitoring/metrics.py
"""
Metrics module - re-exports ComponentMetrics for backward compatibility
"""

from .component_metrics import ComponentMetrics

__all__ = ['ComponentMetrics']
