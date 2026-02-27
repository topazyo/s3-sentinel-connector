# Verification Runbook

This folder contains local/offline validation tools for the `S3SentinelConnector` solution package.

## Purpose

Provide a repeatable pre-publish validation sequence in environments where external Sentinel packaging tooling and ARM-TTK are not present.

## Quick Start (One Command)

From repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\Solutions\S3SentinelConnector\Verification\Run_Local_Readiness.ps1
```

## Step-by-Step Commands

1. Local package validator

```bash
python Solutions/S3SentinelConnector/Verification/Validate_Package_Local.py
```

2. Optional ARM pre-deployment validation (requires Azure context)

```powershell
powershell -ExecutionPolicy Bypass -File .\Solutions\S3SentinelConnector\Verification\Test_Deployment.ps1 -ResourceGroupName <rg-name> -TemplateFile .\Solutions\S3SentinelConnector\TemplateSpecs\mainTemplate.json
```

3. Optional ingestion simulation (requires Azure DCE/DCR and auth)

```bash
python Solutions/S3SentinelConnector/Verification/Simulate_Ingest.py --dce-endpoint https://<dce>.ingest.monitor.azure.com --dcr-rule-id dcr-<immutable-id> --stream-name Custom-Custom_Firewall_CL --validate-only
```

## Generated Evidence Files

- `PrePublish_Validation_Report.md`: Detailed pass/fail table from local package checks.
- `Readiness_Summary.md`: Consolidated readiness status and blocker summary.

## Validation Scope

The local validator currently checks:

- Required solution artifact file presence
- JSON and YAML parse validity for package/workbook/rule files
- `Package.json` ↔ `Metadata.json` version/date alignment
- Required `contentTypes` and artifact path mappings
- Workbook template shape checks
- Analytics rule required-field checks
- Release notes table format and current version entry

## Known External Blockers

The following final pre-publish checks are out of scope locally and must be run in CI/publish pipeline:

- Microsoft Sentinel packaging tool (`Tools/Create-Azure-Sentinel-Solution`)
- ARM-TTK validation

## Human Handoff Commands (External Packaging Environment)

Run the following in an environment where Sentinel packaging tools and ARM-TTK are installed:

1. Re-run local readiness baseline

```powershell
powershell -ExecutionPolicy Bypass -File .\Solutions\S3SentinelConnector\Verification\Run_Local_Readiness.ps1
```

2. Sentinel packaging tool discovery/help (confirm script path and parameters in your packaging tool checkout)

```powershell
powershell -ExecutionPolicy Bypass -File .\Tools\Create-Azure-Sentinel-Solution\pipeline\createSolutionV4.ps1 -?
```

3. ARM-TTK template validation

```powershell
Import-Module <path-to-arm-ttk>\arm-ttk.psd1
Test-AzTemplate -TemplatePath .\Solutions\S3SentinelConnector\TemplateSpecs\mainTemplate.json
```

4. Attach generated outputs to release evidence

- `Solutions/S3SentinelConnector/Verification/PrePublish_Validation_Report.md`
- `Solutions/S3SentinelConnector/Verification/Readiness_Summary.md`
- Packaging-tool output logs
- ARM-TTK output logs

## Ownership

- Audit context: Phase 8 (documentation) and Phase 10 (execution evidence)
- Tracking: `audit/VIBE_DEBT_INVENTORY_ACTIVE.md`, `audit/VIBE_BATCH_EXECUTION_PLAN.md`, and `audit/VIBE_PROGRESS_REPORTS/week_06.md`
