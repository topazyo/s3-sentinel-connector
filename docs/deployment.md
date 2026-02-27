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

Local Terraform formatting (recommended)
----------------------------------------
Use the workspace task that routes through the resilient wrapper script:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File deployment/scripts/terraform_fmt_recursive.ps1
```

For CI-like non-mutating verification, use check mode:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File deployment/scripts/terraform_fmt_recursive.ps1 -Check
```

This wrapper resolves Terraform in the following order:
- explicit `-TerraformExe` path
- `terraform` on `PATH`
- Windows WinGet package discovery under `%LOCALAPPDATA%\Microsoft\WinGet\Packages\Hashicorp.Terraform*`
- `where.exe terraform` fallback

Example with an explicit executable path:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File deployment/scripts/terraform_fmt_recursive.ps1 -TerraformExe "C:\path\to\terraform.exe"
```

Configuration
-------------

Use `config/base.yaml` as the source of defaults and override with environment-specific YAML (e.g., `config/prod.yaml`) and environment variables. For development, copy the example `.env`:

```bash
cp .env.example .env
# or PowerShell: Copy-Item .env.example .env
```

For deployment script variables, create local env files from tracked templates:

```bash
cp deployment/scripts/env/prod.env.example deployment/scripts/env/prod.env
```

Concrete env files under `deployment/scripts/env/*.env` are ignored by git.

Key configuration locations:
- `config/base.yaml` — default values
- `config/{dev,prod}.yaml` — environment overrides
- `config/tables.yaml` — mapping of parsers to Sentinel tables

Production configuration overrides
--------------------------------

`config/prod.yaml` intentionally contains placeholder values and must be overridden for real deployments.

Required production overrides:
- `aws.bucket_name`
- `aws.access_key_id` (or `keyvault:...` reference)
- `aws.secret_access_key` (or `keyvault:...` reference)
- `sentinel.workspace_id`
- `sentinel.dcr_endpoint`
- `sentinel.rule_id`
- `sentinel.stream_name`
- `monitoring.metrics_endpoint`
- `monitoring.alert_webhook`
- `database.host`
- `database.username`
- `database.password` (or `keyvault:...` reference)

Recommended override mechanism:
- Environment variables with `APP_` prefix (for example `APP_SENTINEL_WORKSPACE_ID`).
- Key Vault references (`keyvault:<secret-name>`) for sensitive fields.

Runtime commands
----------------

The container and CLI now support operational runtime commands:

```bash
# Validate config
s3-sentinel validate-config --config-dir config --environment dev

# Run one ingestion cycle and exit
s3-sentinel ingest --config-dir config --environment dev --log-type firewall

# Run long-lived service with health/metrics endpoints
s3-sentinel run --config-dir config --environment prod --log-type firewall --poll-interval 30

# Replay failed batch payloads and archive successful replays
s3-sentinel replay-failed --config-dir config --environment prod --failed-batches-dir failed_batches
```

Health and metrics endpoints:
- `GET /health` on port `8080`
- `GET /ready` on port `8080`
- `GET /metrics` on ports `8080` and `9090`

CI/CD secrets
-------------

Required GitHub Actions repository secrets:

1. `AZURE_CREDENTIALS`
  - JSON service principal credentials used by `azure/login@v2`
  - Create with:

```bash
az ad sp create-for-rbac \
  --name s3-sentinel-gha \
  --role Contributor \
  --scopes /subscriptions/<subscription-id> \
  --sdk-auth
```

2. `ACR_NAME`
  - Plain ACR resource name (without `.azurecr.io`), for example `myregistry`.

Optional:
- `SNYK_TOKEN` if you enable Snyk scanning in active workflows.

Terraform state backend bootstrap
--------------------------------

Environment backend files are defined at:
- `deployment/terraform/environments/dev/backend.tf`
- `deployment/terraform/environments/prod/backend.tf`

Before first `terraform init`, create a storage account and state container in each environment:

```bash
az group create --name tfstate-<env>-rg --location <region>
az storage account create --name <tfstateaccount> --resource-group tfstate-<env>-rg --sku Standard_LRS
az storage container create --name tfstate --account-name <tfstateaccount>
```

Then run:

```bash
terraform -chdir=deployment/terraform/environments/<env> init
terraform -chdir=deployment/terraform/environments/<env> validate
```

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

- To run deployment smoke tests after rollout:

```bash
./deployment/scripts/smoke_tests.sh dev
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
