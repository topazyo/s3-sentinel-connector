<#
.SYNOPSIS
    Validates ARM template deployment for S3 Sentinel Connector
    
.DESCRIPTION
    This script performs comprehensive validation of the ARM template
    without actually deploying resources. Use this before deployment
    to catch configuration errors early.

.PARAMETER ResourceGroupName
    Target resource group for validation

.PARAMETER ParametersFile
    Path to ARM template parameters file

.PARAMETER TemplateFile
    Path to ARM mainTemplate.json (default: ./TemplateSpecs/mainTemplate.json)

.EXAMPLE
    .\Test_Deployment.ps1 -ResourceGroupName "rg-sentinel-test" -ParametersFile "./parameters.json"
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroupName,
    
    [Parameter(Mandatory=$false)]
    [string]$ParametersFile,
    
    [Parameter(Mandatory=$false)]
    [string]$TemplateFile = "./TemplateSpecs/mainTemplate.json"
)

$ErrorActionPreference = "Stop"

function Write-Status {
    param([string]$Message, [string]$Status = "INFO")
    $color = switch ($Status) {
        "PASS" { "Green" }
        "FAIL" { "Red" }
        "WARN" { "Yellow" }
        default { "Cyan" }
    }
    $symbol = switch ($Status) {
        "PASS" { "✓" }
        "FAIL" { "✗" }
        "WARN" { "⚠" }
        default { "●" }
    }
    Write-Host "$symbol $Message" -ForegroundColor $color
}

function Test-AzureConnection {
    Write-Host "`n=== Azure Connection ===" -ForegroundColor Cyan
    try {
        $context = Get-AzContext
        if ($null -eq $context) {
            Write-Status "Not logged in to Azure" "FAIL"
            Write-Host "  Run: Connect-AzAccount" -ForegroundColor Yellow
            return $false
        }
        Write-Status "Connected to subscription: $($context.Subscription.Name)" "PASS"
        Write-Status "Tenant: $($context.Tenant.Id)" "INFO"
        return $true
    }
    catch {
        Write-Status "Failed to get Azure context: $_" "FAIL"
        return $false
    }
}

function Test-ResourceGroup {
    param([string]$Name)
    Write-Host "`n=== Resource Group ===" -ForegroundColor Cyan
    try {
        $rg = Get-AzResourceGroup -Name $Name -ErrorAction SilentlyContinue
        if ($null -eq $rg) {
            Write-Status "Resource group '$Name' does not exist" "WARN"
            Write-Host "  Will be created during deployment" -ForegroundColor Yellow
            return $true
        }
        Write-Status "Resource group exists: $($rg.Location)" "PASS"
        return $true
    }
    catch {
        Write-Status "Error checking resource group: $_" "FAIL"
        return $false
    }
}

function Test-TemplateFile {
    param([string]$Path)
    Write-Host "`n=== Template Validation ===" -ForegroundColor Cyan
    
    if (-not (Test-Path $Path)) {
        Write-Status "Template file not found: $Path" "FAIL"
        return $false
    }
    Write-Status "Template file exists" "PASS"
    
    try {
        $template = Get-Content $Path -Raw | ConvertFrom-Json -ErrorAction Stop
        Write-Status "Template is valid JSON" "PASS"
        
        # Check schema
        if ($template.'$schema' -match "deploymentTemplate") {
            Write-Status "Valid ARM template schema" "PASS"
        }
        else {
            Write-Status "Invalid or missing schema" "WARN"
        }
        
        # Check required sections
        $requiredSections = @('parameters', 'resources')
        foreach ($section in $requiredSections) {
            if ($template.$section) {
                Write-Status "Section '$section' present" "PASS"
            }
            else {
                Write-Status "Missing required section: $section" "FAIL"
                return $false
            }
        }
        
        # List parameters
        $paramCount = ($template.parameters | Get-Member -MemberType NoteProperty).Count
        Write-Status "Parameters defined: $paramCount" "INFO"
        
        # List resources
        $resourceCount = $template.resources.Count
        Write-Status "Resources defined: $resourceCount" "INFO"
        
        return $true
    }
    catch {
        Write-Status "Failed to parse template: $_" "FAIL"
        return $false
    }
}

function Test-ParametersFile {
    param([string]$Path)
    Write-Host "`n=== Parameters Validation ===" -ForegroundColor Cyan
    
    if ([string]::IsNullOrEmpty($Path)) {
        Write-Status "No parameters file specified (will use defaults)" "WARN"
        return $true
    }
    
    if (-not (Test-Path $Path)) {
        Write-Status "Parameters file not found: $Path" "FAIL"
        return $false
    }
    Write-Status "Parameters file exists" "PASS"
    
    try {
        $params = Get-Content $Path -Raw | ConvertFrom-Json -ErrorAction Stop
        Write-Status "Parameters file is valid JSON" "PASS"
        
        # List parameter values (mask secrets)
        if ($params.parameters) {
            $params.parameters | Get-Member -MemberType NoteProperty | ForEach-Object {
                $name = $_.Name
                $value = $params.parameters.$name.value
                if ($name -match "key|secret|password|credential") {
                    Write-Status "  $name = ********" "INFO"
                }
                else {
                    Write-Status "  $name = $value" "INFO"
                }
            }
        }
        
        return $true
    }
    catch {
        Write-Status "Failed to parse parameters: $_" "FAIL"
        return $false
    }
}

function Test-ArmDeployment {
    param(
        [string]$ResourceGroupName,
        [string]$TemplateFile,
        [string]$ParametersFile
    )
    Write-Host "`n=== ARM Deployment Validation ===" -ForegroundColor Cyan
    
    try {
        $deployParams = @{
            ResourceGroupName = $ResourceGroupName
            TemplateFile = $TemplateFile
            Mode = "Incremental"
        }
        
        if (-not [string]::IsNullOrEmpty($ParametersFile)) {
            $deployParams['TemplateParameterFile'] = $ParametersFile
        }
        
        Write-Status "Running what-if deployment..." "INFO"
        
        # Test deployment
        $result = Test-AzResourceGroupDeployment @deployParams -ErrorAction Stop
        
        if ($null -eq $result -or $result.Count -eq 0) {
            Write-Status "Template validation passed" "PASS"
            return $true
        }
        else {
            Write-Status "Template validation failed" "FAIL"
            foreach ($validationError in $result) {
                Write-Host "  Error: $($validationError.Message)" -ForegroundColor Red
            }
            return $false
        }
    }
    catch {
        Write-Status "Deployment validation failed: $_" "FAIL"
        return $false
    }
}

function Test-RequiredProviders {
    Write-Host "`n=== Resource Provider Registration ===" -ForegroundColor Cyan
    
    $requiredProviders = @(
        "Microsoft.Web",
        "Microsoft.Storage",
        "Microsoft.KeyVault",
        "Microsoft.Insights",
        "Microsoft.OperationalInsights"
    )
    
    $allRegistered = $true
    foreach ($provider in $requiredProviders) {
        try {
            $reg = Get-AzResourceProvider -ProviderNamespace $provider -ErrorAction SilentlyContinue
            if ($reg.RegistrationState -eq "Registered") {
                Write-Status "$provider is registered" "PASS"
            }
            else {
                Write-Status "$provider is not registered" "WARN"
                Write-Host "  Run: Register-AzResourceProvider -ProviderNamespace $provider" -ForegroundColor Yellow
            }
        }
        catch {
            Write-Status "Failed to check $provider" "WARN"
        }
    }
    
    return $allRegistered
}

# Main execution
Write-Host @"

===============================================
S3 Sentinel Connector - Deployment Validator
===============================================
"@ -ForegroundColor Cyan

$allPassed = $true

# Run tests
if (-not (Test-AzureConnection)) { $allPassed = $false }
if (-not (Test-ResourceGroup -Name $ResourceGroupName)) { $allPassed = $false }
if (-not (Test-TemplateFile -Path $TemplateFile)) { $allPassed = $false }
if (-not (Test-ParametersFile -Path $ParametersFile)) { $allPassed = $false }
if (-not (Test-RequiredProviders)) { $allPassed = $false }

# Only run deployment validation if basic checks pass
if ($allPassed) {
    # Ensure resource group exists for validation
    $rg = Get-AzResourceGroup -Name $ResourceGroupName -ErrorAction SilentlyContinue
    if ($null -eq $rg) {
        Write-Status "Creating temporary resource group for validation..." "INFO"
        New-AzResourceGroup -Name $ResourceGroupName -Location "eastus" -Force | Out-Null
    }
    
    if (-not (Test-ArmDeployment -ResourceGroupName $ResourceGroupName -TemplateFile $TemplateFile -ParametersFile $ParametersFile)) {
        $allPassed = $false
    }
}

# Summary
Write-Host "`n===============================================" -ForegroundColor Cyan
if ($allPassed) {
    Write-Status "All validation checks passed!" "PASS"
    Write-Host @"

Next steps:
1. Deploy the template:
   az deployment group create \
     --resource-group $ResourceGroupName \
     --template-file $TemplateFile \
     --parameters @$ParametersFile

2. Follow Post-Deployment.md for configuration steps

"@ -ForegroundColor Green
    exit 0
}
else {
    Write-Status "Some validation checks failed" "FAIL"
    Write-Host "Please fix the issues above before deploying." -ForegroundColor Yellow
    exit 1
}
