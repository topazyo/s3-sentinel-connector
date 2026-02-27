# Local Pre-Publish Validation Report

- Generated: 2026-02-27 04:14:27 UTC
- Solution: S3SentinelConnector
- Summary: 14 passed / 0 failed

## Checks

| Check | Status | Details |
|-------|--------|---------|
| Required artifact files exist | ✅ PASS | All required files found |
| Package.json parse | ✅ PASS | Parsed successfully |
| Metadata.json parse | ✅ PASS | Parsed successfully |
| Workbook JSON parse | ✅ PASS | Parsed successfully |
| Workbook metadata JSON parse | ✅ PASS | Parsed successfully |
| Analytics rule YAML parse | ✅ PASS | Parsed successfully |
| Version alignment (Package.json vs Metadata.json) | ✅ PASS | Package=1.0.1, Metadata=1.0.1 |
| LastPublishDate alignment | ✅ PASS | Package=2026-02-27, Metadata=2026-02-27 |
| Package contentTypes include required types | ✅ PASS | All required types present |
| Package artifacts include required paths | ✅ PASS | All required artifact mappings present |
| Workbook schema/version shape | ✅ PASS | schema=https://github.com/Microsoft/Application-Insights-Workbooks/blob/master/schema/workbook.json, version=Notebook/1.0, items_type=list |
| Workbook metadata shape | ✅ PASS | Workbook metadata valid |
| Analytics rule required field coverage | ✅ PASS | All required fields present |
| Release notes table format | ✅ PASS | table_header=True, includes_version(1.0.1)=True |
