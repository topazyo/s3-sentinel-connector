#!/bin/bash
# scripts/verify_connectivity.sh

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

# Check AWS S3 connectivity
check_s3_connectivity() {
    log "Checking AWS S3 connectivity..."
    
    if [ -z "${AWS_ACCESS_KEY}" ] || [ -z "${AWS_SECRET_KEY}" ]; then
        error "AWS credentials not provided"
        return 1
    fi
    
    if [ -z "${S3_BUCKET}" ]; then
        error "S3 bucket name not provided"
        return 1
    fi
    
    # Set AWS credentials
    export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY}"
    export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_KEY}"
    export AWS_DEFAULT_REGION="${AWS_REGION:-us-east-1}"
    
    # Check S3 bucket access
    if aws s3 ls "s3://${S3_BUCKET}" --max-items 1 &>/dev/null; then
        success "Successfully connected to S3 bucket: ${S3_BUCKET}"
        
        # Check object listing
        OBJECTS=$(aws s3 ls "s3://${S3_BUCKET}" --max-items 5 2>/dev/null)
        if [ -n "${OBJECTS}" ]; then
            success "Successfully listed objects in S3 bucket"
            echo "Sample objects:"
            echo "${OBJECTS}"
        else
            warn "Bucket is empty or no permission to list objects"
        fi
        
        return 0
    else
        failure "Failed to connect to S3 bucket: ${S3_BUCKET}"
        return 1
    fi
}

# Check Azure Sentinel connectivity
check_sentinel_connectivity() {
    log "Checking Azure Sentinel connectivity..."
    
    if [ -z "${SENTINEL_WORKSPACE_ID}" ] || [ -z "${SENTINEL_KEY}" ]; then
        error "Sentinel credentials not provided"
        return 1
    fi
    
    # Check Log Analytics workspace
    if az monitor log-analytics workspace show --workspace-name "${SENTINEL_WORKSPACE_NAME}" --resource-group "${RESOURCE_GROUP}" &>/dev/null; then
        success "Successfully connected to Log Analytics workspace: ${SENTINEL_WORKSPACE_NAME}"
        
        # Check query capability
        QUERY="
        SecurityEvent
        | summarize count() by EventID
        | order by count_ desc
        | limit 5
        "
        
        QUERY_RESULT=$(az monitor log-analytics query \
            --workspace "${SENTINEL_WORKSPACE_ID}" \
            --analytics-query "${QUERY}" \
            --output json 2>/dev/null)
        
        if [ -n "${QUERY_RESULT}" ] && [ "${QUERY_RESULT}" != "[]" ]; then
            success "Successfully queried Log Analytics workspace"
            echo "Sample query results:"
            echo "${QUERY_RESULT}" | jq .
        else
            warn "No data returned from query or insufficient permissions"
        fi
        
        return 0
    else
        failure "Failed to connect to Log Analytics workspace: ${SENTINEL_WORKSPACE_NAME}"
        return 1
    fi
}

# Check network connectivity
check_network_connectivity() {
    log "Checking network connectivity..."
    
    # Define endpoints to check
    declare -A ENDPOINTS
    ENDPOINTS["AWS S3"]="s3.${AWS_REGION:-us-east-1}.amazonaws.com:443"
    ENDPOINTS["Azure Log Analytics"]="api.loganalytics.io:443"
    ENDPOINTS["Azure Key Vault"]="${KEY_VAULT_NAME}.vault.azure.net:443"
    
    FAILURES=0
    
    for name in "${!ENDPOINTS[@]}"; do
        endpoint="${ENDPOINTS[$name]}"
        host=$(echo "${endpoint}" | cut -d: -f1)
        port=$(echo "${endpoint}" | cut -d: -f2)
        
        log "Checking connectivity to ${name} (${endpoint})..."
        
        # Check TCP connectivity
        if timeout 5 bash -c "cat < /dev/null > /dev/tcp/${host}/${port}" 2>/dev/null; then
            success "Successfully connected to ${name} (${endpoint})"
        else
            failure "Failed to connect to ${name} (${endpoint})"
            FAILURES=$((FAILURES+1))
        fi
        
        # Check HTTPS connectivity
        if curl -s -o /dev/null -w "%{http_code}" "https://${host}" &>/dev/null; then
            success "HTTPS connectivity to ${name} verified"
        else
            warn "HTTPS connectivity to ${name} could not be verified"
        fi
    done
    
    return ${FAILURES}
}

# Check application connectivity
check_app_connectivity() {
    log "Checking application connectivity..."
    
    if [ -z "${APP_URL}" ]; then
        warn "APP_URL not provided, skipping application connectivity check"
        return 0
    fi
    
    # Check application health endpoint
    HEALTH_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${APP_URL}/health" 2>/dev/null)
    
    if [ "${HEALTH_STATUS}" == "200" ]; then
        success "Application health check passed"
        
        # Get detailed health status
        HEALTH_DETAILS=$(curl -s "${APP_URL}/health" 2>/dev/null)
        echo "Health details:"
        echo "${HEALTH_DETAILS}" | jq .
        
        return 0
    else
        failure "Application health check failed with status: ${HEALTH_STATUS}"
        return 1
    fi
}

# Main function
main() {
    log "Starting connectivity verification for environment: ${ENV}"
    
    FAILURES=0
    
    # Check AWS S3 connectivity
    if ! check_s3_connectivity; then
        FAILURES=$((FAILURES+1))
    fi
    
    # Check Azure Sentinel connectivity
    if ! check_sentinel_connectivity; then
        FAILURES=$((FAILURES+1))
    fi
    
    # Check network connectivity
    if ! check_network_connectivity; then
        FAILURES=$((FAILURES+1))
    fi
    
    # Check application connectivity
    if ! check_app_connectivity; then
        FAILURES=$((FAILURES+1))
    fi
    
    # Summary
    echo ""
    log "Connectivity verification summary:"
    
    if [ ${FAILURES} -eq 0 ]; then
        success "All connectivity checks passed"
        exit 0
    else
        failure "${FAILURES} connectivity checks failed"
        exit 1
    fi
}

# Execute main function
main