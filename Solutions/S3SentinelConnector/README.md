# S3 to Sentinel Data Connector

<img src="https://raw.githubusercontent.com/Azure/Azure-Sentinel/master/Logos/AWS_Logo.svg" alt="AWS Logo" width="75px" height="75px">

## Overview

The **S3 to Sentinel Data Connector** enables secure, high-performance ingestion of logs from AWS S3 buckets into Microsoft Sentinel. This solution is ideal for organizations that:

- Store security logs (firewall, VPN, application) in AWS S3
- Need to centralize multi-cloud security data in Microsoft Sentinel
- Require automated, scheduled log ingestion with minimal operational overhead
- Want enterprise-grade security with Key Vault-managed credentials

## Features

| Feature | Description |
|---------|-------------|
| **Multi-Format Parsing** | Built-in parsers for firewall logs, VPN logs, and extensible custom formats |
| **Automatic Schema Transformation** | Converts source log fields to Sentinel-compatible schemas |
| **Secure Credential Management** | AWS credentials stored in Azure Key Vault with managed identity access |
| **Batch Processing** | Configurable batch sizes for optimal throughput and cost efficiency |
| **Compression Support** | Handles gzip-compressed log files automatically |
| **Monitoring & Alerting** | Prometheus metrics, Azure Application Insights, and custom alerts |
| **ML-Powered Anomaly Detection** | Optional TensorFlow-based anomaly detection for log analysis |

## Architecture

```
┌─────────────────┐         ┌─────────────────┐         ┌─────────────────┐
│   AWS S3        │         │  Azure Function │         │   Microsoft     │
│   Bucket        │◄───────►│     App         │────────►│   Sentinel      │
│   (Logs)        │  Poll   │  (Python 3.11)  │   DCR   │   (Log Table)   │
└─────────────────┘         └────────┬────────┘         └─────────────────┘
                                     │
                            ┌────────▼────────┐
                            │  Azure Key      │
                            │  Vault          │
                            │  (Credentials)  │
                            └─────────────────┘
```

## Prerequisites

1. **Microsoft Sentinel** enabled on a Log Analytics workspace
2. **AWS S3 bucket** with logs to ingest
3. **AWS IAM user** with the following permissions:
   - `s3:GetObject` on the target bucket
   - `s3:ListBucket` on the target bucket
4. **Azure subscription** with Contributor access to deploy resources

## Deployment

NOTE: This solution README contains solution-specific deployment options. For the canonical end-to-end deployment instructions, use `docs/deployment.md`.

### Deploy via Azure Portal

1. Click the **Deploy to Azure** button below
2. Fill in the required parameters:
   - Function App name
   - Storage account name
   - Log Analytics workspace name
   - AWS credentials and bucket information
3. Review and create the deployment
4. Follow post-deployment steps to deploy function code

[![Deploy to Azure](https://aka.ms/deploytoazurebutton)](https://portal.azure.com/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2FAzure%2FAzure-Sentinel%2Fmaster%2FSolutions%2FS3SentinelConnector%2FTemplateSpecs%2FmainTemplate.json/createUIDefinitionUri/https%3A%2F%2Fraw.githubusercontent.com%2FAzure%2FAzure-Sentinel%2Fmaster%2FSolutions%2FS3SentinelConnector%2FTemplateSpecs%2FcreateUiDefinition.json)

### Deploy via Azure CLI

```bash
# Set variables
RESOURCE_GROUP="rg-sentinel-connector"
LOCATION="eastus"
TEMPLATE_FILE="./TemplateSpecs/mainTemplate.json"
PARAMETERS_FILE="./TemplateSpecs/parameters.json"

# Create resource group
az group create --name $RESOURCE_GROUP --location $LOCATION

# Deploy template
az deployment group create \
  --resource-group $RESOURCE_GROUP \
  --template-file $TEMPLATE_FILE \
  --parameters @$PARAMETERS_FILE
```

## Configuration

### Required Parameters

| Parameter | Description | Example |
|-----------|-------------|---------|
| `workspaceName` | Log Analytics workspace name | `sentinel-workspace` |
| `functionAppName` | Unique Function App name | `s3-sentinel-func` |
| `storageAccountName` | Storage account for function runtime | `s3sentinelstore` |
| `keyVaultName` | Key Vault for credentials | `s3sentinel-kv` |
| `awsAccessKeyId` | AWS Access Key ID | `AKIA...` |
| `awsSecretAccessKey` | AWS Secret Access Key | `********` |
| `s3BucketName` | S3 bucket name | `my-logs-bucket` |

### Optional Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `awsRegion` | `us-west-2` | AWS region for S3 bucket |
| `s3Prefix` | `logs/` | S3 key prefix filter |
| `pollingIntervalMinutes` | `5` | Polling frequency |
| `batchSize` | `1000` | Records per batch |
| `logType` | `firewall` | Log type (firewall/vpn) |

## Log Schemas

### Firewall Logs (Custom_Firewall_CL)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `TimeGenerated` | datetime | Yes | Event timestamp |
| `SourceIP` | string | Yes | Source IP address |
| `DestinationIP` | string | Yes | Destination IP address |
| `Action` | string | Yes | Firewall action (allow/deny/drop) |
| `Protocol` | string | No | Network protocol |
| `SourcePort` | int | No | Source port number |
| `DestinationPort` | int | No | Destination port number |
| `BytesTransferred` | long | No | Bytes transferred |
| `RuleName` | string | No | Firewall rule name |

### VPN Logs (Custom_VPN_CL)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `TimeGenerated` | datetime | Yes | Event timestamp |
| `UserPrincipalName` | string | Yes | User identifier |
| `SessionID` | string | Yes | VPN session ID |
| `ClientIP` | string | Yes | Client IP address |
| `BytesIn` | long | No | Bytes received |
| `BytesOut` | long | No | Bytes sent |
| `ConnectionDuration` | int | No | Session duration (seconds) |

## Troubleshooting

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| No data in Sentinel | Function not triggered | Check timer trigger in Function App |
| Authentication errors | Invalid AWS credentials | Verify Key Vault secrets are correct |
| Partial data ingestion | Batch failures | Check Application Insights for errors |
| Schema validation errors | Field type mismatch | Verify log format matches expected schema |

### Viewing Logs

```kql
// Check recent ingestion
Custom_Firewall_CL
| where TimeGenerated > ago(24h)
| summarize count() by bin(TimeGenerated, 1h)
| render timechart

// Check for errors
AzureDiagnostics
| where ResourceProvider == "MICROSOFT.WEB"
| where Category == "FunctionAppLogs"
| where Level == "Error"
| project TimeGenerated, Message
```

## Security Considerations

1. **Credential Rotation**: Rotate AWS credentials every 90 days
2. **Network Isolation**: Consider VNet integration for the Function App
3. **Minimal Permissions**: Use read-only S3 permissions for the IAM user
4. **Audit Logging**: Enable Key Vault diagnostic logs

## Support

- **Documentation**: [Full Documentation](./docs/)
- **Issues**: [GitHub Issues](https://github.com/Azure/Azure-Sentinel/issues)
- **Email**: support@microsoft.com

## License

This project is licensed under the MIT License. See [LICENSE](./LICENSE) for details.
