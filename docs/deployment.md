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
pip install -r requirements/requirements.txt

# For development, testing, and compliance checks
pip install -r requirements/requirements-dev.txt
pip install -r requirements/requirements-test.txt
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

Alert conditions are defined in `config/alerts.yaml`. This file is used by the `AlertManager` (see `src/monitoring/alerts.py`) to determine when to trigger alerts based on incoming metrics. Below is an example structure of `config/alerts.yaml`:

```yaml
# config/alerts.yaml
# Defines the alert rules for the AlertManager.

alerts:
  - name: "high_cpu_usage"
    metric: "cpu.usage_percent"  # Example metric name that your application reports
    threshold: 85.0
    operator: ">"  # Supported: >, <, >=, <=, ==, != (Note: current AlertManager placeholder supports > and <)
    window_seconds: 300 # Time window for evaluation (Note: current AlertManager placeholder is stateless and evaluates immediately)
    severity: "critical" # E.g., critical, warning, info
    description: "CPU usage is critically high on a component."
    # notification_channels: ["email", "slack"] # Optional: specify channels if implemented in AlertManager

  - name: "low_disk_space"
    metric: "disk.free_gb" # Example metric name
    threshold: 10.0
    operator: "<"
    window_seconds: 60 # How long the condition must persist (Note: current AlertManager is stateless)
    severity: "warning"
    description: "Disk space is running low on a component."
    # notification_channels: ["slack"]

  # Add more alert rules as needed following the structure above.
  # Ensure the 'metric' names correspond to metrics reported by your application.
```
For details on how alerts are processed, refer to the `AlertManager` class in the source code.

## Validation

```bash
# Run validation tests
pytest tests/validation/

# Check security compliance
./scripts/check_compliance.sh
# (Ensure development dependencies like `safety` are installed via `requirements/requirements-dev.txt` to run this script.)

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