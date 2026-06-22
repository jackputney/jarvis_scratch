# Jarvis launcher for Windows (PowerShell)
$ErrorActionPreference = "Stop"
Write-Host "=== Jarvis ===" -ForegroundColor Cyan

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "Python not found. Install Python 3.11+ from python.org" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..."
    python -m venv .venv
}

. .venv\Scripts\Activate.ps1
$env:PYTHONUTF8 = "1"
pip install -q -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Warning "Some pip packages failed (often PyAudio/webrtcvad on Windows). Jarvis may still run via sounddevice."
}

if (Test-Path ".env") {
    Get-Content .env | ForEach-Object {
        if ($_ -match '^([^#=]+)=(.*)$') {
            [System.Environment]::SetEnvironmentVariable($Matches[1].Trim(), $Matches[2].Trim(), 'Process')
        }
    }
}

python main.py
