#!/bin/bash
# scripts/diagnose_connectivity.sh

set -e

# Configuration
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV=${1:-"prod"}
ENDPOINT=${2:-"all"}

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

# Diagnose AWS S3 connectivity
diagnose_s3_connectivity() {
    log "Diagnosing AWS S3 connectivity..."
    
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
    
    # Check DNS resolution
    log "Checking DNS resolution for S3 endpoint..."
    S3_ENDPOINT="s3.${AWS_REGION:-us-east-1}.amazonaws.com"
    
    S3_IP=$(dig +short "${S3_ENDPOINT}" | head -1)
    if [ -n "${S3_IP}" ]; then
        success "DNS resolution successful: ${S3_ENDPOINT} -> ${S3_IP}"
    else
        failure "DNS resolution failed for ${S3_ENDPOINT}"
    fi
    
    # Check network connectivity
    log "Checking network connectivity to S3 endpoint..."
    if timeout 5 bash -c "cat < /dev/null > /dev/tcp/${S3_ENDPOINT}/443" 2>/dev/null; then
        success "Network connectivity successful to ${S3_ENDPOINT}:443"
    else
        failure "Network connectivity failed to ${S3_ENDPOINT}:443"
    fi
    
    # Check TLS handshake
    log "Checking TLS handshake with S3 endpoint..."
    if openssl s_client -connect "${S3_ENDPOINT}:443" -servername "${S3_ENDPOINT}" </dev/null 2>/dev/null | grep -q "Verify return code: 0"; then
        success "TLS handshake successful with ${S3_ENDPOINT}"
    else
        failure "TLS handshake failed with ${S3_ENDPOINT}"
    fi
    
    # Check AWS credentials
    log "Checking AWS credentials..."
    if aws sts get-caller-identity &>/dev/null; then
        IDENTITY=$(aws sts get-caller-identity --output json)
        success "AWS credentials are valid"
        echo "Identity: $(echo ${IDENTITY} | jq -r '.Arn')"
    else
        failure "AWS credentials are invalid"
    fi
    
    # Check S3 bucket access
    log "Checking S3 bucket access..."
    if aws s3 ls "s3://${S3_BUCKET}" --max-items 1 &>/dev/null; then
        success "S3 bucket access successful: ${S3_BUCKET}"
        
        # Check bucket permissions
        log "Checking bucket permissions..."
        BUCKET_POLICY=$(aws s3api get-bucket-policy --bucket "${S3_BUCKET}" 2>/dev/null || echo "")
        
        if [ -n "${BUCKET_POLICY}" ]; then
            success "Bucket policy retrieved"
            echo "Bucket policy:"
            echo "${BUCKET_POLICY}" | jq .
        else
            warn "No bucket policy found or insufficient permissions"
        fi
        
        # Check object access
        log "Checking object access..."
        TEST_OBJECT=$(aws s3 ls "s3://${S3_BUCKET}" --max-items 1 | head -1 | awk '{print $4}')
        
        if [ -n "${TEST_OBJECT}" ]; then
            if aws s3api head-object --bucket "${S3_BUCKET}" --key "${TEST_OBJECT}" &>/dev/null; then
                success "Object access successful: ${TEST_OBJECT}"
            else
                failure "Object access failed: ${TEST_OBJECT}"
            fi
        else
            warn "No objects found in bucket"
        fi
    else
        failure "S3 bucket access failed: ${S3_BUCKET}"
        
        # Check if bucket exists
        if aws s3api head-bucket --bucket "${S3_BUCKET}" 2>/dev/null; then
            warn "Bucket exists but access is denied"
        else
            error "Bucket does not exist or is in a different region"
        fi
    fi
}

# Diagnose Azure Sentinel connectivity
diagnose_sentinel_connectivity() {
    log "Diagnosing Azure Sentinel connectivity..."
    
    if [ -z "${SENTINEL_WORKSPACE_ID}" ] || [ -z "${SENTINEL_KEY}" ]; then
        error "Sentinel credentials not provided"
        return 1
    fi
    
    # Check Azure login
    log "Checking Azure login status..."
    if az account show &>/dev/null; then
        ACCOUNT=$(az account show --output json)
        success "Azure login successful"
        echo "Account: $(echo ${ACCOUNT} | jq -r '.name')"
    else
        failure "Azure login failed"
        
        # Try to login
        log "Attempting to login to Azure..."
        if az login --output none; then
            success "Azure login successful"
        else
            error "Azure login failed. Please login manually with 'az login'"
            return 1
        fi
    fi
    
    # Check DNS resolution
    log "Checking DNS resolution for Log Analytics endpoint..."
    LA_ENDPOINT="api.loganalytics.io"
    
    LA_IP=$(dig +short "${LA_ENDPOINT}" | head -1)
    if [ -n "${LA_IP}" ]; then
        success "DNS resolution successful: ${LA_ENDPOINT} -> ${LA_IP}"
    else
        failure "DNS resolution failed for ${LA_ENDPOINT}"
    fi
    
    # Check network connectivity
    log "Checking network connectivity to Log Analytics endpoint..."
    if timeout 5 bash -c "cat < /dev/null > /dev/tcp/${LA_ENDPOINT}/443" 2>/dev/null; then
        success "Network connectivity successful to ${LA_ENDPOINT}:443"
    else
        failure "Network connectivity failed to ${LA_ENDPOINT}:443"
    fi
    
    # Check TLS handshake
    log "Checking TLS handshake with Log Analytics endpoint..."
    if openssl s_client -connect "${LA_ENDPOINT}:443" -servername "${LA_ENDPOINT}" </dev/null 2>/dev/null | grep -q "Verify return code: 0"; then
        success "TLS handshake successful with ${LA_ENDPOINT}"
    else
        failure "TLS handshake failed with ${LA_ENDPOINT}"
    fi
    
    # Check Log Analytics workspace
    log "Checking Log Analytics workspace..."
    if az monitor log-analytics workspace show --workspace-name "${SENTINEL_WORKSPACE_NAME}" --resource-group "${RESOURCE_GROUP}" &>/dev/null; then
        WORKSPACE=$(az monitor log-analytics workspace show --workspace-name "${SENTINEL_WORKSPACE_NAME}" --resource-group "${RESOURCE_GROUP}" --output json)
        success "Log Analytics workspace found: ${SENTINEL_WORKSPACE_NAME}"
        echo "Workspace ID: $(echo ${WORKSPACE} | jq -r '.customerId')"
        echo "Location: $(echo ${WORKSPACE} | jq -r '.location')"
    else
        failure "Log Analytics workspace not found: ${SENTINEL_WORKSPACE_NAME}"
    fi
    
    # Check query capability
    log "Testing query capability..."
    QUERY="
    SecurityEvent
    | summarize count() by EventID
    | order by count_ desc
    | limit 5
    "
    
    if az monitor log-analytics query --workspace "${SENTINEL_WORKSPACE_ID}" --analytics-query "${QUERY}" --output json &>/dev/null; then
        success "Query capability verified"
    else
        failure "Query capability failed"
    fi
    
    # Check DCR endpoint
    if [ -n "${DCR_ENDPOINT}" ]; then
        log "Checking DCR endpoint..."
        
        # Check DNS resolution
        DCR_HOST=$(echo "${DCR_ENDPOINT}" | sed -e 's|^[^/]*//||' -e 's|/.*$||')
        
        DCR_IP=$(dig +short "${DCR_HOST}" | head -1)
        if [ -n "${DCR_IP}" ]; then
            success "DNS resolution successful: ${DCR_HOST} -> ${DCR_IP}"
        else
            failure "DNS resolution failed for ${DCR_HOST}"
        fi
        
        # Check network connectivity
        if timeout 5 bash -c "cat < /dev/null > /dev/tcp/${DCR_HOST}/443" 2>/dev/null; then
            success "Network connectivity successful to ${DCR_HOST}:443"
        else
            failure "Network connectivity failed to ${DCR_HOST}:443"
        fi
        
        # Check TLS handshake
        if openssl s_client -connect "${DCR_HOST}:443" -servername "${DCR_HOST}" </dev/null 2>/dev/null | grep -q "Verify return code: 0"; then
            success "TLS handshake successful with ${DCR_HOST}"
        else
            failure "TLS handshake failed with ${DCR_HOST}"
        fi
    fi
}

# Diagnose network connectivity
diagnose_network_connectivity() {
    log "Diagnosing network connectivity..."
    
    # Define endpoints to check
    declare -A ENDPOINTS
    ENDPOINTS["AWS S3"]="s3.${AWS_REGION:-us-east-1}.amazonaws.com:443"
    ENDPOINTS["Azure Log Analytics"]="api.loganalytics.io:443"
    ENDPOINTS["Azure Key Vault"]="${KEY_VAULT_NAME}.vault.azure.net:443"
    
    # Filter endpoints if specific one requested
    if [ "${ENDPOINT}" != "all" ]; then
        if [ -n "${ENDPOINTS[$ENDPOINT]}" ]; then
            TEMP_ENDPOINTS=("${ENDPOINT}:${ENDPOINTS[$ENDPOINT]}")
            declare -A ENDPOINTS=()
            ENDPOINTS["$ENDPOINT"]="${TEMP_ENDPOINTS[0]#*:}"
        else
            error "Unknown endpoint: ${ENDPOINT}"
            echo "Available endpoints: ${!ENDPOINTS[*]}"
            return 1
        fi
    fi
    
    for name in "${!ENDPOINTS[@]}"; do
        endpoint="${ENDPOINTS[$name]}"
        host=$(echo "${endpoint}" | cut -d: -f1)
        port=$(echo "${endpoint}" | cut -d: -f2)
        
        log "Diagnosing connectivity to ${name} (${endpoint})..."
        
        # Check DNS resolution
        log "Checking DNS resolution..."
        IP_ADDRESSES=$(dig +short "${host}")
        
        if [ -n "${IP_ADDRESSES}" ]; then
            success "DNS resolution successful for ${host}"
            echo "IP addresses:"
            echo "${IP_ADDRESSES}"
        else
            failure "DNS resolution failed for ${host}"
            
            # Try alternative DNS servers
            log "Trying alternative DNS servers..."
            GOOGLE_DNS=$(dig @8.8.8.8 +short "${host}")
            
            if [ -n "${GOOGLE_DNS}" ]; then
                success "DNS resolution successful using Google DNS (8.8.8.8)"
                echo "IP addresses:"
                echo "${GOOGLE_DNS}"
                warn "Local DNS resolution is failing but external DNS works"
            else
                error "DNS resolution failed using Google DNS"
            fi
        fi
        
        # Check route to host
        log "Checking route to host..."
        if which traceroute &>/dev/null; then
            FIRST_IP=$(echo "${IP_ADDRESSES}" | head -1)
            if [ -n "${FIRST_IP}" ]; then
                echo "Route to ${host} (${FIRST_IP}):"
                traceroute -m 10 -w 2 "${FIRST_IP}" 2>/dev/null || true
            else
                warn "Cannot trace route due to DNS resolution failure"
            fi
        else
            warn "traceroute not available, skipping route check"
        fi
        
        # Check TCP connectivity
        log "Checking TCP connectivity..."
        if timeout 5 bash -c "cat < /dev/null > /dev/tcp/${host}/${port}" 2>/dev/null; then
            success "TCP connectivity successful to ${host}:${port}"
        else
            failure "TCP connectivity failed to ${host}:${port}"
            
            # Check if firewall is blocking
            log "Checking for firewall blocks..."
            if which telnet &>/dev/null; then
                TELNET_OUTPUT=$(timeout 5 telnet "${host}" "${port}" 2>&1 || true)
                echo "Telnet output:"
                echo "${TELNET_OUTPUT}"
            fi
        fi
        
        # Check TLS handshake
        log "Checking TLS handshake..."
        if openssl s_client -connect "${host}:${port}" -servername "${host}" </dev/null 2>/dev/null | grep -q "Verify return code: 0"; then
            success "TLS handshake successful with ${host}"
            
            # Check certificate details
            log "Certificate details:"
            openssl s_client -connect "${host}:${port}" -servername "${host}" </dev/null 2>/dev/null | openssl x509 -noout -text | grep -E "Subject:|Issuer:|Not Before:|Not After :|DNS:" || true
        else
            failure "TLS handshake failed with ${host}"
            
            # Get more details on TLS failure
            log "TLS handshake details:"
            openssl s_client -connect "${host}:${port}" -servername "${host}" </dev/null 2>&1 | grep -E "error|failure|unable|verify" || true
        fi
        
        # Check HTTP connectivity
        log "Checking HTTP connectivity..."
        if curl -s -o /dev/null -w "%{http_code}" "https://${host}" &>/dev/null; then
            HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "https://${host}")
            success "HTTP connectivity successful to ${host} (Status: ${HTTP_CODE})"
        else
            failure "HTTP connectivity failed to ${host}"
            
            # Get more details on HTTP failure
            log "HTTP request details:"
            curl -v "https://${host}" 2>&1 | grep -E "Failed|error|refused|timeout" || true
        fi
        
        echo "-----------------------------------"
    done
}

# Main function
main() {
    log "Starting connectivity diagnostics for environment: ${ENV}"
    
    # Check required tools
    REQUIRED_TOOLS=("dig" "curl" "openssl" "jq")
    MISSING_TOOLS=()
    
    for tool in "${REQUIRED_TOOLS[@]}"; do
        if ! command -v "${tool}" &>/dev/null; then
            MISSING_TOOLS+=("${tool}")
        fi
    done
    
    if [ ${#MISSING_TOOLS[@]} -gt 0 ]; then
        error "Missing required tools: ${MISSING_TOOLS[*]}"
        exit 1
    fi
    
    # Run diagnostics based on endpoint
    case "${ENDPOINT}" in
        "s3")
            diagnose_s3_connectivity
            ;;
        "sentinel")
            diagnose_sentinel_connectivity
            ;;
        "all")
            diagnose_s3_connectivity
            diagnose_sentinel_connectivity
            diagnose_network_connectivity
            ;;
        *)
            diagnose_network_connectivity
            ;;
    esac
    
    log "Connectivity diagnostics completed"
}

# Execute main function
main