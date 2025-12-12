import numpy as np
import pytest

from src.ml.enhanced_connector import MLEnhancedConnector, MLConfig


class CountingModel:
    def __init__(self):
        self.calls = 0

    def predict(self, data):
        self.calls += 1
        try:
            length = len(data)
        except TypeError:
            length = 1
        return np.full(length, 0.9, dtype=float)

    def partial_fit(self, data, labels=None):
        return self


@pytest.fixture
async def ml_connector(tmp_path):
    config = MLConfig(
        model_path=str(tmp_path / "models"),
        anomaly_threshold=0.5,
        update_interval=30,
        cache_size=10,
    )
    connector = MLEnhancedConnector(config)
    try:
        yield connector
    finally:
        await connector.cleanup()


def _sample_logs():
    return [
        {
            "timestamp": "2025-12-12T10:00:00+00:00",
            "message": "Firewall allow from 192.168.0.1",
            "action": "allow",
            "source_ip": "192.168.0.1",
            "destination_ip": "10.0.0.5",
            "bytes_in": 1024,
            "bytes_out": 2048,
        },
        {
            "timestamp": "2025-12-12T10:05:00+00:00",
            "message": "Firewall deny suspicious payload",
            "action": "deny",
            "source_ip": "192.168.0.2",
            "destination_ip": "10.0.0.8",
            "bytes_in": 4096,
            "bytes_out": 1024,
        },
    ]


@pytest.mark.asyncio
async def test_process_logs_enriches_records(ml_connector):
    logs = _sample_logs()

    processed = await ml_connector.process_logs(logs)

    assert len(processed) == len(logs)
    first = processed[0]
    assert "priority" in first
    assert "processing_path" in first
    assert first["processing_path"] in {"normal", "priority", "anomaly"}
    assert "pattern_frequency" in first
    assert ml_connector.prediction_cache


@pytest.mark.asyncio
async def test_priority_predictions_cached(ml_connector):
    logs = _sample_logs()
    ml_connector.log_classifier = CountingModel()


    await ml_connector.process_logs(logs)
    assert ml_connector.log_classifier.calls == 1

    await ml_connector.process_logs(logs)
    assert ml_connector.log_classifier.calls == 1
