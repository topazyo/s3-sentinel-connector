# Deployment Guide

## Prerequisites

### 1. Azure Resources
- Azure Subscription
- Azure Key Vault
- Microsoft Sentinel workspace
- Azure Container Registry

### 2. AWS Resources
- S3 Bucket
- IAM credentials
- Event notifications

### 3. Development Environment
```bash
# Python 3.9+
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Deployment Steps

### 1. Infrastructure Setup

```bash
# Initialize Terraform
cd deployment/terraform
terraform init

# Apply infrastructure
terraform apply -var-file=environments/prod/terraform.tfvars
```

### 2. Application Deployment

```bash
# Build container
docker build -t s3-sentinel-connector .

# Push to ACR
az acr login --name <acr-name>
docker tag s3-sentinel-connector <acr-name>.azurecr.io/s3-sentinel-connector
docker push <acr-name>.azurecr.io/s3-sentinel-connector
```

### 3. Configuration

```yaml
# config/prod.yaml
azure:
  key_vault_url: "https://your-keyvault.vault.azure.net"
  tenant_id: "your-tenant-id"
  
aws:
  region: "us-east-1"
  bucket_name: "your-bucket"
  
sentinel:
  workspace_id: "your-workspace-id"
  dcr_endpoint: "your-dcr-endpoint"
```

### 4. Security Setup

```bash
# Initialize security components
./scripts/setup_security.sh prod

# Verify setup
./scripts/verify_security.sh prod
```

## Monitoring Setup

### 1. Azure Monitor

```bash
# Deploy monitoring resources
az deployment group create \
  --resource-group your-rg \
  --template-file deployment/monitoring/template.json
```

### 2. Alert Configuration

```yaml
# config/alerts.yaml
alerts:
  - name: high_latency
    threshold: 300
    window: 5m
    severity: high
```

## Validation

```bash
# Run validation tests
pytest tests/validation/

# Check security compliance
./scripts/check_compliance.sh

# Verify connectivity
./scripts/verify_connectivity.sh
```

## Troubleshooting

### Common Issues

1. **Connection Failures**
   ```bash
   # Check connectivity
   ./scripts/diagnose_connectivity.sh
   ```

2. **Performance Issues**
   ```bash
   # Run performance diagnostics
   ./scripts/diagnose_performance.sh
   ```

3. **Security Alerts**
   ```bash
   # Verify security configuration
   ./scripts/verify_security.sh
   ```