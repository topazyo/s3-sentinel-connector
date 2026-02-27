"""Unit tests for src.monitoring.component_metrics.ComponentMetrics."""

from __future__ import annotations

from src.monitoring.component_metrics import ComponentMetrics


def test_component_metrics_processing_and_averages():
    metrics = ComponentMetrics("router")

    metrics.record_processing(count=10, duration=2.0, batch_size=5)
    metrics.record_processing(count=20, duration=3.0, batch_size=10)

    result = metrics.get_metrics()

    assert result["processed_count"] == 30
    assert result["processing_time"] == 5.0
    assert result["avg_processing_time"] == 5.0 / 30
    assert result["avg_batch_size"] == 7.5


def test_component_metrics_error_rate_and_custom_metrics():
    metrics = ComponentMetrics("router")

    metrics.record_processing(count=10, duration=1.0, batch_size=10)
    metrics.record_error("timeout")
    metrics.record_error("timeout")
    metrics.record_metric("queue_depth", 25, {"queue": "sentinel"})

    result = metrics.get_metrics()

    assert result["error_count"] == 2
    assert result["error_rate"] == 0.2
    assert result["error_types"]["timeout"] == 2
    assert result["custom_metrics"]["queue_depth"][0]["value"] == 25


def test_component_metrics_reset_clears_counters():
    metrics = ComponentMetrics("router")

    metrics.record_processing(count=5, duration=1.0, batch_size=5)
    metrics.record_error("validation")

    metrics.reset_metrics()
    result = metrics.get_metrics()

    assert result["processed_count"] == 0
    assert result["error_count"] == 0
    assert result["processing_time"] == 0
    assert result["avg_processing_time"] == 0
    assert result["error_rate"] == 0
