# src/ml/enhanced_connector.py
"""Optional ML enhancements for anomaly detection and enrichment in the ingestion pipeline."""

import asyncio
import hashlib
import logging
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

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
    anomaly_history_limit: int = 1000
    recent_feature_limit: int = 200


class MLEnhancedConnector:
    """Coordinates optional model loading, inference, and ML feature workflows."""

    def __init__(self, config: Optional[MLConfig] = None) -> None:
        """
        Initialize ML-enhanced connector

        Args:
            config: ML configuration

        Raises:
            ImportError: If TensorFlow is required but not installed
        """
        self.config = config or MLConfig()
        if self.config.feature_columns is None:
            self.config.feature_columns = []
        self.logger = logging.getLogger(__name__)
        self.tasks: List[asyncio.Task] = []
        self._initialize_caches()
        self._initialize_preprocessors()

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
            return

        self.ml_enabled = True

        # Initialize ML components
        self._initialize_models()

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
            self.logger.warning(
                "Failed to initialize ML models (%s). "
                "Running in degraded ML mode.",
                e,
            )
            self.ml_enabled = False
            self.anomaly_detector = None
            self.log_classifier = None
            self.feature_importance = None

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
            self.encoders = {}
            self.feature_extractors = self._initialize_feature_extractors()

    def _initialize_caches(self):
        """Initialize caching systems"""
        self.prediction_cache = {}
        self.feature_cache = {}
        self.pattern_cache = defaultdict(int)
        self.anomaly_history: Deque[Dict[str, Any]] = deque(
            maxlen=self.config.anomaly_history_limit
        )
        self.recent_features: Deque[Any] = deque(
            maxlen=self.config.recent_feature_limit
        )  # For preprocessor updates

    def _set_prediction_cache(self, cache_key: str, predictions: np.ndarray) -> None:
        """Insert prediction into cache while enforcing bounded size."""
        if cache_key in self.prediction_cache:
            self.prediction_cache[cache_key] = predictions
            return

        while len(self.prediction_cache) >= self.config.cache_size:
            oldest_key = next(iter(self.prediction_cache))
            self.prediction_cache.pop(oldest_key, None)

        self.prediction_cache[cache_key] = predictions

    def _enforce_pattern_cache_limit(self) -> None:
        """Trim least-frequent patterns to keep bounded memory usage."""
        if len(self.pattern_cache) <= self.config.cache_size:
            return

        pattern_to_evict = min(self.pattern_cache, key=self.pattern_cache.get)
        self.pattern_cache.pop(pattern_to_evict, None)

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
        encoders = {}
        encoder_paths = {
            "categorical": f"{self.config.model_path}/categorical_encoder",
            "text": f"{self.config.model_path}/text_encoder",
        }

        for encoder_name, encoder_path in encoder_paths.items():
            try:
                encoders[encoder_name] = joblib.load(encoder_path)
            except Exception:
                self.logger.debug("Encoder not available: %s", encoder_name)

        return encoders

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
        feature_rows: List[Dict[str, Any]] = [dict() for _ in logs]

        for extractor_name, extractor_func in self.feature_extractors.items():
            try:
                extracted = extractor_func(logs)
                if not isinstance(extracted, list) or len(extracted) != len(logs):
                    self.logger.warning(
                        "Extractor %s returned incompatible shape", extractor_name
                    )
                    continue

                for index, row in enumerate(extracted):
                    if isinstance(row, dict):
                        feature_rows[index].update(row)
            except Exception as e:
                self.logger.error(
                    f"Feature extraction failed for {extractor_name}: {e!s}"
                )

        if not feature_rows:
            return pd.DataFrame()

        return pd.DataFrame(feature_rows).fillna(0)

    def _extract_temporal_features(self, logs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Extract temporal features"""
        feature_rows: List[Dict[str, Any]] = []
        for log in logs:
            raw_timestamp = log.get("timestamp") or log.get("TimeGenerated")
            timestamp = pd.to_datetime(raw_timestamp, errors="coerce", utc=True)
            if pd.isna(timestamp):
                timestamp = pd.Timestamp(datetime.now(timezone.utc))

            feature_rows.append(
                {
                    "hour": float(timestamp.hour),
                    "day_of_week": float(timestamp.dayofweek),
                    "is_weekend": float(timestamp.dayofweek >= 5),
                    "is_business_hours": float(9 <= timestamp.hour <= 17),
                }
            )

        return feature_rows

    def _extract_textual_features(self, logs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Extract textual features"""
        feature_rows: List[Dict[str, Any]] = []
        for log in logs:
            message = str(log.get("message", ""))
            row: Dict[str, Any] = {
                "message_length": float(len(message)),
                "word_count": float(len(message.split())),
            }

            text_encoder = self.encoders.get("text") if hasattr(self, "encoders") else None
            if text_encoder is not None and message:
                try:
                    encoded_text = text_encoder.transform([message])
                    encoded_array = np.asarray(encoded_text).ravel()
                    if encoded_array.size > 0:
                        row["text_embedding_mean"] = float(encoded_array.mean())
                        row["text_embedding_std"] = float(encoded_array.std())
                except Exception:
                    self.logger.debug("Text encoding unavailable for message")

            feature_rows.append(row)

        return feature_rows

    async def _get_priorities(self, features: pd.DataFrame) -> np.ndarray:
        """Get log priorities using classification model"""
        try:
            if self.log_classifier is None or features.empty:
                return np.ones(len(features))

            # Check cache first
            cache_key = self._get_cache_key(features)
            if cache_key in self.prediction_cache:
                return self.prediction_cache[cache_key]

            # Preprocess features
            scaled_features = self.scalers["classification"].transform(features)

            # Get predictions
            predictions = self.log_classifier.predict(scaled_features)

            # Update cache
            self._set_prediction_cache(cache_key, predictions)

            return predictions

        except Exception as e:
            self.logger.error(f"Priority prediction failed: {e!s}")
            return np.ones(len(features))  # Default to highest priority

    async def _detect_anomalies(self, features: pd.DataFrame) -> np.ndarray:
        """Detect anomalies in logs"""
        try:
            if self.anomaly_detector is None or features.empty:
                return np.zeros(len(features))

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
            pattern_was_new = pattern not in self.pattern_cache
            self.pattern_cache[pattern] += 1
            if pattern_was_new:
                self._enforce_pattern_cache_limit()

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
        return hashlib.md5(pattern.values.tobytes(), usedforsecurity=False).hexdigest()

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
            self.recent_features.append(features)

            # Update anomaly detector
            if self.anomaly_detector is not None and hasattr(
                self.anomaly_detector, "partial_fit"
            ):
                self.anomaly_detector.partial_fit(features)

            # Update classifier if labels available
            labels = [
                log.get("true_priority")
                for log in processed_logs
                if "true_priority" in log
            ]
            if labels and self.log_classifier is not None and hasattr(
                self.log_classifier, "partial_fit"
            ):
                self.log_classifier.partial_fit(features, labels)

            # Update feature importance
            if self.feature_importance is not None and hasattr(
                self.feature_importance, "update"
            ):
                self.feature_importance.update(features, labels)

            self.logger.info("Successfully updated ML models")

        except Exception as e:
            self.logger.error(f"Model update failed: {e!s}")

    def _start_background_tasks(self):
        """Start background tasks"""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            self.logger.info(
                "No running event loop during initialization; "
                "background ML tasks were not started."
            )
            return

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
            if model is None:
                continue
            try:
                model_path = f"{self.config.model_path}/{model_name}"
                if TENSORFLOW_AVAILABLE and tf is not None and isinstance(
                    model, tf.keras.Model
                ):
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
        return hashlib.md5(feature_bytes, usedforsecurity=False).hexdigest()

    def _extract_numerical_features(
        self, logs: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Extract numerical features from logs

        Args:
            logs: Log entries

        Returns:
            Dictionary of numerical features
        """
        feature_rows: List[Dict[str, Any]] = []
        for log in logs:
            level = log.get("level", "").upper()
            feature_rows.append(
                {
                    "log_size": float(len(str(log))),
                    "has_error_level": float(level == "ERROR"),
                    "has_warning_level": float(level == "WARNING"),
                }
            )

        return feature_rows

    def _extract_categorical_features(
        self, logs: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Extract categorical features from logs

        Args:
            logs: Log entries

        Returns:
            Dictionary of categorical feature counts
        """
        level_map = {"ERROR": 3.0, "WARNING": 2.0, "INFO": 1.0, "DEBUG": 0.0}
        feature_rows: List[Dict[str, Any]] = []
        for log in logs:
            level = str(log.get("level", "UNKNOWN")).upper()
            source = str(log.get("source", "UNKNOWN"))
            log_type = str(log.get("type", "UNKNOWN"))

            feature_rows.append(
                {
                    "level_score": level_map.get(level, 0.0),
                    "source_length": float(len(source)),
                    "type_length": float(len(log_type)),
                }
            )

        return feature_rows

    async def _process_anomaly(self, log: Dict[str, Any]) -> Dict[str, Any]:
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

    async def _process_high_priority(self, log: Dict[str, Any]) -> Dict[str, Any]:
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

    async def _process_normal(self, log: Dict[str, Any]) -> Dict[str, Any]:
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
                matrix = self._build_recent_feature_matrix()
                if matrix is None or matrix.size == 0:
                    return

                for scaler_name, scaler in self.scalers.items():
                    try:
                        scaler.partial_fit(matrix)
                        self.logger.info(f"Updated {scaler_name} scaler")
                    except Exception as e:
                        self.logger.error(
                            f"Failed to update {scaler_name} scaler: {e!s}"
                        )

                # Clear recent features after update
                self.recent_features.clear()

            self.logger.debug("Preprocessors updated successfully")

        except Exception as e:
            self.logger.error(f"Preprocessor update failed: {e!s}")

    def _build_recent_feature_matrix(self) -> Optional[np.ndarray]:
        """Build a 2D numeric matrix from recent feature snapshots."""
        if not self.recent_features:
            return None

        frames: List[pd.DataFrame] = []
        for item in self.recent_features:
            if isinstance(item, pd.DataFrame):
                frames.append(item)
            elif isinstance(item, np.ndarray):
                frames.append(pd.DataFrame(item))

        if not frames:
            return None

        combined = pd.concat(frames, ignore_index=True).fillna(0)
        numeric = combined.select_dtypes(include=[np.number, bool]).astype(float)
        if numeric.empty:
            return None

        return numeric.values

    async def cleanup(self):
        """Cleanup resources"""
        for task in self.tasks:
            task.cancel()

        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        if self.ml_enabled:
            self._save_models()
