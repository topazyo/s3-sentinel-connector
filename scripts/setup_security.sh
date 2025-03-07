# scripts/setup_security.sh

#!/bin/bash

set -e

# Configuration
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV=$1

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

# Load environment variables
source "${SCRIPT_DIR}/env/${ENV}.env"

# Functions
log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%dT%H:%M:%S%z')] $1${NC}"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%dT%H:%M:%S%z')] ERROR: $1${NC}" >&2
}

# Setup encryption keys
setup_encryption() {
    log "Setting up encryption keys..."
    
    # Create key directory
    mkdir -p "${PROJECT_ROOT}/keys"
    
    # Generate initial encryption key
    python -c "
from src.security.encryption import EncryptionManager
manager = EncryptionManager('${PROJECT_ROOT}/keys')
manager._generate_key()
"
    
    log "Encryption keys setup complete"
}

# Setup audit logging
setup_audit() {
    log "Setting up audit logging..."
    
    # Create audit log directory
    mkdir -p "${PROJECT_ROOT}/logs/audit"
    
    # Set permissions
    chmod 700 "${PROJECT_ROOT}/logs/audit"
    
    log "Audit logging setup complete"
}

# Setup access control
setup_access_control() {
    log "Setting up access control..."
    
    # Create roles and permissions
    python -c "
from src.security.access_control import AccessControl, Role, User

ac = AccessControl('${JWT_SECRET}')

# Define roles
admin_role = Role(
    name='admin',
    permissions=['read', 'write', 'delete', 'configure']
)

operator_role = Role(
    name='operator',
    permissions=['read', 'write']
)

reader_role = Role(
    name='reader',
    permissions=['read']
)

# Add roles
ac.add_role(admin_role)
ac.add_role(operator_role)
ac.add_role(reader_role)

# Add initial admin user
admin_user = User(
    username='admin',
    roles=['admin']
)

ac.add_user(admin_user)
"
    
    log "Access control setup complete"
}

# Main setup flow
main() {
    log "Starting security setup for environment: ${ENV}"
    
    # Validate environment
    if [ -z "$ENV" ]; then
        error "Environment not specified"
        exit 1
    fi
    
    # Run setup steps
    setup_encryption
    setup_audit
    setup_access_control
    
    log "Security setup completed successfully"
}

# Execute main function
main