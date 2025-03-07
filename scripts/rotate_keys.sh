# scripts/rotate_keys.sh

#!/bin/bash

set -e

# Configuration
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV=$1

# Load environment variables
source "${SCRIPT_DIR}/env/${ENV}.env"

# Rotate encryption keys
python -c "
from src.security.encryption import EncryptionManager
manager = EncryptionManager('${PROJECT_ROOT}/keys')
manager._rotate_key(manager.current_key)
"

echo "Encryption keys rotated successfully"