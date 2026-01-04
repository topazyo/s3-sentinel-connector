# src/ml/enhanced_connector.py

import asyncio
import hashlib
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

# Optional TensorFlow import
try:
    import tensorflow as tf

    TENSORFLOW_AVAILABLE = True
except ImportError:
    TENSORFLOW_AVAILABLE = False
    tf = None  # type: ignore


@dataclass
class MLConfig:
    """ML model configuration"""

    anomaly_threshold: float = 0.95
    batch_size: int = 1000
    feature_columns: List[str] = None
    model_path: str = "models"
    update_interval: int = 3600  # seconds
    cache_size: int = 10000


class MLEnhancedConnector:
    def __init__(self, config: Optional[MLConfig] = None) -> None:
        """
        Initialize ML-enhanced connector

        Args:
            config: ML configuration

        Raises:
            ImportError: If TensorFlow is required but not installed
        """
        self.config = config or MLConfig()
        self.logger = logging.getLogger(__name__)

        # Check TensorFlow availability
        if not TENSORFLOW_AVAILABLE:
            self.logger.warning(
                "TensorFlow not available. ML features will be disabled. "
                "Install with: pip install tensorflow"
            )
            self.ml_enabled = False
            self.anomaly_detector = None
            self.log_classifier = None
            self.feature_importance = None
            self._initialize_preprocessors()
            self._initialize_caches()
            return

        self.ml_enabled = True

        # Initialize ML components
        self._initialize_models()

        # Initialize preprocessing components
        self._initialize_preprocessors()

        # Initialize caches
        self._initialize_caches()

        # Start background tasks
        self.tasks = []
        self._start_background_tasks()

    def _initialize_models(self):
        """Initialize ML models"""
        try:
            # Load anomaly detection model
            self.anomaly_detector = self._load_model("anomaly_detection")

            # Load log classification model
            self.log_classifier = self._load_model("log_classification")

            # Load feature importance model
            self.feature_importance = self._load_model("feature_importance")

            self.logger.info("Successfully initialized ML models")

        except Exception as e:
            self.logger.error(f"Failed to initialize ML models: {e!s}")
            raise

    def _initialize_preprocessors(self):
        """Initialize data preprocessors"""
        try:
            # Load scalers
            self.scalers = {
                "anomaly": StandardScaler(),
                "classification": StandardScaler(),
            }

            # Load encoders
            self.encoders = self._load_encoders()

            # Initialize feature extractors
            self.feature_extractors = self._initialize_feature_extractors()

        except Exception as e:
            self.logger.error(f"Failed to initialize preprocessors: {e!s}")
            raise

    def _initialize_caches(self):
        """Initialize caching systems"""
        self.prediction_cache = {}
        self.feature_cache = {}
        self.pattern_cache = defaultdict(int)
        self.anomaly_history = []
        self.recent_features = []  # For preprocessor updates

    def _load_model(self, model_name: str) -> Any:
        """Load ML model from disk"""
        try:
            model_path = f"{self.config.model_path}/{model_name}"

            if model_name.endswith("_tf"):
                return tf.keras.models.load_model(model_path)
            else:
                return joblib.load(model_path)

        except Exception as e:
            self.logger.error(f"Failed to load model {model_name}: {e!s}")
            raise

    def _load_encoders(self) -> Dict[str, Any]:
        """Load feature encoders"""
        return {
            "categorical": joblib.load(f"{self.config.model_path}/categorical_encoder"),
            "text": joblib.load(f"{self.config.model_path}/text_encoder"),
        }

    def _initialize_feature_extractors(self) -> Dict[str, callable]:
        """Initialize feature extraction functions"""
        return {
            "temporal": self._extract_temporal_features,
            "textual": self._extract_textual_features,
            "numerical": self._extract_numerical_features,
            "categorical": self._extract_categorical_features,
        }

    async def process_logs(self, logs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Process logs with ML enhancements

        Args:
            logs: List of log entries

        Returns:
            Processed and enhanced logs (or original logs if ML disabled)
        """
        # If ML not available, return logs unchanged
        if not self.ml_enabled:
            self.logger.debug("ML disabled - returning logs without enhancement")
            return {"logs": logs, "ml_enhanced": False, "count": len(logs)}

        try:
            # Extract features
            features = self._extract_features(logs)

            # Get predictions
            priorities = await self._get_priorities(features)
            anomalies = await self._detect_anomalies(features)
            patterns = await self._identify_patterns(features)

            # Enhance logs with ML insights
            enhanced_logs = self._enhance_logs(logs, priorities, anomalies, patterns)

            # Prioritize processing
            processed_logs = await self.prioritize_processing(enhanced_logs)

            # Update caches and models
            await self._update_models(features, processed_logs)

            return processed_logs

        except Exception as e:
            self.logger.error(f"Log processing failed: {e!s}")
            raise

    def _extract_features(self, logs: List[Dict[str, Any]]) -> pd.DataFrame:
        """Extract features from logs"""
        features = {}

        for extractor_name, extractor_func in self.feature_extractors.items():
            try:
                features[extractor_name] = extractor_func(logs)
            except Exception as e:
                self.logger.error(
                    f"Feature extraction failed for {extractor_name}: {e!s}"
                )

        return pd.DataFrame(features)

    def _extract_temporal_features(self, logs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Extract temporal features"""
        features = {}

        for log in logs:
            timestamp = pd.to_datetime(log["timestamp"])
            features.update(
                {
                    "hour": timestamp.hour,
                    "day_of_week": timestamp.dayofweek,
                    "is_weekend": timestamp.dayofweek >= 5,
                    "is_business_hours": 9 <= timestamp.hour <= 17,
                }
            )

        return features

    def _extract_textual_features(self, logs: List[Dict[str, Any]]) -> np.ndarray:
        """Extract textual features"""
        text_features = []

        for log in logs:
            if "message" in log:
                encoded_text = self.encoders["text"].transform([log["message"]])
                text_features.append(encoded_text)

        return np.array(text_features)

    async def _get_priorities(self, features: pd.DataFrame) -> np.ndarray:
        """Get log priorities using classification model"""
        try:
            # Check cache first
            cache_key = self._get_cache_key(features)
            if cache_key in self.prediction_cache:
                return self.prediction_cache[cache_key]

            # Preprocess features
            scaled_features = self.scalers["classification"].transform(features)

            # Get predictions
            predictions = self.log_classifier.predict(scaled_features)

            # Update cache
            self.prediction_cache[cache_key] = predictions

            return predictions

        except Exception as e:
            self.logger.error(f"Priority prediction failed: {e!s}")
            return np.ones(len(features))  # Default to highest priority

    async def _detect_anomalies(self, features: pd.DataFrame) -> np.ndarray:
        """Detect anomalies in logs"""
        try:
            # Preprocess features
            scaled_features = self.scalers["anomaly"].transform(features)

            # Get anomaly scores
            anomaly_scores = self.anomaly_detector.predict(scaled_features)

            # Apply threshold
            anomalies = anomaly_scores > self.config.anomaly_threshold

            # Update anomaly history
            self.anomaly_history.append(
                {
                    "timestamp": datetime.now(timezone.utc),
                    "scores": anomaly_scores,
                    "anomalies": anomalies,
                }
            )

            return anomalies

        except Exception as e:
            self.logger.error(f"Anomaly detection failed: {e!s}")
            return np.zeros(len(features))  # Default to no anomalies

    async def _identify_patterns(self, features: pd.DataFrame) -> Dict[str, Any]:
        """Identify patterns in logs"""
        patterns = {
            "clusters": self._cluster_logs(features),
            "correlations": self._find_correlations(features),
            "sequences": self._detect_sequences(features),
        }

        return patterns

    def _cluster_logs(self, features: pd.DataFrame) -> Dict[str, Any]:
        """Cluster logs based on features"""
        from sklearn.cluster import DBSCAN

        clusterer = DBSCAN(eps=0.3, min_samples=5)
        clusters = clusterer.fit_predict(features)

        return {
            "cluster_labels": clusters,
            "cluster_counts": np.bincount(clusters[clusters >= 0]),
        }

    def _find_correlations(self, features: pd.DataFrame) -> Dict[str, float]:
        """Find correlations between features"""
        correlations = {}

        for col1 in features.columns:
            for col2 in features.columns:
                if col1 < col2:
                    corr = features[col1].corr(features[col2])
                    if abs(corr) > 0.7:  # Strong correlation threshold
                        correlations[f"{col1}_{col2}"] = corr

        return correlations

    def _detect_sequences(self, features: pd.DataFrame) -> List[Dict[str, Any]]:
        """Detect sequential patterns in logs"""
        sequences = []
        window_size = 5

        for i in range(len(features) - window_size + 1):
            window = features.iloc[i : i + window_size]
            pattern = self._hash_pattern(window)
            self.pattern_cache[pattern] += 1

            if self.pattern_cache[pattern] > 10:  # Pattern threshold
                sequences.append(
                    {
                        "start_idx": i,
                        "length": window_size,
                        "frequency": self.pattern_cache[pattern],
                    }
                )

        return sequences

    def _hash_pattern(self, pattern: pd.DataFrame) -> str:
        """Create hash for pattern matching"""
        return hashlib.md5(pattern.values.tobytes()).hexdigest()

    async def prioritize_processing(
        self, enhanced_logs: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Prioritize log processing based on ML insights"""
        # Sort by priority and anomaly status
        enhanced_logs.sort(
            key=lambda x: (
                x["priority"],
                x["is_anomaly"],
                x.get("pattern_frequency", 0),
            ),
            reverse=True,
        )

        # Process in batches
        batches = [
            enhanced_logs[i : i + self.config.batch_size]
            for i in range(0, len(enhanced_logs), self.config.batch_size)
        ]

        processed_logs = []
        for batch in batches:
            processed_batch = await self._process_batch(batch)
            processed_logs.extend(processed_batch)

        return processed_logs

    async def _process_batch(self, batch: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process batch of logs"""
        tasks = []
        for log in batch:
            if log["is_anomaly"]:
                tasks.append(self._process_anomaly(log))
            elif log["priority"] > 0.8:
                tasks.append(self._process_high_priority(log))
            else:
                tasks.append(self._process_normal(log))

        return await asyncio.gather(*tasks)

    async def _update_models(
        self, features: pd.DataFrame, processed_logs: List[Dict[str, Any]]
    ):
        """Update ML models with new data"""
        if len(processed_logs) < 1000:  # Minimum batch size for update
            return

        try:
            # Update anomaly detector
            self.anomaly_detector.partial_fit(features)

            # Update classifier if labels available
            labels = [
                log.get("true_priority")
                for log in processed_logs
                if "true_priority" in log
            ]
            if labels:
                self.log_classifier.partial_fit(features, labels)

            # Update feature importance
            self.feature_importance.update(features, labels)

            self.logger.info("Successfully updated ML models")

        except Exception as e:
            self.logger.error(f"Model update failed: {e!s}")

    def _start_background_tasks(self):
        """Start background tasks"""
        self.tasks.extend(
            [
                asyncio.create_task(self._periodic_model_update()),
                asyncio.create_task(self._cache_cleanup()),
                asyncio.create_task(self._pattern_analysis()),
            ]
        )

    async def _periodic_model_update(self):
        """Periodically update models"""
        while True:
            try:
                # Save models
                self._save_models()

                # Update preprocessors
                self._update_preprocessors()

                await asyncio.sleep(self.config.update_interval)

            except Exception as e:
                self.logger.error(f"Periodic update failed: {e!s}")
                await asyncio.sleep(60)

    def _save_models(self):
        """Save current model states"""
        for model_name, model in {
            "anomaly_detection": self.anomaly_detector,
            "log_classification": self.log_classifier,
            "feature_importance": self.feature_importance,
        }.items():
            try:
                model_path = f"{self.config.model_path}/{model_name}"
                if isinstance(model, tf.keras.Model):
                    model.save(model_path)
                else:
                    joblib.dump(model, model_path)
            except Exception as e:
                self.logger.error(f"Failed to save model {model_name}: {e!s}")

    # Missing method implementations (H4 fixes)

    def _enhance_logs(
        self,
        logs: List[Dict[str, Any]],
        priorities: np.ndarray,
        anomalies: np.ndarray,
        patterns: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Enhance logs with ML insights

        Args:
            logs: Original log entries
            priorities: Priority scores from classification
            anomalies: Anomaly detection results
            patterns: Identified patterns

        Returns:
            Enhanced logs with ML metadata
        """
        enhanced = []
        for i, log in enumerate(logs):
            enhanced_log = log.copy()
            enhanced_log["priority"] = (
                float(priorities[i]) if i < len(priorities) else 0.5
            )
            enhanced_log["is_anomaly"] = (
                bool(anomalies[i]) if i < len(anomalies) else False
            )
            enhanced_log["ml_insights"] = {
                "priority_score": float(priorities[i]) if i < len(priorities) else 0.5,
                "anomaly_score": float(anomalies[i]) if i < len(anomalies) else 0.0,
                "pattern_info": self._get_pattern_info(i, patterns),
            }
            enhanced.append(enhanced_log)
        return enhanced

    def _get_pattern_info(self, index: int, patterns: Dict[str, Any]) -> Dict[str, Any]:
        """Get pattern information for a specific log entry"""
        info = {}
        if "sequences" in patterns:
            for seq in patterns["sequences"]:
                if seq["start_idx"] <= index < seq["start_idx"] + seq["length"]:
                    info["sequence_id"] = seq["start_idx"]
                    info["frequency"] = seq["frequency"]
                    break
        return info

    def _get_cache_key(self, features: pd.DataFrame) -> str:
        """
        Generate cache key for features

        Args:
            features: Feature DataFrame

        Returns:
            Hash key for caching
        """
        # Create a hash from feature values
        feature_bytes = features.values.tobytes()
        return hashlib.md5(feature_bytes).hexdigest()

    def _extract_numerical_features(
        self, logs: List[Dict[str, Any]]
    ) -> Dict[str, float]:
        """
        Extract numerical features from logs

        Args:
            logs: Log entries

        Returns:
            Dictionary of numerical features
        """
        features = {
            "log_count": len(logs),
            "avg_size": 0.0,
            "max_size": 0.0,
            "error_count": 0,
            "warning_count": 0,
        }

        sizes = []
        for log in logs:
            # Calculate log entry size
            log_str = str(log)
            sizes.append(len(log_str))

            # Count severity levels
            level = log.get("level", "").upper()
            if level == "ERROR":
                features["error_count"] += 1
            elif level == "WARNING":
                features["warning_count"] += 1

        if sizes:
            features["avg_size"] = sum(sizes) / len(sizes)
            features["max_size"] = max(sizes)

        return features

    def _extract_categorical_features(
        self, logs: List[Dict[str, Any]]
    ) -> Dict[str, int]:
        """
        Extract categorical features from logs

        Args:
            logs: Log entries

        Returns:
            Dictionary of categorical feature counts
        """
        features = defaultdict(int)

        for log in logs:
            # Count log levels
            level = log.get("level", "UNKNOWN")
            features[f"level_{level}"] += 1

            # Count sources
            source = log.get("source", "UNKNOWN")
            features[f"source_{source}"] += 1

            # Count types
            log_type = log.get("type", "UNKNOWN")
            features[f"type_{log_type}"] += 1

        return dict(features)

    def _process_anomaly(self, log: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process anomalous log entry

        Args:
            log: Anomalous log entry

        Returns:
            Processed log with anomaly handling
        """
        log["processing_priority"] = "critical"
        log["requires_review"] = True
        log["anomaly_timestamp"] = datetime.now(timezone.utc).isoformat()

        # Log anomaly for monitoring
        self.logger.warning(
            f"Anomaly detected in log: {log.get('message', 'No message')}"
        )

        return log

    def _process_high_priority(self, log: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process high-priority log entry

        Args:
            log: High-priority log entry

        Returns:
            Processed log with priority handling
        """
        log["processing_priority"] = "high"
        log["requires_attention"] = True

        return log

    def _process_normal(self, log: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process normal log entry

        Args:
            log: Normal log entry

        Returns:
            Processed log
        """
        log["processing_priority"] = "normal"

        return log

    async def _cache_cleanup(self):
        """Background task to clean up expired cache entries"""
        while True:
            try:
                # Clean prediction cache
                if len(self.prediction_cache) > self.config.cache_size:
                    # Remove oldest entries (simple FIFO)
                    keys_to_remove = list(self.prediction_cache.keys())[
                        : len(self.prediction_cache) - self.config.cache_size
                    ]
                    for key in keys_to_remove:
                        del self.prediction_cache[key]

                    self.logger.info(f"Cleaned {len(keys_to_remove)} cache entries")

                # Clean pattern cache
                if len(self.pattern_cache) > self.config.cache_size:
                    self.pattern_cache.clear()
                    self.logger.info("Cleared pattern cache")

                await asyncio.sleep(300)  # Run every 5 minutes

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Cache cleanup failed: {e!s}")
                await asyncio.sleep(60)

    async def _pattern_analysis(self):
        """Background task to analyze patterns periodically"""
        while True:
            try:
                # Analyze frequent patterns
                if self.pattern_cache:
                    frequent_patterns = sorted(
                        self.pattern_cache.items(), key=lambda x: x[1], reverse=True
                    )[
                        :10
                    ]  # Top 10 patterns

                    self.logger.info(
                        f"Top patterns: {len(frequent_patterns)} unique patterns identified"
                    )

                    # Store analysis results
                    for pattern_hash, frequency in frequent_patterns:
                        if frequency > 100:  # Significant pattern threshold
                            self.logger.info(
                                f"High-frequency pattern detected: {pattern_hash} ({frequency} occurrences)"
                            )

                await asyncio.sleep(600)  # Run every 10 minutes

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Pattern analysis failed: {e!s}")
                await asyncio.sleep(60)

    def _update_preprocessors(self):
        """Update feature preprocessors with recent data"""
        try:
            # Update scalers if we have enough data
            if hasattr(self, "recent_features") and len(self.recent_features) > 100:
                for scaler_name, scaler in self.scalers.items():
                    try:
                        scaler.partial_fit(self.recent_features)
                        self.logger.info(f"Updated {scaler_name} scaler")
                    except Exception as e:
                        self.logger.error(
                            f"Failed to update {scaler_name} scaler: {e!s}"
                        )

                # Clear recent features after update
                self.recent_features = []

            self.logger.debug("Preprocessors updated successfully")

        except Exception as e:
            self.logger.error(f"Preprocessor update failed: {e!s}")

    async def cleanup(self):
        """Cleanup resources"""
        for task in self.tasks:
            task.cancel()

        await asyncio.gather(*self.tasks, return_exceptions=True)
        self._save_models()
