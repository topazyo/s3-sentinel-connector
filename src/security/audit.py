# src/security/audit.py

import logging
from datetime import datetime
from typing import Dict, Any, Optional
import json
import hashlib
from dataclasses import dataclass, asdict

@dataclass
class AuditEvent:
    """Audit event data structure"""
    timestamp: str
    event_type: str
    user: str
    action: str
    resource: str
    status: str
    details: Dict[str, Any]
    source_ip: Optional[str] = None
    correlation_id: Optional[str] = None

class AuditLogger:
    def __init__(self, log_path: str) -> None:
        """
        Initialize audit logger
        
        Args:
            log_path: Path to audit log file
        """
        self.log_path = log_path
        self._setup_logger()

    def _setup_logger(self) -> None:
        """Set up audit logger"""
        self.logger = logging.getLogger('audit')
        self.logger.setLevel(logging.INFO)
        
        # File handler
        handler = logging.FileHandler(self.log_path)
        handler.setFormatter(
            logging.Formatter('%(asctime)s|%(message)s')
        )
        self.logger.addHandler(handler)

    def log_event(self, event: AuditEvent) -> None:
        """
        Log audit event
        
        Args:
            event: Audit event to log
        """
        try:
            # Add hash for integrity verification
            event_dict = asdict(event)
            event_dict['hash'] = self._generate_event_hash(event_dict)
            
            self.logger.info(json.dumps(event_dict))
            
        except Exception as e:
            self.logger.error(f"Failed to log audit event: {str(e)}")
            raise

    def _generate_event_hash(self, event_dict: Dict[str, Any]) -> str:
        """Generate hash for event verification"""
        event_str = json.dumps(event_dict, sort_keys=True)
        return hashlib.sha256(event_str.encode()).hexdigest()

    def verify_log_integrity(self) -> bool:
        """Verify integrity of audit log"""
        try:
            with open(self.log_path, 'r') as f:
                for line in f:
                    timestamp, event_json = line.strip().split('|', 1)
                    event_dict = json.loads(event_json)
                    
                    # Extract and verify hash
                    original_hash = event_dict.pop('hash', None)
                    if not original_hash:
                        return False
                        
                    current_hash = self._generate_event_hash(event_dict)
                    if original_hash != current_hash:
                        return False
                        
            return True
            
        except Exception as e:
            self.logger.error(f"Log integrity verification failed: {str(e)}")
            return False