#!/bin/bash
# scripts/check_compliance.sh

set -e

# Configuration
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV=${1:-"prod"}
COMPLIANCE_LEVEL=${2:-"standard"}

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

# Check data protection compliance
check_data_protection() {
    log "Checking data protection compliance..."
    
    FAILURES=0
    
    # Check encryption at rest
    if [ -f "${PROJECT_ROOT}/keys/encryption.key" ]; then
        success "Encryption at rest is configured"
    else
        failure "Encryption at rest is not configured"
        FAILURES=$((FAILURES+1))
    fi
    
    # Check secure credential storage
    if [ -n "${KEY_VAULT_NAME}" ]; then
        KV_EXISTS=$(az keyvault show --name "${KEY_VAULT_NAME}" --query name --output tsv 2>/dev/null || echo "")
        
        if [ -n "${KV_EXISTS}" ]; then
            success "Secure credential storage is configured"
        else
            failure "Key Vault ${KEY_VAULT_NAME} does not exist"
            FAILURES=$((FAILURES+1))
        fi
    else
        failure "Secure credential storage is not configured"
        FAILURES=$((FAILURES+1))
    fi
    
    # Check data retention policy
    RETENTION_CONFIG="${PROJECT_ROOT}/config/retention.yaml"
    if [ -f "${RETENTION_CONFIG}" ]; then
        success "Data retention policy is configured"
    else
        failure "Data retention policy is not configured"
        FAILURES=$((FAILURES+1))
    fi
    
    # Check for sensitive data in code
    log "Checking for sensitive data in code..."
    
    SENSITIVE_PATTERNS=(
        "password"
        "secret"
        "token"
        "key"
        "credential"
    )
    
    SENSITIVE_FILES=()
    
    for pattern in "${SENSITIVE_PATTERNS[@]}"; do
        FOUND_FILES=$(grep -l -r --include="*.py" --include="*.sh" --include="*.yaml" --include="*.json" -i "${pattern}=" "${PROJECT_ROOT}/src" 2>/dev/null || echo "")
        
        if [ -n "${FOUND_FILES}" ]; then
            SENSITIVE_FILES+=("${FOUND_FILES}")
        fi
    done
    
    if [ ${#SENSITIVE_FILES[@]} -eq 0 ]; then
        success "No sensitive data found in code"
    else
        failure "Potential sensitive data found in code"
        echo "Files to review:"
        for file in "${SENSITIVE_FILES[@]}"; do
            echo "  - ${file}"
        done
        FAILURES=$((FAILURES+1))
    fi
    
    return ${FAILURES}
}

# Check access control compliance
check_access_control() {
    log "Checking access control compliance..."
    
    FAILURES=0
    
    # Check RBAC configuration
    ROLES_DIR="${PROJECT_ROOT}/config/roles"
    if [ -d "${ROLES_DIR}" ] && [ -f "${ROLES_DIR}/admin.json" ]; then
        success "RBAC is configured"
    else
        failure "RBAC is not properly configured"
        FAILURES=$((FAILURES+1))
    fi
    
    # Check JWT configuration
    JWT_CONFIG=$(grep -l "jwt_secret" "${PROJECT_ROOT}/src" --include="*.py" 2>/dev/null || echo "")
    if [ -n "${JWT_CONFIG}" ]; then
        success "JWT authentication is configured"
    else
        failure "JWT authentication is not configured"
        FAILURES=$((FAILURES+1))
    fi
    
    # Check for principle of least privilege
    if [ "${COMPLIANCE_LEVEL}" == "high" ]; then
        log "Checking for principle of least privilege..."
        
        # Check AWS IAM policies
        if [ -n "${AWS_ACCESS_KEY}" ]; then
            log "Checking AWS IAM policies..."
            
            # This would require AWS CLI with appropriate permissions
            # For this script, we'll just check for policy files
            
            IAM_POLICIES="${PROJECT_ROOT}/config/iam"
            if [ -d "${IAM_POLICIES}" ]; then
                success "AWS IAM policies are defined"
            else
                warn "AWS IAM policies directory not found"
            fi
        fi
    fi
    
    return ${FAILURES}
}

# Check audit logging compliance
check_audit_logging() {
    log "Checking audit logging compliance..."
    
    FAILURES=0
    
    # Check audit log configuration
    AUDIT_DIR="${PROJECT_ROOT}/logs/audit"
    AUDIT_FILE="${AUDIT_DIR}/audit.log"
    
    if [ -d "${AUDIT_DIR}" ] && [ -f "${AUDIT_FILE}" ]; then
        success "Audit logging is configured"
        
        # Check permissions
        PERMS=$(stat -c "%a" "${AUDIT_FILE}")
        if [ "${PERMS}" == "600" ]; then
            success "Audit log has correct permissions"
        else
            failure "Audit log has incorrect permissions: ${PERMS} (should be 600)"
            FAILURES=$((FAILURES+1))
        fi
    else
        failure "Audit logging is not configured"
        FAILURES=$((FAILURES+1))
    fi
    
    # Check audit log content
    if [ -f "${AUDIT_FILE}" ]; then
        LOG_SIZE=$(stat -c "%s" "${AUDIT_FILE}")
        if [ ${LOG_SIZE} -gt 0 ]; then
            success "Audit log contains entries"
            
            # Check for required event types
            REQUIRED_EVENTS=("authentication" "authorization" "configuration")
            MISSING_EVENTS=()
            
            for event in "${REQUIRED_EVENTS[@]}"; do
                if ! grep -q "\"event_type\":\"${event}\"" "${AUDIT_FILE}"; then
                    MISSING_EVENTS+=("${event}")
                fi
            done
            
            if [ ${#MISSING_EVENTS[@]} -eq 0 ]; then
                success "Audit log contains all required event types"
            else
                warn "Audit log is missing events: ${MISSING_EVENTS[*]}"
            fi
        else
            warn "Audit log is empty"
        fi
    fi
    
    # Check log integrity
    python -c "
from src.security.audit import AuditLogger
import os

audit_file = '${AUDIT_FILE}'
if os.path.exists(audit_file):
    logger = AuditLogger(audit_file)
    if logger.verify_log_integrity():
        print('Audit log integrity verified')
        exit(0)
    else:
        print('Audit log integrity check failed')
        exit(1)
else:
    print('Audit file not found')
    exit(1)
"
    
    if [ $? -eq 0 ]; then
        success "Audit log integrity verified"
    else
        failure "Audit log integrity check failed"
        FAILURES=$((FAILURES+1))
    fi
    
    return ${FAILURES}
}

# Check network security compliance
check_network_security() {
    log "Checking network security compliance..."
    
    FAILURES=0
    
    # Check TLS configuration
    TLS_CONFIG="${PROJECT_ROOT}/config/tls.yaml"
    if [ -f "${TLS_CONFIG}" ]; then
        success "TLS configuration exists"
        
        # Check TLS version
        TLS_VERSION=$(grep "min_version" "${TLS_CONFIG}" | cut -d: -f2 | tr -d ' ')
        if [ "${TLS_VERSION}" == "1.2" ] || [ "${TLS_VERSION}" == "1.3" ]; then
            success "TLS version is compliant (${TLS_VERSION})"
        else
            failure "TLS version is not compliant: ${TLS_VERSION} (should be 1.2 or 1.3)"
            FAILURES=$((FAILURES+1))
        fi
    else
        failure "TLS configuration is missing"
        FAILURES=$((FAILURES+1))
    fi
    
    # Check network isolation
    if [ -n "${VNET_NAME}" ] && [ -n "${SUBNET_NAME}" ]; then
        # Check if NSG exists
        NSG_NAME="${APP_NAME}-nsg"
        NSG_EXISTS=$(az network nsg show --name "${NSG_NAME}" --resource-group "${RESOURCE_GROUP}" --query name --output tsv 2>/dev/null || echo "")
        
        if [ -n "${NSG_EXISTS}" ]; then
            success "Network Security Group is configured"
            
            # Check default deny rule
            DENY_RULE=$(az network nsg rule show --name "DenyAllInbound" --nsg-name "${NSG_NAME}" --resource-group "${RESOURCE_GROUP}" --query name --output tsv 2>/dev/null || echo "")
            
            if [ -n "${DENY_RULE}" ]; then
                success "Default deny rule is configured"
            else
                failure "Default deny rule is missing"
                FAILURES=$((FAILURES+1))
            fi
        else
            failure "Network Security Group is not configured"
            FAILURES=$((FAILURES+1))
        fi
    else
        warn "Network isolation check skipped (VNET_NAME or SUBNET_NAME not provided)"
    fi
    
    return ${FAILURES}
}

# Check dependency security
check_dependency_security() {
    log "Checking dependency security..."
    
    FAILURES=0
    
    # Check for vulnerable dependencies
    if command -v safety &> /dev/null; then
        log "Running safety check on dependencies..."
        
        SAFETY_OUTPUT=$(safety check -r "${PROJECT_ROOT}/requirements.txt" --json)
        VULN_COUNT=$(echo "${SAFETY_OUTPUT}" | jq 'length')
        
        if [ "${VULN_COUNT}" -eq 0 ]; then
            success "No vulnerable dependencies found"
        else
            failure "${VULN_COUNT} vulnerable dependencies found"
            echo "${SAFETY_OUTPUT}" | jq '.[].advisory'
            FAILURES=$((FAILURES+1))
        fi
    else
        warn "safety not installed, skipping dependency security check"
        warn "Install with: pip install safety"
    fi
    
    # Check for dependency pinning
    UNPINNED_DEPS=$(grep -v "==" "${PROJECT_ROOT}/requirements.txt" | grep -v "^#" | grep -v "^$")
    
    if [ -z "${UNPINNED_DEPS}" ]; then
        success "All dependencies are pinned to specific versions"
    else
        failure "Unpinned dependencies found:"
        echo "${UNPINNED_DEPS}"
        FAILURES=$((FAILURES+1))
    fi
    
    return ${FAILURES}
}

# Generate compliance report
generate_report() {
    log "Generating compliance report..."
    
    REPORT_FILE="${PROJECT_ROOT}/compliance_report_${ENV}_$(date +%Y%m%d).json"
    
    cat > "${REPORT_FILE}" << EOF
{
    "environment": "${ENV}",
    "compliance_level": "${COMPLIANCE_LEVEL}",
    "timestamp": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
    "results": {
        "data_protection": {
            "status": "$([ ${DATA_PROTECTION_FAILURES} -eq 0 ] && echo "compliant" || echo "non-compliant")",
            "failures": ${DATA_PROTECTION_FAILURES}
        },
        "access_control": {
            "status": "$([ ${ACCESS_CONTROL_FAILURES} -eq 0 ] && echo "compliant" || echo "non-compliant")",
            "failures": ${ACCESS_CONTROL_FAILURES}
        },
        "audit_logging": {
            "status": "$([ ${AUDIT_LOGGING_FAILURES} -eq 0 ] && echo "compliant" || echo "non-compliant")",
            "failures": ${AUDIT_LOGGING_FAILURES}
        },
        "network_security": {
            "status": "$([ ${NETWORK_SECURITY_FAILURES} -eq 0 ] && echo "compliant" || echo "non-compliant")",
            "failures": ${NETWORK_SECURITY_FAILURES}
        },
        "dependency_security": {
            "status": "$([ ${DEPENDENCY_SECURITY_FAILURES} -eq 0 ] && echo "compliant" || echo "non-compliant")",
            "failures": ${DEPENDENCY_SECURITY_FAILURES}
        }
    },
    "overall_status": "$([ ${TOTAL_FAILURES} -eq 0 ] && echo "compliant" || echo "non-compliant")",
    "total_failures": ${TOTAL_FAILURES}
}
EOF
    
    log "Compliance report generated: ${REPORT_FILE}"
    
    # Display summary
    echo ""
    log "Compliance Summary:"
    echo "-------------------"
    echo "Data Protection:     $([ ${DATA_PROTECTION_FAILURES} -eq 0 ] && success "Compliant" || failure "Non-compliant (${DATA_PROTECTION_FAILURES} issues)")"
    echo "Access Control:      $([ ${ACCESS_CONTROL_FAILURES} -eq 0 ] && success "Compliant" || failure "Non-compliant (${ACCESS_CONTROL_FAILURES} issues)")"
    echo "Audit Logging:       $([ ${AUDIT_LOGGING_FAILURES} -eq 0 ] && success "Compliant" || failure "Non-compliant (${AUDIT_LOGGING_FAILURES} issues)")"
    echo "Network Security:    $([ ${NETWORK_SECURITY_FAILURES} -eq 0 ] && success "Compliant" || failure "Non-compliant (${NETWORK_SECURITY_FAILURES} issues)")"
    echo "Dependency Security: $([ ${DEPENDENCY_SECURITY_FAILURES} -eq 0 ] && success "Compliant" || failure "Non-compliant (${DEPENDENCY_SECURITY_FAILURES} issues)")"
    echo "-------------------"
    echo "Overall Status:      $([ ${TOTAL_FAILURES} -eq 0 ] && success "Compliant" || failure "Non-compliant (${TOTAL_FAILURES} issues)")"
}

# Main function
main() {
    log "Starting compliance check for environment: ${ENV} (level: ${COMPLIANCE_LEVEL})"
    
    # Run compliance checks
    check_data_protection
    DATA_PROTECTION_FAILURES=$?
    
    check_access_control
    ACCESS_CONTROL_FAILURES=$?
    
    check_audit_logging
    AUDIT_LOGGING_FAILURES=$?
    
    check_network_security
    NETWORK_SECURITY_FAILURES=$?
    
    check_dependency_security
    DEPENDENCY_SECURITY_FAILURES=$?
    
    # Calculate total failures
    TOTAL_FAILURES=$((DATA_PROTECTION_FAILURES + ACCESS_CONTROL_FAILURES + AUDIT_LOGGING_FAILURES + NETWORK_SECURITY_FAILURES + DEPENDENCY_SECURITY_FAILURES))
    
    # Generate report
    generate_report
    
    # Exit with status
    if [ ${TOTAL_FAILURES} -eq 0 ]; then
        log "Compliance check passed"
        exit 0
    else
        error "Compliance check failed with ${TOTAL_FAILURES} issues"
        exit 1
    fi
}

# Execute main function
main