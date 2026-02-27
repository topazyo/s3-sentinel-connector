import asyncio
from collections import deque
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

from src.ml import enhanced_connector as ml_module
from src.ml.enhanced_connector import MLConfig, MLEnhancedConnector


class TestMLEnhancedConnector:
    def test_process_logs_returns_passthrough_when_ml_disabled(self):
        connector = MLEnhancedConnector()
        connector.ml_enabled = False

        logs = [{"message": "hello"}, {"message": "world"}]
        result = asyncio.run(connector.process_logs(logs))

        assert result["logs"] == logs
        assert result["ml_enhanced"] is False
        assert result["count"] == 2

    def test_extract_temporal_features_returns_per_log_rows(self):
        connector = MLEnhancedConnector()

        logs = [
            {"timestamp": "2026-02-27T10:00:00Z"},
            {"timestamp": "2026-02-28T22:15:00Z"},
        ]

        rows = connector._extract_temporal_features(logs)

        assert len(rows) == 2
        assert rows[0]["hour"] == 10.0
        assert rows[1]["hour"] == 22.0

    def test_extract_features_builds_rectangular_dataframe(self):
        connector = MLEnhancedConnector()
        connector.feature_extractors = {
            "one": lambda logs: [{"a": 1.0} for _ in logs],
            "two": lambda logs: [{"b": 2.0} for _ in logs],
        }

        logs = [{"message": "a"}, {"message": "b"}, {"message": "c"}]
        features = connector._extract_features(logs)

        assert isinstance(features, pd.DataFrame)
        assert features.shape == (3, 2)
        assert list(features.columns) == ["a", "b"]

    def test_process_batch_handles_async_processing_methods(self):
        connector = MLEnhancedConnector()
        batch = [
            {"priority": 0.9, "is_anomaly": False},
            {"priority": 0.1, "is_anomaly": True},
            {"priority": 0.1, "is_anomaly": False},
        ]

        result = asyncio.run(connector._process_batch(batch))

        assert len(result) == 3
        assert result[0]["processing_priority"] == "high"
        assert result[1]["processing_priority"] == "critical"
        assert result[2]["processing_priority"] == "normal"

    def test_model_load_failure_degrades_gracefully(self, monkeypatch):
        monkeypatch.setattr(ml_module, "TENSORFLOW_AVAILABLE", True)
        monkeypatch.setattr(
            MLEnhancedConnector,
            "_load_model",
            Mock(side_effect=FileNotFoundError("missing model")),
        )

        connector = MLEnhancedConnector()

        assert connector.ml_enabled is False
        assert connector.anomaly_detector is None
        assert connector.log_classifier is None

    def test_build_recent_feature_matrix_combines_frames(self):
        connector = MLEnhancedConnector()
        connector.recent_features = deque(
            [
                pd.DataFrame([{"x": 1.0, "y": 2.0}]),
                np.array([[3.0, 4.0]]),
            ]
        )

        matrix = connector._build_recent_feature_matrix()

        assert matrix is not None
        assert matrix.shape[0] == 2

    def test_prediction_cache_is_bounded_without_background_cleanup(self):
        connector = MLEnhancedConnector(config=MLConfig(cache_size=2))

        connector._set_prediction_cache("k1", np.array([1.0]))
        connector._set_prediction_cache("k2", np.array([2.0]))
        connector._set_prediction_cache("k3", np.array([3.0]))

        assert len(connector.prediction_cache) == 2
        assert "k1" not in connector.prediction_cache
        assert "k2" in connector.prediction_cache
        assert "k3" in connector.prediction_cache

    def test_history_and_recent_features_are_bounded(self):
        connector = MLEnhancedConnector(
            config=MLConfig(anomaly_history_limit=2, recent_feature_limit=2)
        )

        connector.anomaly_history.append({"id": 1})
        connector.anomaly_history.append({"id": 2})
        connector.anomaly_history.append({"id": 3})

        connector.recent_features.append(pd.DataFrame([{"x": 1.0}]))
        connector.recent_features.append(pd.DataFrame([{"x": 2.0}]))
        connector.recent_features.append(pd.DataFrame([{"x": 3.0}]))

        assert len(connector.anomaly_history) == 2
        assert connector.anomaly_history[0]["id"] == 2
        assert connector.anomaly_history[1]["id"] == 3
        assert len(connector.recent_features) == 2
