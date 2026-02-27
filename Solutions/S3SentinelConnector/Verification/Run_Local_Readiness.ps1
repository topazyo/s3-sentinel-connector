<#
.SYNOPSIS
    Runs local pre-publish readiness checks for S3SentinelConnector.

.DESCRIPTION
    Executes Validate_Package_Local.py and produces a consolidated readiness summary
    at Verification/Readiness_Summary.md. This script intentionally limits checks
    to local/offline validation and documents external-tooling blockers.

.EXAMPLE
    .\Run_Local_Readiness.ps1
#>

param(
    [Parameter(Mandatory = $false)]
    [string]$PythonExe = "C:/Users/Topaz/Github/s3-sentinel-connector/.venv/Scripts/python.exe"
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$solutionRoot = Split-Path -Parent $scriptRoot
$validatorScript = Join-Path $scriptRoot "Validate_Package_Local.py"
$validationReport = Join-Path $scriptRoot "PrePublish_Validation_Report.md"
$readinessSummary = Join-Path $scriptRoot "Readiness_Summary.md"

function Write-Status {
    param([string]$Message, [string]$Status = "INFO")
    $color = switch ($Status) {
        "PASS" { "Green" }
        "FAIL" { "Red" }
        "WARN" { "Yellow" }
        default { "Cyan" }
    }
    $symbol = switch ($Status) {
        "PASS" { "[PASS]" }
        "FAIL" { "[FAIL]" }
        "WARN" { "[WARN]" }
        default { "[INFO]" }
    }
    Write-Host "$symbol $Message" -ForegroundColor $color
}

Write-Host "`n=======================================================" -ForegroundColor Cyan
Write-Host "S3SentinelConnector Local Readiness Runner" -ForegroundColor Cyan
Write-Host "=======================================================`n" -ForegroundColor Cyan

if (-not (Test-Path $validatorScript)) {
    Write-Status "Validator script missing: $validatorScript" "FAIL"
    exit 1
}

if (-not (Test-Path $PythonExe)) {
    Write-Status "Python executable not found: $PythonExe" "FAIL"
    exit 1
}

Write-Status "Running local package validator" "INFO"
$validatorOutput = & $PythonExe $validatorScript 2>&1
$validatorExitCode = $LASTEXITCODE

foreach ($line in $validatorOutput) {
    Write-Host $line
}

if ($validatorExitCode -ne 0) {
    Write-Status "Local package validator failed" "FAIL"
} else {
    Write-Status "Local package validator passed" "PASS"
}

$generatedUtc = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd HH:mm:ss 'UTC'")
$overallStatus = if ($validatorExitCode -eq 0) { "PASS" } else { "FAIL" }

$summary = @()
$summary += "# Local Readiness Summary"
$summary += ""
$summary += "- Generated: $generatedUtc"
$summary += "- Solution: S3SentinelConnector"
$summary += "- Overall Status: **$overallStatus**"
$summary += ""
$summary += "## Executed Checks"
$summary += ""
$summary += "1. Local package consistency validation (Validate_Package_Local.py)"
$summary += "2. Artifact presence and parse checks (JSON/YAML)"
$summary += "3. Package/metadata version-date alignment checks"
$summary += "4. Workbook and analytics rule shape checks"
$summary += ""
$summary += "## Artifacts"
$summary += ""
$summary += "- Detailed report: Verification/PrePublish_Validation_Report.md"
$summary += ""
$summary += "## External Validation Blockers"
$summary += ""
$summary += "- Sentinel packaging tool (Tools/Create-Azure-Sentinel-Solution) not present in this repository."
$summary += "- ARM-TTK scripts not present in this repository."
$summary += "- These checks remain required in CI/publish pipeline before marketplace submission."

$summary -join "`n" | Out-File -FilePath $readinessSummary -Encoding utf8

Write-Status "Readiness summary written: $readinessSummary" "PASS"

if ($validatorExitCode -ne 0) {
    exit $validatorExitCode
}

exit 0
