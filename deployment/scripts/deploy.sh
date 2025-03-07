#!/bin/bash
# deployment/scripts/deploy.sh

set -e

# Configuration
ENVIRONMENT=$1
IMAGE_TAG=$2
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

# Load environment-specific variables
source "${SCRIPT_DIR}/env/${ENVIRONMENT}.env"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Function to log messages
log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%dT%H:%M:%S%z')] $1${NC}"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%dT%H:%M:%S%z')] ERROR: $1${NC}" >&2
}

warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%dT%H:%M:%S%z')] WARNING: $1${NC}"
}

# Validate inputs
if [ -z "$ENVIRONMENT" ] || [ -z "$IMAGE_TAG" ]; then
    error "Usage: $0 <environment> <image-tag>"
    exit 1
fi

# Check if required tools are installed
check_requirements() {
    local required_tools=("kubectl" "terraform" "az" "docker")
    
    for tool in "${required_tools[@]}"; do
        if ! command -v "$tool" &> /dev/null; then
            error "$tool is required but not installed."
            exit 1
        fi
    done
}

# Initialize Azure connection
initialize_azure() {
    log "Logging into Azure..."
    az login --service-principal \
        --username "$AZURE_CLIENT_ID" \
        --password "$AZURE_CLIENT_SECRET" \
        --tenant "$AZURE_TENANT_ID"
        
    az account set --subscription "$AZURE_SUBSCRIPTION_ID"
}

# Apply Terraform infrastructure
apply_infrastructure() {
    log "Applying Terraform infrastructure..."
    
    cd "${PROJECT_ROOT}/deployment/terraform"
    
    # Initialize Terraform
    terraform init \
        -backend-config="storage_account_name=tfstate${ENVIRONMENT}" \
        -backend-config="container_name=tfstate" \
        -backend-config="key=s3-sentinel-connector.tfstate"
    
    # Apply Terraform configuration
    terraform apply \
        -var-file="environments/${ENVIRONMENT}/terraform.tfvars" \
        -auto-approve
}

# Build and push Docker image
build_and_push_image() {
    log "Building and pushing Docker image..."
    
    # Build image
    docker build -t "$ACR_NAME.azurecr.io/s3-sentinel-connector:${IMAGE_TAG}" \
        -f "${PROJECT_ROOT}/Dockerfile" \
        "${PROJECT_ROOT}"
    
    # Login to ACR
    az acr login --name "$ACR_NAME"
    
    # Push image
    docker push "$ACR_NAME.azurecr.io/s3-sentinel-connector:${IMAGE_TAG}"
}

# Deploy to Kubernetes
deploy_to_kubernetes() {
    log "Deploying to Kubernetes..."
    
    # Get AKS credentials
    az aks get-credentials \
        --resource-group "s3-sentinel-connector-${ENVIRONMENT}-rg" \
        --name "s3-sentinel-${ENVIRONMENT}-aks"
    
    # Apply Kubernetes configurations
    kubectl apply -k "${PROJECT_ROOT}/deployment/kubernetes/overlays/${ENVIRONMENT}"
    
    # Update deployment image
    kubectl set image deployment/s3-sentinel-connector \
        connector="$ACR_NAME.azurecr.io/s3-sentinel-connector:${IMAGE_TAG}"
    
    # Wait for rollout
    kubectl rollout status deployment/s3-sentinel-connector
}

# Verify deployment
verify_deployment() {
    log "Verifying deployment..."
    
    # Check pod status
    local ready_pods=$(kubectl get pods -l app=s3-sentinel-connector \
        -o jsonpath='{.items[*].status.containerStatuses[*].ready}' | tr ' ' '\n' | grep -c "true")
    
    local total_pods=$(kubectl get pods -l app=s3-sentinel-connector \
        -o jsonpath='{.items[*].status.containerStatuses[*].ready}' | tr ' ' '\n' | wc -l)
    
    if [ "$ready_pods" -eq "$total_pods" ]; then
        log "Deployment successful: ${ready_pods}/${total_pods} pods ready"
    else
        error "Deployment verification failed: ${ready_pods}/${total_pods} pods ready"
        exit 1
    fi
}

# Main deployment flow
main() {
    log "Starting deployment for environment: ${ENVIRONMENT}"
    
    # Check requirements
    check_requirements
    
    # Initialize Azure connection
    initialize_azure
    
    # Apply infrastructure
    apply_infrastructure
    
    # Build and push image
    build_and_push_image
    
    # Deploy to Kubernetes
    deploy_to_kubernetes
    
    # Verify deployment
    verify_deployment
    
    log "Deployment completed successfully!"
}

# Execute main function
main