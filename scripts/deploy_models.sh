#!/bin/bash
# scripts/deploy_models.sh

set -e

# Configuration
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV=${1:-"prod"}
MODEL_TYPE=${2:-"all"}

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

# Validate model files
validate_models() {
    log "Validating model files..."
    
    # Define model types and required files
    declare -A MODEL_FILES
    MODEL_FILES["anomaly_detection"]="anomaly_detection.pkl anomaly_scaler.pkl"
    MODEL_FILES["log_classification"]="log_classifier.pkl classification_scaler.pkl label_encoder.pkl"
    MODEL_FILES["feature_importance"]="feature_importance.pkl"
    
    # Validate model files
    MODELS_DIR="${PROJECT_ROOT}/models"
    
    if [ "${MODEL_TYPE}" == "all" ]; then
        MODELS_TO_CHECK="${!MODEL_FILES[@]}"
    else
        MODELS_TO_CHECK="${MODEL_TYPE}"
    fi
    
    VALIDATION_PASSED=true
    
    for model in ${MODELS_TO_CHECK}; do
        log "Validating ${model} model files..."
        
        for file in ${MODEL_FILES[$model]}; do
            if [ ! -f "${MODELS_DIR}/${file}" ]; then
                error "Missing model file: ${file}"
                VALIDATION_PASSED=false
            else
                # Check file size
                FILE_SIZE=$(stat -c%s "${MODELS_DIR}/${file}")
                if [ "${FILE_SIZE}" -lt 1000 ]; then
                    warn "Model file ${file} is suspiciously small (${FILE_SIZE} bytes)"
                fi
                
                log "  ✓ ${file} (${FILE_SIZE} bytes)"
            fi
        done
    done
    
    if [ "${VALIDATION_PASSED}" = false ]; then
        error "Model validation failed. Aborting deployment."
        exit 1
    fi
    
    log "Model validation completed successfully."
}

# Create model package
create_model_package() {
    log "Creating model package..."
    
    # Create package directory
    PACKAGE_DIR="${PROJECT_ROOT}/models/package"
    mkdir -p "${PACKAGE_DIR}"
    
    # Copy model files
    if [ "${MODEL_TYPE}" == "all" ]; then
        cp "${PROJECT_ROOT}/models/"*.pkl "${PACKAGE_DIR}/"
    else
        for model in ${MODEL_TYPE}; do
            for file in ${MODEL_FILES[$model]}; do
                cp "${PROJECT_ROOT}/models/${file}" "${PACKAGE_DIR}/"
            done
        done
    fi
    
    # Create metadata file
    cat > "${PACKAGE_DIR}/metadata.json" << EOF
{
    "version": "$(date +%Y%m%d%H%M%S)",
    "environment": "${ENV}",
    "models": $([ "${MODEL_TYPE}" == "all" ] && echo "\"all\"" || echo "\"${MODEL_TYPE}\""),
    "created_at": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
    "created_by": "$(whoami)"
}
EOF
    
    # Create package archive
    PACKAGE_NAME="models_${ENV}_$(date +%Y%m%d%H%M%S).tar.gz"
    tar -czf "${PROJECT_ROOT}/models/${PACKAGE_NAME}" -C "${PACKAGE_DIR}" .
    
    log "Created model package: ${PACKAGE_NAME}"
    
    # Cleanup
    rm -rf "${PACKAGE_DIR}"
    
    echo "${PACKAGE_NAME}"
}

# Upload models to Azure Storage
upload_models() {
    log "Uploading models to Azure Storage..."
    
    PACKAGE_NAME=$1
    
    # Upload to Azure Storage
    az storage blob upload \
        --account-name "${STORAGE_ACCOUNT}" \
        --container-name "models" \
        --name "${ENV}/${PACKAGE_NAME}" \
        --file "${PROJECT_ROOT}/models/${PACKAGE_NAME}" \
        --auth-mode login
    
    log "Models uploaded to Azure Storage: ${STORAGE_ACCOUNT}/models/${ENV}/${PACKAGE_NAME}"
    
    # Get SAS URL for deployment
    SAS_URL=$(az storage blob generate-sas \
        --account-name "${STORAGE_ACCOUNT}" \
        --container-name "models" \
        --name "${ENV}/${PACKAGE_NAME}" \
        --permissions r \
        --expiry $(date -u -d "1 day" '+%Y-%m-%dT%H:%M:%SZ') \
        --auth-mode login \
        --full-uri \
        --output tsv)
    
    echo "${SAS_URL}"
}

# Deploy models to production
deploy_models() {
    log "Deploying models to production..."
    
    SAS_URL=$1
    
    # Update model reference in configuration
    az appconfig kv set \
        --name "${APP_CONFIG}" \
        --key "ml:modelPackage" \
        --value "${SAS_URL}" \
        --label "${ENV}" \
        --yes
    
    log "Updated model reference in App Configuration"
    
    # Trigger model reload
    if [ "${ENV}" == "prod" ]; then
        # For production, use the deployment slot
        az webapp deployment slot swap \
            --resource-group "${RESOURCE_GROUP}" \
            --name "${APP_NAME}" \
            --slot staging \
            --target-slot production
            
        log "Swapped deployment slots to activate new models"
    else
        # For non-production, restart the app
        az webapp restart \
            --resource-group "${RESOURCE_GROUP}" \
            --name "${APP_NAME}"
            
        log "Restarted application to load new models"
    fi
}

# Verify model deployment
verify_deployment() {
    log "Verifying model deployment..."
    
    # Wait for application to start
    sleep 30
    
    # Check model version endpoint
    MODEL_INFO=$(curl -s "https://${APP_NAME}.azurewebsites.net/api/model-info")
    
    echo "Model Information:"
    echo "${MODEL_INFO}" | jq .
    
    # Verify model version
    EXPECTED_VERSION=$(date +%Y%m%d)
    ACTUAL_VERSION=$(echo "${MODEL_INFO}" | jq -r '.version' | cut -c 1-8)
    
    if [ "${ACTUAL_VERSION}" == "${EXPECTED_VERSION}" ]; then
        log "Model deployment verified successfully."
    else
        warn "Model version mismatch. Expected: ${EXPECTED_VERSION}, Actual: ${ACTUAL_VERSION}"
    fi
}

# Main function
main() {
    log "Starting model deployment for environment: ${ENV}"
    
    # Validate models
    validate_models
    
    # Create model package
    PACKAGE_NAME=$(create_model_package)
    
    # Upload models
    SAS_URL=$(upload_models "${PACKAGE_NAME}")
    
    # Deploy models
    deploy_models "${SAS_URL}"
    
    # Verify deployment
    verify_deployment
    
    log "Model deployment completed"
}

# Execute main function
main