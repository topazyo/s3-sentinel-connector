# Post-Deployment Guide: S3 to Sentinel Data Connector

NOTE: This solution-level post-deployment guide supplements the canonical deployment guide at `docs/deployment.md`. For end-to-end deployment steps prefer `docs/deployment.md` and use this document for detailed verification checklists and solution-specific scripts.

This guide provides step-by-step instructions for completing the deployment and validating the S3 to Sentinel Data Connector.

## Prerequisites Checklist

Before proceeding, verify:

- [ ] ARM template deployment completed successfully
- [ ] You have the deployment outputs (Function App URL, Key Vault URI, DCR endpoint)
- [ ] You have AWS credentials with S3 read permissions ready
- [ ] Log files exist in your S3 bucket at the configured prefix

---

## Step 1: Retrieve Deployment Outputs

After ARM template deployment, collect these values from the Azure Portal:

1. Navigate to **Resource Groups** > Select your resource group
2. Click **Deployments** > Select the deployment
3. Click **Outputs** and note:
   - `functionAppUrl`
   - `functionAppPrincipalId`
   - `keyVaultUri`
   - `dcrEndpoint`
   - `dcrImmutableId`
   - `customTableName`

Or via Azure CLI:
```bash
az deployment group show \
  --resource-group <RESOURCE_GROUP> \
  --name <DEPLOYMENT_NAME> \
  --query properties.outputs
```

---

## Step 2: Verify Key Vault Secrets

The deployment automatically created these secrets in Key Vault. Verify they exist:

1. Open **Azure Portal** > **Key Vaults** > **[Your Key Vault Name]**
2. Navigate to **Secrets**
3. Confirm these secrets exist:
   - `aws-access-key-id` - AWS Access Key ID
   - `aws-secret-access-key` - AWS Secret Access Key

### Updating Credentials (if needed)

If you need to update the AWS credentials:

```bash
# Update Access Key ID
az keyvault secret set \
  --vault-name <KEY_VAULT_NAME> \
  --name aws-access-key-id \
  --value "<NEW_AWS_ACCESS_KEY_ID>"

# Update Secret Access Key
az keyvault secret set \
  --vault-name <KEY_VAULT_NAME> \
  --name aws-secret-access-key \
  --value "<NEW_AWS_SECRET_ACCESS_KEY>"
```

---

## Step 3: Deploy Function App Code

The ARM template creates the Function App infrastructure. You must deploy the actual function code:

### Option A: Deploy via Azure Functions Core Tools

```bash
# Navigate to the function app directory
cd Solutions/S3SentinelConnector/Data\ Connectors/S3SentinelConnector_FunctionApp

# Install dependencies
pip install -r requirements.txt

# Deploy to Azure
func azure functionapp publish <FUNCTION_APP_NAME>
```

### Option B: Deploy via VS Code

1. Install the **Azure Functions** extension
2. Open the function app folder
3. Click **Azure** icon in sidebar
4. Right-click on your Function App > **Deploy to Function App**
5. Select the function app name from the deployment

### Option C: Deploy via GitHub Actions

Create `.github/workflows/deploy-function.yml`:

```yaml
name: Deploy S3 Sentinel Connector

on:
  push:
    branches: [main]
    paths:
      - 'Solutions/S3SentinelConnector/Data Connectors/**'

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          cd "Solutions/S3SentinelConnector/Data Connectors/S3SentinelConnector_FunctionApp"
          pip install -r requirements.txt
      
      - name: Deploy to Azure Functions
        uses: Azure/functions-action@v1
        with:
          app-name: ${{ secrets.FUNCTION_APP_NAME }}
          package: 'Solutions/S3SentinelConnector/Data Connectors/S3SentinelConnector_FunctionApp'
          publish-profile: ${{ secrets.AZURE_FUNCTIONAPP_PUBLISH_PROFILE }}
```

---

## Step 4: Verify Function App Configuration

1. Open **Azure Portal** > **Function Apps** > **[Your Function App]**
2. Navigate to **Configuration** > **Application settings**
3. Verify these settings are correctly populated:

| Setting | Expected Value |
|---------|----------------|
| `KEY_VAULT_URL` | `https://<kv-name>.vault.azure.net` |
| `AWS_REGION` | Your AWS region (e.g., `us-west-2`) |
| `S3_BUCKET_NAME` | Your S3 bucket name |
| `S3_PREFIX` | Your log prefix (e.g., `logs/`) |
| `POLLING_INTERVAL_MINUTES` | `5` (or your configured value) |
| `BATCH_SIZE` | `1000` (or your configured value) |
| `LOG_TYPE` | `firewall` or `vpn` |
| `DCR_ENDPOINT` | DCE logs ingestion endpoint |
| `DCR_RULE_ID` | DCR immutable ID |
| `DCR_STREAM_NAME` | `Custom-Custom_Firewall_CL` or `Custom-Custom_VPN_CL` |

---

## Step 5: Trigger Initial Sync

The function runs on a timer. To trigger it manually:

### Via Azure Portal

1. Navigate to **Function Apps** > **[Your Function App]** > **Functions**
2. Click on `S3SentinelConnector_FunctionApp`
3. Click **Code + Test**
4. Click **Test/Run**
5. In the body, enter: `{}`
6. Click **Run**

### Via Azure CLI

```bash
# Get the function key
FUNC_KEY=$(az functionapp keys list \
  --resource-group <RESOURCE_GROUP> \
  --name <FUNCTION_APP_NAME> \
  --query functionKeys.default -o tsv)

# Trigger the function
curl -X POST \
  "https://<FUNCTION_APP_NAME>.azurewebsites.net/admin/functions/S3SentinelConnector_FunctionApp" \
  -H "x-functions-key: $FUNC_KEY" \
  -H "Content-Type: application/json" \
  -d '{}'
```

---

## Step 6: Verify Data Ingestion

### Check Function Logs

1. Open **Azure Portal** > **Function Apps** > **[Your Function App]**
2. Navigate to **Monitor** > **Logs**
3. Run this query:

```kql
FunctionAppLogs
| where TimeGenerated > ago(1h)
| where FunctionName == "S3SentinelConnector_FunctionApp"
| project TimeGenerated, Level, Message
| order by TimeGenerated desc
```

### Check Sentinel Data

1. Open **Azure Portal** > **Microsoft Sentinel** > **[Your Workspace]**
2. Navigate to **Logs**
3. Run:

```kql
// For Firewall logs
Custom_Firewall_CL
| where TimeGenerated > ago(24h)
| summarize count() by bin(TimeGenerated, 1h)
| render timechart

// For VPN logs  
Custom_VPN_CL
| where TimeGenerated > ago(24h)
| summarize count() by bin(TimeGenerated, 1h)
| render timechart
```

### Verify Record Schema

```kql
Custom_Firewall_CL
| take 10
| project TimeGenerated, SourceIP, DestinationIP, Action, Protocol, BytesTransferred
```

---

## Step 7: Configure Alerts (Optional)

Create an alert rule for connector health monitoring:

1. Navigate to **Azure Monitor** > **Alerts** > **Create alert rule**
2. Select the Function App as the resource
3. Configure condition:
   - Signal: `FunctionExecutionCount`
   - Alert logic: Count < 1 in the last 30 minutes
4. Configure action group for notifications

---

## Credential Rotation Procedure

**Frequency**: Rotate AWS credentials every 90 days

### Step-by-Step Rotation

1. **Generate New AWS Credentials**
   - Log in to AWS Console
   - Navigate to **IAM** > **Users** > **[Your IAM User]**
   - Click **Security credentials** > **Create access key**
   - Save the new Access Key ID and Secret Access Key

2. **Update Key Vault Secrets**
   ```bash
   # Update Access Key ID
   az keyvault secret set \
     --vault-name <KEY_VAULT_NAME> \
     --name aws-access-key-id \
     --value "<NEW_ACCESS_KEY_ID>"
   
   # Update Secret Access Key
   az keyvault secret set \
     --vault-name <KEY_VAULT_NAME> \
     --name aws-secret-access-key \
     --value "<NEW_SECRET_ACCESS_KEY>"
   ```

3. **Restart Function App**
   ```bash
   az functionapp restart \
     --resource-group <RESOURCE_GROUP> \
     --name <FUNCTION_APP_NAME>
   ```

4. **Verify Connectivity**
   - Trigger a manual function run
   - Check logs for successful S3 operations
   - Verify data continues to flow into Sentinel

5. **Deactivate Old Credentials**
   - Return to AWS IAM
   - Delete the old access key

---

## Troubleshooting Guide

### Issue: Function Not Triggering

| Symptom | Cause | Solution |
|---------|-------|----------|
| No function executions | Timer disabled | Check Function App > Functions > Enable |
| Function paused | Plan scaling | Check App Service Plan status |
| Missing trigger | Deployment issue | Redeploy function code |

### Issue: Authentication Errors

| Symptom | Cause | Solution |
|---------|-------|----------|
| "Access Denied" from S3 | Invalid AWS credentials | Verify Key Vault secrets |
| "Unauthorized" from Azure | Managed identity issue | Check Function App identity and DCR RBAC |
| Key Vault access denied | Missing access policy | Verify Function identity has Secret Get permission |

### Issue: No Data in Sentinel

| Symptom | Cause | Solution |
|---------|-------|----------|
| Table empty | No matching files | Check S3 prefix and file extensions |
| Partial data | Schema validation | Check logs for validation errors |
| Ingestion errors | DCR misconfiguration | Verify stream name and schema match |

### Diagnostic Commands

```bash
# Check Function App status
az functionapp show \
  --resource-group <RESOURCE_GROUP> \
  --name <FUNCTION_APP_NAME> \
  --query "state"

# View recent logs
az monitor log-analytics query \
  --workspace <WORKSPACE_NAME> \
  --analytics-query "FunctionAppLogs | where TimeGenerated > ago(1h) | where Level == 'Error'"

# Test S3 connectivity (from local machine with AWS CLI)
aws s3 ls s3://<BUCKET_NAME>/<PREFIX> --region <REGION>

# View Key Vault secrets (names only)
az keyvault secret list --vault-name <KEY_VAULT_NAME> --query "[].name"
```

---

## Performance Tuning

### Recommended Settings by Volume

| Daily Log Volume | Polling Interval | Batch Size | Function Plan |
|------------------|------------------|------------|---------------|
| < 100 MB | 15 minutes | 500 | Consumption |
| 100 MB - 1 GB | 5 minutes | 1000 | Consumption |
| 1 GB - 10 GB | 5 minutes | 2000 | Premium EP1 |
| > 10 GB | 1 minute | 5000 | Premium EP2+ |

### Adjusting Configuration

```bash
# Update polling interval
az functionapp config appsettings set \
  --resource-group <RESOURCE_GROUP> \
  --name <FUNCTION_APP_NAME> \
  --settings POLLING_INTERVAL_MINUTES=1

# Update batch size
az functionapp config appsettings set \
  --resource-group <RESOURCE_GROUP> \
  --name <FUNCTION_APP_NAME> \
  --settings BATCH_SIZE=2000
```

---

## Security Best Practices

1. **Enable VNet Integration** for the Function App to secure network traffic
2. **Restrict Key Vault Access** to only the Function App's managed identity
3. **Enable Diagnostic Logging** for audit trails
4. **Use Private Endpoints** for Key Vault and Storage Account
5. **Rotate AWS Credentials** every 90 days (set a calendar reminder)

---

## Support Resources

- **Microsoft Sentinel Documentation**: https://docs.microsoft.com/azure/sentinel/
- **Azure Functions Documentation**: https://docs.microsoft.com/azure/azure-functions/
- **AWS S3 Documentation**: https://docs.aws.amazon.com/s3/
- **GitHub Issues**: https://github.com/Azure/Azure-Sentinel/issues

---

## Appendix: Quick Reference

### Key URLs

| Resource | URL Pattern |
|----------|-------------|
| Function App | `https://<function-app-name>.azurewebsites.net` |
| Key Vault | `https://<key-vault-name>.vault.azure.net` |
| Application Insights | Azure Portal > Application Insights > <app-name>-insights |
| Sentinel Workspace | Azure Portal > Microsoft Sentinel > <workspace-name> |

### Important Resource IDs

```
DCR Endpoint: https://<dce-name>.ingest.monitor.azure.com
DCR Rule ID: dcr-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
Stream Name: Custom-Custom_Firewall_CL
```
