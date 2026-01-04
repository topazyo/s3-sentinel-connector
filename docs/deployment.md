# Deployment Guide (Consolidated)

This document is the canonical deployment guide for the S3 → Sentinel Connector. It consolidates deployment, post-deployment verification, monitoring, and troubleshooting steps. If you are following any solution-level guides (for example under `Solutions/S3SentinelConnector/`), prefer this document and use those solution files as supplements.

Prerequisites
-------------

1. Azure resources
  - Azure subscription with permissions to create resource groups and deploy ARM/Terraform templates
  - Azure Key Vault for storing secrets
  - Microsoft Sentinel (Log Analytics workspace)
  - (Optional) Azure Container Registry (ACR) for container images

2. AWS resources
  - S3 bucket containing the logs to ingest
  - IAM user/role with `s3:GetObject` and `s3:ListBucket` for the ingestion service

3. Local tooling
  - Python 3.9+ (project configured for `py39` in `pyproject.toml`)
  - Terraform (v1.4+ recommended)
  - Docker (for building images)
  - Azure CLI (`az`) and `kubectl` if deploying to AKS

Quick start (infrastructure + app)
--------------------------------
1. Initialize and apply Terraform (example for `dev` environment):

```bash
cd deployment/terraform
terraform init
terraform apply -var-file=environments/dev/terraform.tfvars
```

2. Build and push container (optional when using Function App packaging instead):

```bash
docker build -t s3-sentinel-connector:latest .
az acr login --name <acr-name>
docker tag s3-sentinel-connector:latest <acr-name>.azurecr.io/s3-sentinel-connector:latest
docker push <acr-name>.azurecr.io/s3-sentinel-connector:latest
```

3. Deploy application manifests (Kubernetes overlay example):

```bash
kubectl apply -k deployment/kubernetes/overlays/dev
kubectl rollout status deployment/s3-sentinel-connector
```

Configuration
-------------

Use `config/base.yaml` as the source of defaults and override with environment-specific YAML (e.g., `config/prod.yaml`) and environment variables. For development, copy the example `.env`:

```bash
cp .env.example .env
# or PowerShell: Copy-Item .env.example .env
```

Key configuration locations:
- `config/base.yaml` — default values
- `config/{dev,prod}.yaml` — environment overrides
- `config/tables.yaml` — mapping of parsers to Sentinel tables

Post-deployment verification
----------------------------
Follow the post-deployment checks to ensure the connector is operating correctly. The solution-level `Solutions/S3SentinelConnector/Post-Deployment.md` contains detailed checklists; this section summarizes key steps.

1. Retrieve deployment outputs (resource names, Key Vault URL, DCR endpoint, Function App URL if applicable).

```bash
az deployment group show --resource-group <rg> --name <deployment-name>
```

2. Verify Key Vault secrets were created and are accessible to the runtime identity.

3. Validate connectivity to S3 and that the ingestion service can list and read objects.

4. Verify logs are routed to Sentinel (check ingestion metrics in PipelineMonitor and Sentinel workspace).

Monitoring and alerts
---------------------

1. Deploy monitoring ARM templates / resources (if using the included templates):

```bash
az deployment group create --resource-group <rg> --template-file deployment/monitoring/template.json
```

2. Configure alert thresholds in `config/alerts.yaml` or via the monitoring dashboard.

Troubleshooting
---------------

Common troubleshooting commands are implemented under `deployment/scripts/` and `Solutions/S3SentinelConnector/Verification/`.

- To verify Kubernetes deployment status:

```bash
kubectl get pods -n <namespace>
kubectl logs deployment/s3-sentinel-connector -n <namespace>
```

- To run solution-level verification (PowerShell script included):

```powershell
.\Solutions\S3SentinelConnector\Verification\Test_Deployment.ps1 -ResourceGroupName "rg-sentinel-test" -ParametersFile "./parameters.json"
```

Files referenced
----------------
- `deployment/scripts/deploy.sh` — orchestrated deploy script that runs Terraform, applies kustomize overlays, and verifies rollout.
- `deployment/terraform/` — Terraform modules & environment tfvars
- `deployment/kubernetes/` — kustomize base + overlays for `dev`/`prod`
- `Solutions/S3SentinelConnector/Post-Deployment.md` — detailed post-deployment checklist and validation steps (useful for runbook steps)

Notes
-----
- Prefer this `docs/deployment.md` as the canonical guide. The files under `Solutions/S3SentinelConnector/` are solution-specific supplements and contain richer checklists and verification scripts tailored to function-app packaging.
- If you maintain both ARM and Terraform flows, clearly document which is preferred for each environment to avoid confusion.
