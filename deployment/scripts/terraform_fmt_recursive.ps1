param(
    [Parameter(Mandatory = $false)]
    [string]$TerraformExe = "",
    [Parameter(Mandatory = $false)]
    [string]$TargetDir = "deployment/terraform",
    [Parameter(Mandatory = $false)]
    [switch]$Check
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

if (-not (Test-Path $TargetDir)) {
    throw "Target directory not found: $TargetDir"
}

Write-Host "Terraform version:"
& $resolvedTerraform version

$fmtArgs = @("fmt", "-recursive")
if ($Check) {
    $fmtArgs += "-check"
    Write-Host "Running Terraform formatting check (non-mutating mode)..."
}
$fmtArgs += $TargetDir

& $resolvedTerraform @fmtArgs
exit $LASTEXITCODE
