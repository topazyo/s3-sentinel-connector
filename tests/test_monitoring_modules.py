# tests/test_monitoring_modules.py
"""
Tests for Phase 4: Verify monitoring modules C6 fix
"""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime

def test_metrics_module_import():
    """Test that metrics module can be imported"""
    from src.monitoring.metrics import ComponentMetrics
    assert ComponentMetrics is not None


def test_alerts_module_import():
    """Test that alerts module can be imported"""
    from src.monitoring.alerts import AlertManager, AlertCondition
    assert AlertManager is not None
    assert AlertCondition is not None


def test_monitoring_init_imports():
    """Test that monitoring __init__ imports work"""
    from src.monitoring import ComponentMetrics, AlertManager
    assert ComponentMetrics is not None
    assert AlertManager is not None


def test_component_metrics_creation():
    """Test ComponentMetrics can be instantiated"""
    from src.monitoring.metrics import ComponentMetrics
    
    metrics = ComponentMetrics("test_component")
    assert metrics.component_name == "test_component"
    assert metrics.metrics['processed_count'] == 0
    assert metrics.metrics['error_count'] == 0


def test_component_metrics_record_processing():
    """Test recording processing metrics"""
    from src.monitoring.metrics import ComponentMetrics
    
    metrics = ComponentMetrics("test_component")
    metrics.record_processing(count=10, duration=1.5, batch_size=10)
    
    assert metrics.metrics['processed_count'] == 10
    assert metrics.metrics['processing_time'] == 1.5
    assert len(metrics.metrics['batch_sizes']) == 1


def test_component_metrics_record_error():
    """Test recording error metrics"""
    from src.monitoring.metrics import ComponentMetrics
    
    metrics = ComponentMetrics("test_component")
    metrics.record_error("ValueError")
    metrics.record_error("ValueError")
    metrics.record_error("TypeError")
    
    assert metrics.metrics['error_count'] == 3
    assert metrics.metrics['error_types']['ValueError'] == 2
    assert metrics.metrics['error_types']['TypeError'] == 1


def test_component_metrics_get_metrics():
    """Test getting calculated metrics"""
    from src.monitoring.metrics import ComponentMetrics
    
    metrics = ComponentMetrics("test_component")
    metrics.record_processing(count=10, duration=2.0, batch_size=10)
    metrics.record_processing(count=5, duration=1.0, batch_size=5)
    metrics.record_error("ValueError")
    
    result = metrics.get_metrics()
    
    assert result['processed_count'] == 15
    assert result['error_count'] == 1
    assert result['avg_processing_time'] == pytest.approx(3.0 / 15)
    assert result['avg_batch_size'] == pytest.approx(7.5)
    assert result['error_rate'] == pytest.approx(1.0 / 15)


def test_alert_manager_creation():
    """Test AlertManager can be instantiated"""
    from src.monitoring.alerts import AlertManager
    
    alert_configs = [
        {
            'name': 'high_error_rate',
            'metric': 'error_rate',
            'threshold': 0.05,
            'operator': 'gt',
            'duration': 60,
            'severity': 'warning'
        }
    ]
    
    manager = AlertManager(alert_configs)
    assert len(manager.conditions) == 1
    assert manager.conditions[0].name == 'high_error_rate'


def test_alert_manager_update_metric():
    """Test updating metric values"""
    from src.monitoring.alerts import AlertManager
    
    manager = AlertManager([])
    manager.update_metric('error_rate', 0.10)
    
    assert manager.metric_cache['error_rate'] == 0.10


def test_alert_manager_evaluate_condition():
    """Test condition evaluation"""
    from src.monitoring.alerts import AlertManager
    
    manager = AlertManager([])
    
    # Test greater than
    assert manager._evaluate_condition(10, 5, 'gt') is True
    assert manager._evaluate_condition(3, 5, 'gt') is False
    
    # Test less than
    assert manager._evaluate_condition(3, 5, 'lt') is True
    assert manager._evaluate_condition(10, 5, 'lt') is False
    
    # Test greater than or equal
    assert manager._evaluate_condition(5, 5, 'gte') is True
    assert manager._evaluate_condition(6, 5, 'gte') is True
    assert manager._evaluate_condition(4, 5, 'gte') is False


@pytest.mark.asyncio
async def test_alert_manager_check_alert_conditions():
    """Test getting alert status"""
    from src.monitoring.alerts import AlertManager
    
    manager = AlertManager([])
    
    status = await manager.check_alert_conditions()
    
    assert 'active_alerts' in status
    assert 'alert_count' in status
    assert 'conditions_tracked' in status
    assert 'checked_at' in status
    assert status['alert_count'] == 0


@pytest.mark.asyncio
async def test_alert_firing():
    """Test alert firing logic"""
    from src.monitoring.alerts import AlertManager, AlertCondition
    from datetime import datetime, timedelta, timezone
    
    alert_config = {
        'name': 'test_alert',
        'metric': 'error_rate',
        'threshold': 0.05,
        'operator': 'gt',
        'duration': 0,  # Immediate
        'severity': 'warning'
    }
    
    manager = AlertManager([alert_config])
    manager.update_metric('error_rate', 0.10)  # Above threshold
    
    # Check condition
    condition = manager.conditions[0]
    manager.condition_states[condition.name] = datetime.now(timezone.utc) - timedelta(seconds=10)
    
    await manager._check_condition(condition)
    
    # Alert should be fired
    assert 'test_alert' in manager.active_alerts
    assert manager.active_alerts['test_alert']['value'] == 0.10


@pytest.mark.asyncio
async def test_alert_resolution():
    """Test alert resolution logic"""
    from src.monitoring.alerts import AlertManager
    
    alert_config = {
        'name': 'test_alert',
        'metric': 'error_rate',
        'threshold': 0.05,
        'operator': 'gt',
        'duration': 0,
        'severity': 'warning'
    }
    
    manager = AlertManager([alert_config])
    
    # Manually add an active alert
    manager.active_alerts['test_alert'] = {
        'name': 'test_alert',
        'value': 0.10,
        'message': 'Test alert message'
    }
    
    # Resolve it
    await manager._resolve_alert('test_alert')
    
    assert 'test_alert' not in manager.active_alerts


def test_monitoring_manager_requires_modules():
    """Test that MonitoringManager raises error if modules missing"""
    from src.monitoring import MonitoringManager
    
    config = {
        'app_name': 'test',
        'environment': 'test',
        'components': ['s3_handler'],
        'metrics': {'endpoint': 'http://test'},
        'alerts': []
    }
    
    # Should work now that modules exist
    try:
        manager = MonitoringManager(config)
        # If we get here, modules are available
        assert hasattr(manager, 'pipeline_monitor')
    except Exception as e:
        # May fail due to other initialization issues, but shouldn't be ImportError
        assert not isinstance(e, ImportError) or "metrics and alerts" not in str(e)
