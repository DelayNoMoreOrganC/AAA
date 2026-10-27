# Archive V6 installer (PowerShell)
# Right-click -> Run with PowerShell
# Or: powershell -ExecutionPolicy Bypass -File install.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Log = Join-Path $Root "install.log"
$Backend = Join-Path $Root "app\web\backend"
$Req = Join-Path $Backend "requirements.txt"

function Write-Log($msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg"
    Add-Content -Path $Log -Value $line
    Write-Host $msg
}

try {
    Set-Location $Root
    Write-Log "=== Archive V6 install start ==="
    Write-Log "Root: $Root"

    if (-not (Test-Path (Join-Path $Backend "run.py"))) {
        throw "Missing app\web\backend\run.py. Unzip the full package first."
    }

    $python = $null
    $pyArgs = @()

    if (Get-Command python -ErrorAction SilentlyContinue) {
        $python = (Get-Command python).Source
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        $python = (Get-Command py).Source
        $pyArgs = @("-3")
    } else {
        throw "Python not found. Install Python 3.12+ and enable Add to PATH."
    }

    Write-Log "Python: $python $($pyArgs -join ' ')"
    & $python @pyArgs --version

    Write-Log "pip upgrade..."
    & $python @pyArgs -m pip install --upgrade pip 2>&1 | Tee-Object -FilePath $Log -Append

    Write-Log "pip install requirements..."
    & $python @pyArgs -m pip install -r $Req 2>&1 | Tee-Object -FilePath $Log -Append

    $data = Join-Path $Root "app\web\data"
    New-Item -ItemType Directory -Force -Path $data | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $data "orgs") | Out-Null

    Write-Host ""
    Write-Host "========================================"
    Write-Host "  Install OK. Starting server..."
    Write-Host "  http://127.0.0.1:8000"
    Write-Host "  No default accounts or passwords."
    Write-Host "  First setup: use the workstation launcher's one-time local /setup link."
    Write-Host "  See project-root docs/WORKSTATION_V0.1.md."
    Write-Host "========================================"
    Write-Host ""

    Set-Location $Backend
    & $python @pyArgs run.py
}
catch {
    Write-Log "ERROR: $_"
    Write-Host ""
    Write-Host "[ERROR] $_" -ForegroundColor Red
    Write-Host "See install.log in: $Root"
    Read-Host "Press Enter to exit"
    exit 1
}
