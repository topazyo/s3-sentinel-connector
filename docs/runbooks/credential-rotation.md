# Runbook: Credential Rotation

## Summary
Rotate AWS and Azure credentials used by the S3 to Sentinel Connector.

> **Automated Rotation:** The connector includes `RotationManager` (`src/security/rotation_manager.py`)
> which automatically rotates credentials when they exceed `max_age_days` (default: 90) or
> `min_rotation_interval_hours` (default: 24). Use this runbook for **manual rotation** or
> when automated rotation has failed. For automated rotation status, check the
> `credential_rotated` metric in `PipelineMonitor`.

## When to Use
- Scheduled credential rotation (recommended: every 90 days)
- Suspected credential compromise
- Employee departure with credential access
- Security audit requirement

## Prerequisites
- [ ] Access to Azure Key Vault (Contributor role or higher)
- [ ] Access to AWS IAM (AdministratorAccess or IAMFullAccess)
- [ ] Access to Azure Portal or Azure CLI
- [ ] Access to connector deployment (for verification)

## Procedure

### Step 1: Generate New AWS Credentials

```bash
# Using AWS CLI
aws iam create-access-key --user-name sentinel-connector-service

# Note the AccessKeyId and SecretAccessKey from output
```

### Step 2: Store New Credentials in Key Vault

```bash
# Using Azure CLI
az keyvault secret set \
  --vault-name <your-vault-name> \
  --name aws-access-key-id \
  --value "<new-access-key-id>"

az keyvault secret set \
  --vault-name <your-vault-name> \
  --name aws-secret-access-key \
  --value "<new-secret-access-key>"
```

### Step 3: Verify New Credentials Work

```bash
# Force credential refresh in running connector
# Option A: Restart the service
kubectl rollout restart deployment/s3-sentinel-connector

# Option B: Wait for cache expiry (default: 1 hour)
# Monitor logs for successful S3 operations
kubectl logs -l app=s3-sentinel-connector --tail=100 | grep "S3 list_objects"
```

### Step 4: Delete Old AWS Credentials (After Grace Period)

**Wait 24 hours** to ensure no processes are using old credentials.

```bash
# List access keys for the service user
aws iam list-access-keys --user-name sentinel-connector-service

# Delete the OLD access key (not the new one!)
aws iam delete-access-key \
  --user-name sentinel-connector-service \
  --access-key-id <old-access-key-id>
```

### Step 5: Document Rotation

Update the rotation log:
- Date of rotation
- Reason for rotation
- Old key ID (last 4 characters): `...XXXX`
- New key ID (last 4 characters): `...YYYY`
- Performed by

## Verification
- [ ] New credentials stored in Key Vault
- [ ] Connector successfully connects to S3 (check logs)
- [ ] Old credentials deleted from AWS IAM
- [ ] Rotation documented

## Rollback

If new credentials don't work:

1. **Do NOT delete old credentials yet**
2. Restore old credentials in Key Vault:
   ```bash
   az keyvault secret set --vault-name <vault> --name aws-access-key-id --value "<old-value>"
   ```
3. Force credential refresh (restart service)
4. Investigate why new credentials failed

## Escalation

If rotation fails or service is degraded:
1. Page on-call SRE
2. Create incident ticket
3. Notify security team if compromise is suspected

## Related ADRs
- [ADR-003: Credential Management via Azure Key Vault](../adr/ADR-003-credential-management.md)
- [ADR-006: Config Env Override Path Rules](../adr/ADR-006-config-env-override-path-rules.md)
