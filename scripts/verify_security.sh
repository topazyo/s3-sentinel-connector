#!/bin/bash
# scripts/verify_security.sh

set -e

# Configuration
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV=${1:-"prod"}

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Load environment variables
source "${SCRIPT_DIR}/env/${ENV}.env"

# Functions
log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%dT%H:%M:%S%z')] $1${NC}"
}

warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%dT%H:%M:%S%z')] WARNING: $1${NC}"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%dT%H:%M:%S%z')] ERROR: $1${NC}" >&2
}

success() {
    echo -e "${GREEN}✓ $1${NC}"
}

failure() {
    echo -e "${RED}✗ $1${NC}"
}

# Verify Key Vault
verify_key_vault() {
    log "Verifying Key Vault configuration..."
    
    # Check if Key Vault exists
    KV_EXISTS=$(az keyvault show --name "${KEY_VAULT_NAME}" --query name --output tsv 2>/dev/null || echo "")
    
    if [ -z "${KV_EXISTS}" ]; then
        failure "Key Vault ${KEY_VAULT_NAME} does not exist"
        return 1
    else
        success "Key Vault ${KEY_VAULT_NAME} exists"
    fi
    
    # Check required secrets
    REQUIRED_SECRETS=("aws-access-key" "aws-secret-key" "sentinel-workspace-id" "sentinel-key" "jwt-secret" "encryption-key")
    MISSING_SECRETS=()
    
    for secret in "${REQUIRED_SECRETS[@]}"; do
        SECRET_EXISTS=$(az keyvault secret show --vault-name "${KEY_VAULT_NAME}" --name "${secret}" --query id --output tsv 2>/dev/null || echo "")
        
        if [ -z "${SECRET_EXISTS}" ]; then
            MISSING_SECRETS+=("${secret}")
            failure "Secret ${secret} is missing"
        else
            success "Secret ${secret} exists"
        fi
    done
    
    if [ ${#MISSING_SECRETS[@]} -gt 0 ]; then
        warn "Missing secrets: ${MISSING_SECRETS[*]}"
        return 1
    fi
    
    # Check Key Vault network configuration
    NETWORK_RULES=$(az keyvault network-rule list --name "${KEY_VAULT_NAME}" --query '{default_action:defaultAction,ip_rules:ipRules[].value}' --output json)
    
    echo "Network configuration:"
    echo "${NETWORK_RULES}" | jq .
    
    DEFAULT_ACTION=$(echo "${NETWORK_RULES}" | jq -r '.default_action')
    if [ "${DEFAULT_ACTION}" == "Deny" ]; then
        success "Key Vault has restricted network access"
    else
        warn "Key Vault has open network access (default_action: ${DEFAULT_ACTION})"
    fi
    
    return 0
}

# Verify encryption
verify_encryption() {
    log "Verifying encryption configuration..."
    
    # Check encryption key
    KEY_FILE="${PROJECT_ROOT}/keys/encryption.key"
    if [ -f "${KEY_FILE}" ]; then
        success "Encryption key file exists"
        
        # Check file permissions
        PERMS=$(stat -c "%a" "${KEY_FILE}")
        if [ "${PERMS}" == "600" ]; then
            success "Encryption key has correct permissions (600)"
        else
            failure "Encryption key has incorrect permissions: ${PERMS} (should be 600)"
        fi
    else
        failure "Encryption key file is missing"
    fi
    
    # Verify encryption functionality
    log "Testing encryption functionality..."
    
    TEST_DATA="This is a test string for encryption verification"
    TEST_FILE="/tmp/encryption_test"
    
    # Run encryption test using the application
    python -c "
from src.security.encryption import EncryptionManager
import os

# Initialize encryption manager
manager = EncryptionManager('${PROJECT_ROOT}/keys')

# Test encryption
test_data = '${TEST_DATA}'.encode()
encrypted = manager.encrypt(test_data)
decrypted = manager.decrypt(encrypted)

# Verify
if decrypted == test_data:
    print('Encryption test passed')
    exit(0)
else:
    print('Encryption test failed')
    exit(1)
"
    
    if [ $? -eq 0 ]; then
        success "Encryption functionality verified"
    else
        failure "Encryption functionality test failed"
    fi
    
    return 0
}

# Verify audit logging
verify_audit_logging() {
    log "Verifying audit logging configuration..."
    
    # Check audit log directory
    AUDIT_DIR="${PROJECT_ROOT}/logs/audit"
    if [ -d "${AUDIT_DIR}" ]; then
        success "Audit log directory exists"
        
        # Check directory permissions
        PERMS=$(stat -c "%a" "${AUDIT_DIR}")
        if [ "${PERMS}" == "700" ]; then
            success "Audit log directory has correct permissions (700)"
        else
            failure "Audit log directory has incorrect permissions: ${PERMS} (should be 700)"
        fi
    else
        failure "Audit log directory is missing"
    fi
    
    # Check audit log file
    AUDIT_FILE="${AUDIT_DIR}/audit.log"
    if [ -f "${AUDIT_FILE}" ]; then
        success "Audit log file exists"
        
        # Check file permissions
        PERMS=$(stat -c "%a" "${AUDIT_FILE}")
        if [ "${PERMS}" == "600" ]; then
            success "Audit log file has correct permissions (600)"
        else
            failure "Audit log file has incorrect permissions: ${PERMS} (should be 600)"
        fi
    else
        failure "Audit log file is missing"
    fi
    
    # Verify audit logging functionality
    log "Testing audit logging functionality..."
    
    # Run audit logging test
    python -c "
from src.security.audit import AuditLogger, AuditEvent
from datetime import datetime

# Initialize audit logger
logger = AuditLogger('${AUDIT_FILE}')

# Create test event
event = AuditEvent(
    timestamp=datetime.utcnow().isoformat(),
    event_type='security_test',
    user='security_verifier',
    action='verify_audit',
    resource='audit_system',
    status='success',
    details={'test': True},
    source_ip='127.0.0.1',
    correlation_id='verify-security-test'
)

# Log event
logger.log_event(event)

# Verify integrity
if logger.verify_log_integrity():
    print('Audit logging test passed')
    exit(0)
else:
    print('Audit logging test failed')
    exit(1)
"
    
    if [ $? -eq 0 ]; then
        success "Audit logging functionality verified"
    else
        failure "Audit logging functionality test failed"
    fi
    
    return 0
}

# Verify RBAC
verify_rbac() {
    log "Verifying RBAC configuration..."
    
    # Check roles directory
    ROLES_DIR="${PROJECT_ROOT}/config/roles"
    if [ -d "${ROLES_DIR}" ]; then
        success "Roles directory exists"
    else
        failure "Roles directory is missing"
        return 1
    fi
    
    # Check required role files
    REQUIRED_ROLES=("admin.json" "operator.json" "reader.json")
    MISSING_ROLES=()
    
    for role in "${REQUIRED_ROLES[@]}"; do
        if [ -f "${ROLES_DIR}/${role}" ]; then
            success "Role file ${role} exists"
            
            # Validate role file format
            if jq empty "${ROLES_DIR}/${role}" 2>/dev/null; then
                success "Role file ${role} has valid JSON format"
            else
                failure "Role file ${role} has invalid JSON format"
            fi
        else
            MISSING_ROLES+=("${role}")
            failure "Role file ${role} is missing"
        fi
    done
    
    if [ ${#MISSING_ROLES[@]} -gt 0 ]; then
        warn "Missing role files: ${MISSING_ROLES[*]}"
        return 1
    fi
    
    # Verify RBAC functionality
    log "Testing RBAC functionality..."
    
    # Run RBAC test
    python -c "
from src.security.access_control import AccessControl, Role, User
import os

# Get JWT secret from environment or use test value
jwt_secret = os.environ.get('JWT_SECRET', 'test-jwt-secret')

# Initialize access control
ac = AccessControl(jwt_secret)

# Define test roles
admin_role = Role(
    name='admin',
    permissions=['read', 'write', 'delete', 'configure']
)

reader_role = Role(
    name='reader',
    permissions=['read']
)

# Add roles
ac.add_role(admin_role)
ac.add_role(reader_role)

# Add test users
admin_user = User(
    username='admin_test',
    roles=['admin']
)

reader_user = User(
    username='reader_test',
    roles=['reader']
)

ac.add_user(admin_user)
ac.add_user(reader_user)

# Test permissions
admin_can_write = ac.has_permission('admin_test', 'write')
reader_can_write = ac.has_permission('reader_test', 'write')
reader_can_read = ac.has_permission('reader_test', 'read')

# Test token generation and validation
admin_token = ac.generate_token('admin_test')
try:
    payload = ac.validate_token(admin_token)
    token_valid = True
except Exception as e:
    token_valid = False

# Verify results
if admin_can_write and not reader_can_write and reader_can_read and token_valid:
    print('RBAC test passed')
    exit(0)
else:
    print('RBAC test failed')
    exit(1)
"
    
    if [ $? -eq 0 ]; then
        success "RBAC functionality verified"
    else
        failure "RBAC functionality test failed"
    fi
    
    return 0
}

# Main function
main() {
    log "Starting security verification for environment: ${ENV}"
    
    FAILURES=0
    
    # Verify Key Vault
    if ! verify_key_vault; then
        FAILURES=$((FAILURES+1))
    fi
    
    # Verify encryption
    if ! verify_encryption; then
        FAILURES=$((FAILURES+1))
    fi
    
    # Verify audit logging
    if ! verify_audit_logging; then
        FAILURES=$((FAILURES+1))
    fi
    
    # Verify RBAC
    if ! verify_rbac; then
        FAILURES=$((FAILURES+1))
    fi
    
    # Summary
    echo ""
    log "Security verification summary:"
    
    if [ ${FAILURES} -eq 0 ]; then
        success "All security checks passed"
    else
        failure "${FAILURES} security checks failed"
        exit 1
    fi
}

# Execute main function
main