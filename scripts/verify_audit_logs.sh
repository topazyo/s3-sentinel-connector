# scripts/verify_audit_logs.sh

#!/bin/bash

set -e

# Configuration
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV=$1

# Verify audit log integrity
python -c "
from src.security.audit import AuditLogger
logger = AuditLogger('${PROJECT_ROOT}/logs/audit/audit.log')
if logger.verify_log_integrity():
    print('Audit log integrity verified')
else:
    print('Audit log integrity check failed')
    exit(1)
"