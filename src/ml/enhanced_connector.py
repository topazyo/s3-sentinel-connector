# src/ml/enhanced_connector.py

import numpy as np
import pandas as pd
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
import tensorflow as tf
import joblib
from sklearn.preprocessing import StandardScaler
import logging
from dataclasses import dataclass
import asyncio
from collections import defaultdict

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
    def __init__(self, config: Optional[MLConfig] = None):
        """
        Initialize ML-enhanced connector
        
        Args:
            config: ML configuration
        """
        self.config = config or MLConfig()
        self.logger = logging.getLogger(__name__)
        
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
            self.anomaly_detector = self._load_model('anomaly_detection')
            
            # Load log classification model
            self.log_classifier = self._load_model('log_classification')
            
            # Load feature importance model
            self.feature_importance = self._load_model('feature_importance')
            
            self.logger.info("Successfully initialized ML models")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize ML models: {str(e)}")
            raise

    def _initialize_preprocessors(self):
        """Initialize data preprocessors"""
        try:
            # Load scalers
            self.scalers = {
                'anomaly': StandardScaler(),
                'classification': StandardScaler()
            }
            
            # Load encoders
            self.encoders = self._load_encoders()
            
            # Initialize feature extractors
            self.feature_extractors = self._initialize_feature_extractors()
            
        except Exception as e:
            self.logger.error(f"Failed to initialize preprocessors: {str(e)}")
            raise

    def _initialize_caches(self):
        """Initialize caching systems"""
        self.prediction_cache = {}
        self.feature_cache = {}
        self.pattern_cache = defaultdict(int)
        self.anomaly_history = []

    def _load_model(self, model_name: str) -> Any:
        """Load ML model from disk"""
        try:
            model_path = f"{self.config.model_path}/{model_name}"
            
            if model_name.endswith('_tf'):
                return tf.keras.models.load_model(model_path)
            else:
                return joblib.load(model_path)
                
        except Exception as e:
            self.logger.error(f"Failed to load model {model_name}: {str(e)}")
            raise

    def _load_encoders(self) -> Dict[str, Any]:
        """Load feature encoders"""
        return {
            'categorical': joblib.load(f"{self.config.model_path}/categorical_encoder"),
            'text': joblib.load(f"{self.config.model_path}/text_encoder")
        }

    def _initialize_feature_extractors(self) -> Dict[str, callable]:
        """Initialize feature extraction functions"""
        return {
            'temporal': self._extract_temporal_features,
            'textual': self._extract_textual_features,
            'numerical': self._extract_numerical_features,
            'categorical': self._extract_categorical_features
        }

    async def process_logs(self, 
                         logs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Process logs with ML enhancements
        
        Args:
            logs: List of log entries
            
        Returns:
            Processed and enhanced logs
        """
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
            self.logger.error(f"Log processing failed: {str(e)}")
            raise

    def _extract_features(self, logs: List[Dict[str, Any]]) -> pd.DataFrame:
        """Extract features from logs"""
        features = {}
        
        for extractor_name, extractor_func in self.feature_extractors.items():
            try:
                features[extractor_name] = extractor_func(logs)
            except Exception as e:
                self.logger.error(f"Feature extraction failed for {extractor_name}: {str(e)}")
                
        return pd.DataFrame(features)

    def _extract_temporal_features(self, logs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Extract temporal features"""
        features = {}
        
        for log in logs:
            timestamp = pd.to_datetime(log['timestamp'])
            features.update({
                'hour': timestamp.hour,
                'day_of_week': timestamp.dayofweek,
                'is_weekend': timestamp.dayofweek >= 5,
                'is_business_hours': 9 <= timestamp.hour <= 17
            })
            
        return features

    def _extract_textual_features(self, logs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Extract textual features"""
        text_features = []
        
        for log in logs:
            if 'message' in log:
                encoded_text = self.encoders['text'].transform([log['message']])
                text_features.append(encoded_text)
                
        return np.array(text_features)

    async def _get_priorities(self, 
                            features: pd.DataFrame) -> np.ndarray:
        """Get log priorities using classification model"""
        try:
            # Check cache first
            cache_key = self._get_cache_key(features)
            if cache_key in self.prediction_cache:
                return self.prediction_cache[cache_key]
            
            # Preprocess features
            scaled_features = self.scalers['classification'].transform(features)
            
            # Get predictions
            predictions = self.log_classifier.predict(scaled_features)
            
            # Update cache
            self.prediction_cache[cache_key] = predictions
            
            return predictions
            
        except Exception as e:
            self.logger.error(f"Priority prediction failed: {str(e)}")
            return np.ones(len(features))  # Default to highest priority

    async def _detect_anomalies(self, 
                              features: pd.DataFrame) -> np.ndarray:
        """Detect anomalies in logs"""
        try:
            # Preprocess features
            scaled_features = self.scalers['anomaly'].transform(features)
            
            # Get anomaly scores
            anomaly_scores = self.anomaly_detector.predict(scaled_features)
            
            # Apply threshold
            anomalies = anomaly_scores > self.config.anomaly_threshold
            
            # Update anomaly history
            self.anomaly_history.append({
                'timestamp': datetime.utcnow(),
                'scores': anomaly_scores,
                'anomalies': anomalies
            })
            
            return anomalies
            
        except Exception as e:
            self.logger.error(f"Anomaly detection failed: {str(e)}")
            return np.zeros(len(features))  # Default to no anomalies

    async def _identify_patterns(self, 
                               features: pd.DataFrame) -> Dict[str, Any]:
        """Identify patterns in logs"""
        patterns = {
            'clusters': self._cluster_logs(features),
            'correlations': self._find_correlations(features),
            'sequences': self._detect_sequences(features)
        }
        
        return patterns

    def _cluster_logs(self, features: pd.DataFrame) -> Dict[str, Any]:
        """Cluster logs based on features"""
        from sklearn.cluster import DBSCAN
        
        clusterer = DBSCAN(eps=0.3, min_samples=5)
        clusters = clusterer.fit_predict(features)
        
        return {
            'cluster_labels': clusters,
            'cluster_counts': np.bincount(clusters[clusters >= 0])
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
            window = features.iloc[i:i+window_size]
            pattern = self._hash_pattern(window)
            self.pattern_cache[pattern] += 1
            
            if self.pattern_cache[pattern] > 10:  # Pattern threshold
                sequences.append({
                    'start_idx': i,
                    'length': window_size,
                    'frequency': self.pattern_cache[pattern]
                })
                
        return sequences

    def _hash_pattern(self, pattern: pd.DataFrame) -> str:
        """Create hash for pattern matching"""
        return hashlib.md5(pattern.values.tobytes()).hexdigest()

    async def prioritize_processing(self, 
                                  enhanced_logs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Prioritize log processing based on ML insights"""
        # Sort by priority and anomaly status
        enhanced_logs.sort(key=lambda x: (
            x['priority'],
            x['is_anomaly'],
            x.get('pattern_frequency', 0)
        ), reverse=True)
        
        # Process in batches
        batches = [
            enhanced_logs[i:i+self.config.batch_size]
            for i in range(0, len(enhanced_logs), self.config.batch_size)
        ]
        
        processed_logs = []
        for batch in batches:
            processed_batch = await self._process_batch(batch)
            processed_logs.extend(processed_batch)
            
        return processed_logs

    async def _process_batch(self, 
                           batch: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process batch of logs"""
        tasks = []
        for log in batch:
            if log['is_anomaly']:
                tasks.append(self._process_anomaly(log))
            elif log['priority'] > 0.8:
                tasks.append(self._process_high_priority(log))
            else:
                tasks.append(self._process_normal(log))
                
        return await asyncio.gather(*tasks)

    async def _update_models(self, 
                           features: pd.DataFrame,
                           processed_logs: List[Dict[str, Any]]):
        """Update ML models with new data"""
        if len(processed_logs) < 1000:  # Minimum batch size for update
            return
            
        try:
            # Update anomaly detector
            self.anomaly_detector.partial_fit(features)
            
            # Update classifier if labels available
            labels = [log.get('true_priority') for log in processed_logs if 'true_priority' in log]
            if labels:
                self.log_classifier.partial_fit(features, labels)
                
            # Update feature importance
            self.feature_importance.update(features, labels)
            
            self.logger.info("Successfully updated ML models")
            
        except Exception as e:
            self.logger.error(f"Model update failed: {str(e)}")

    def _start_background_tasks(self):
        """Start background tasks"""
        self.tasks.extend([
            asyncio.create_task(self._periodic_model_update()),
            asyncio.create_task(self._cache_cleanup()),
            asyncio.create_task(self._pattern_analysis())
        ])

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
                self.logger.error(f"Periodic update failed: {str(e)}")
                await asyncio.sleep(60)

    def _save_models(self):
        """Save current model states"""
        for model_name, model in {
            'anomaly_detection': self.anomaly_detector,
            'log_classification': self.log_classifier,
            'feature_importance': self.feature_importance
        }.items():
            try:
                model_path = f"{self.config.model_path}/{model_name}"
                if isinstance(model, tf.keras.Model):
                    model.save(model_path)
                else:
                    joblib.dump(model, model_path)
            except Exception as e:
                self.logger.error(f"Failed to save model {model_name}: {str(e)}")

    async def cleanup(self):
        """Cleanup resources"""
        for task in self.tasks:
            task.cancel()
            
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self._save_models()