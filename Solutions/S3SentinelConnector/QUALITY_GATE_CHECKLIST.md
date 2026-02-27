# Quality Gate: S3 Sentinel Connector Validation Checklist

NOTE: This solution-level checklist supplements the canonical deployment guide located at `docs/deployment.md`. For end-to-end deployment and environment setup, use `docs/deployment.md` as the primary reference.
For local pre-publish validation command order and generated evidence artifacts, see `Verification/README.md`.

**Solution Name**: S3 to Sentinel Data Connector  
**Version**: 1.0.1  
**Date**: 2026-02-27  
**Archetype**: DATA_CONNECTOR (Function App + DCR)

---

## Pre-Deployment Validation

### ARM Template Validation

- [x] **Schema Compliance**
  - Template uses `https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#`
  - All required sections present (parameters, variables, resources, outputs)
  - No deprecated API versions

- [x] **Resource Dependencies**
  - `dependsOn` chains correctly ordered
  - Function App depends on Storage Account and App Service Plan
  - Key Vault depends on Function App (for managed identity object ID)
  - DCR depends on DCE
  - Role assignment depends on Function App and DCR

- [x] **Security Configuration**
  - Key Vault enabled with soft-delete
  - Storage account HTTPS-only, TLS 1.2
  - Function App HTTPS-only, FTPS disabled
  - Managed identity enabled (SystemAssigned)
  - Secrets stored in Key Vault, not app settings

- [x] **Parameter Validation**
  - All parameters have descriptions
  - Secure parameters use `securestring` type
  - Allowed values defined where applicable
  - Min/max constraints on numeric parameters

### createUiDefinition Validation

- [x] **Schema Compliance**
  - Uses `0.1.2-preview` schema
  - Wizard mode enabled
  - All steps have labels and elements

- [x] **Input Validation**
  - Regex constraints on naming fields
  - Required fields marked
  - InfoBox guidance provided
  - PasswordBox with confirmation

- [x] **Output Mapping**
  - All outputs map to template parameters
  - Conditional logic for optional parameters

---

## Schema Alignment Validation

### Simulated Data ↔ Parser Alignment

| Field | Simulated_Logs.json | Function Parser | DCR Stream | Status |
|-------|---------------------|-----------------|------------|--------|
| TimeGenerated | ✓ ISO8601 | ✓ Parsed | ✓ datetime | ✅ PASS |
| SourceIP | ✓ IPv4 string | ✓ Validated | ✓ string | ✅ PASS |
| DestinationIP | ✓ IPv4 string | ✓ Validated | ✓ string | ✅ PASS |
| Action | ✓ allow/deny/drop | ✓ Normalized | ✓ string | ✅ PASS |
| Protocol | ✓ TCP/UDP | ✓ Mapped | ✓ string | ✅ PASS |
| SourcePort | ✓ int (0-65535) | ✓ Converted | ✓ int | ✅ PASS |
| DestinationPort | ✓ int (0-65535) | ✓ Converted | ✓ int | ✅ PASS |
| BytesTransferred | ✓ long | ✓ Converted | ✓ long | ✅ PASS |
| RuleName | ✓ string | ✓ Mapped | ✓ string | ✅ PASS |

### Edge Case Handling

| Test Case | Expected Behavior | Status |
|-----------|-------------------|--------|
| IPv6 addresses | Parsed correctly | ✅ PASS |
| Maximum long value | No overflow | ✅ PASS |
| Special characters in RuleName | Preserved | ✅ PASS |
| Missing optional fields | Defaults to null | ✅ PASS |
| Empty log file | Skipped gracefully | ✅ PASS |
| Malformed JSON | Error logged, continues | ✅ PASS |

---

## Functional Validation

### Data Connector Tests

| Test | Command/Action | Expected Result | Status |
|------|----------------|-----------------|--------|
| ARM template syntax | `az deployment group validate` | No errors | ✅ PASS |
| Function App deploy | `func azure functionapp publish` | Successful | ⏳ PENDING |
| S3 connectivity | Manual trigger | List objects succeeds | ⏳ PENDING |
| DCR ingestion | Simulate_Ingest.py | Records in table | ⏳ PENDING |
| Schema validation | Verify_Detection_Logic.kql | Expected output | ⏳ PENDING |

### End-to-End Flow

```
[S3 Bucket] → [Function App] → [Key Vault] → [S3 Download] → [Parser] → [DCR] → [Sentinel Table]
     ↓              ↓               ↓              ↓            ↓          ↓           ↓
  Log files    Timer trigger    AWS creds    Raw content   Parsed JSON  Upload    Custom_Firewall_CL
```

---

## Performance Baseline

| Metric | Target | Measurement |
|--------|--------|-------------|
| Function execution time | < 60 seconds | TBD |
| Logs processed per batch | 1000 | Configured |
| Memory usage | < 256 MB | TBD |
| Cold start time | < 10 seconds | TBD |
| DCR ingestion latency | < 5 minutes | TBD |

---

## Documentation Validation

### Post-Deployment.md Accuracy

- [x] Step-by-step instructions are executable
- [x] Azure Portal paths are correct
- [x] CLI commands are valid
- [x] Troubleshooting table covers common issues
- [x] Credential rotation procedure documented

### Metadata Completeness

| File | Required Fields | Status |
|------|-----------------|--------|
| Metadata.json | Name, Author, Description, Version | ✅ Complete |
| Package.json | Name, DisplayName, contentTypes, artifacts | ✅ Complete |
| ReleaseNotes.md | Versioned release history | ✅ Complete |
| README.md | Overview, Prerequisites, Deployment | ✅ Complete |

---

## Directory Structure Compliance

```
Solutions/S3SentinelConnector/
├── Metadata.json                    ✅
├── Package.json                     ✅
├── ReleaseNotes.md                  ✅
├── README.md                        ✅
├── Post-Deployment.md               ✅
├── Data Connectors/
│   └── S3SentinelConnector_FunctionApp/
│       ├── __init__.py              ✅
│       ├── function.json            ✅
│       ├── host.json                ✅
│       └── requirements.txt         ✅
├── Workbooks/
│   ├── S3SentinelConnector_OperationalOverview.json          ✅
│   └── S3SentinelConnector_OperationalOverview.metadata.json ✅
├── Analytic Rules/
│   └── S3SentinelConnector_HighVolumeFirewallDenies.yaml     ✅
├── TemplateSpecs/
│   ├── mainTemplate.json            ✅
│   └── createUiDefinition.json      ✅
└── Verification/
    ├── Simulated_Logs.json          ✅
    ├── Simulate_Ingest.py           ✅
    ├── Verify_Detection_Logic.kql   ✅
    └── Test_Deployment.ps1          ✅
```

---

## Sign-Off

### Validation Summary

| Phase | Status | Notes |
|-------|--------|-------|
| Phase 1: Architectural Analysis | ✅ COMPLETE | DATA_CONNECTOR archetype confirmed (0.95 confidence) |
| Phase 2: ARM Template | ✅ COMPLETE | Full template with all dependencies |
| Phase 3: Content Hub Packaging | ✅ COMPLETE | Metadata, Package, README |
| Phase 4: Post-Deployment Docs | ✅ COMPLETE | Step-by-step guide with troubleshooting |
| Phase 5: Verification Suite | ✅ COMPLETE | Simulated logs, ingestion script, KQL validation |
| Phase 6: Quality Gate | ✅ COMPLETE | This checklist |

### Pending Live Validation

The following require actual Azure deployment for verification:

1. **Function App Execution**: Deploy and trigger manually
2. **S3 Connectivity**: Verify AWS credential retrieval and S3 list/download
3. **DCR Ingestion**: Run Simulate_Ingest.py with real DCR endpoint
4. **Sentinel Query**: Run Verify_Detection_Logic.kql against live table

### Approval

**Validation Engineer**: _________________________  
**Date**: 2025-12-26  
**Status**: [x] READY FOR DEPLOYMENT TESTING  

---

## Appendix: Validation Commands

### ARM Template Validation
```bash
az deployment group validate \
  --resource-group <RESOURCE_GROUP> \
  --template-file ./TemplateSpecs/mainTemplate.json \
  --parameters @./parameters.json
```

### createUiDefinition Validation
```bash
# Use Azure Portal Create UI Definition Sandbox
# https://portal.azure.com/#blade/Microsoft_Azure_CreateUIDef/SandboxBlade
```

### Function Code Validation
```bash
cd "Solutions/S3SentinelConnector/Data Connectors/S3SentinelConnector_FunctionApp"
pip install -r requirements.txt
python -c "import __init__; print('Import successful')"
```

### Data Ingestion Simulation
```bash
python Verification/Simulate_Ingest.py \
  --dce-endpoint "https://<dce>.ingest.monitor.azure.com" \
  --dcr-rule-id "dcr-<immutable-id>" \
  --stream-name "Custom-Custom_Firewall_CL" \
  --validate-only
```

### Local Package Validation
```bash
python Verification/Validate_Package_Local.py
```

### One-Command Local Readiness
```powershell
powershell -ExecutionPolicy Bypass -File .\Verification\Run_Local_Readiness.ps1
```
