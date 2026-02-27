param(
    [Parameter(Mandatory = $false)]
    [string]$TerraformExe = "",
    [Parameter(Mandatory = $false)]
    [string[]]$TargetDirs = @(
        "deployment/terraform/environments",
        "deployment/terraform/environments/dev",
        "deployment/terraform/environments/prod"
    ),
    [Parameter(Mandatory = $false)]
    [switch]$Upgrade
)

$ErrorActionPreference = "Stop"

function Resolve-TerraformExe {
    param([string]$PreferredPath)

    if ($PreferredPath -and (Test-Path $PreferredPath)) {
        return $PreferredPath
    }

    $terraformOnPath = Get-Command terraform -ErrorAction SilentlyContinue
    if ($terraformOnPath -and (Test-Path $terraformOnPath.Source)) {
        return $terraformOnPath.Source
    }

    $localAppData = $env:LOCALAPPDATA
    if ($localAppData) {
        $wingetPackagesRoot = Join-Path $localAppData "Microsoft\WinGet\Packages"
        if (Test-Path $wingetPackagesRoot) {
            $candidate = Get-ChildItem $wingetPackagesRoot -Directory -Filter "Hashicorp.Terraform*" -ErrorAction SilentlyContinue |
                ForEach-Object {
                    Get-ChildItem $_.FullName -Recurse -Filter terraform.exe -ErrorAction SilentlyContinue
                } |
                Select-Object -First 1 -ExpandProperty FullName

            if ($candidate -and (Test-Path $candidate)) {
                return $candidate
            }
        }
    }

    $whereTerraform = & where.exe terraform 2>$null
    if ($LASTEXITCODE -eq 0 -and $whereTerraform) {
        $whereCandidate = ($whereTerraform | Select-Object -First 1).Trim()
        if ($whereCandidate -and (Test-Path $whereCandidate)) {
            return $whereCandidate
        }
    }

    throw "Terraform executable was not found. Install Terraform or add it to PATH."
}

$resolvedTerraform = Resolve-TerraformExe -PreferredPath $TerraformExe
Write-Host "Using terraform executable: $resolvedTerraform"

Write-Host "Terraform version:"
& $resolvedTerraform version

foreach ($dir in $TargetDirs) {
    if (-not (Test-Path $dir)) {
        throw "Target directory not found: $dir"
    }

    Write-Host "`n=== Validating $dir ==="

    $initArgs = @("-chdir=$dir", "init", "-backend=false", "-input=false", "-no-color")
    if ($Upgrade) {
        $initArgs += "-upgrade"
    }

    & $resolvedTerraform @initArgs
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    & $resolvedTerraform "-chdir=$dir" validate "-no-color"
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

Write-Host "`nTerraform validation succeeded for all target directories."
exit 0