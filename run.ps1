# Jarvis launcher for Windows (PowerShell)
$ErrorActionPreference = "Stop"
Write-Host "=== Jarvis ===" -ForegroundColor Cyan

function Get-PreferredPython {
    # Prefer 3.12/3.11 — native wheels (pyaudio, webrtcvad) are unreliable on 3.14+.
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        foreach ($ver in @("3.12", "3.11")) {
            try {
                $exe = & py "-$ver" -c "import sys; print(sys.executable)" 2>$null
                if ($LASTEXITCODE -eq 0 -and $exe) {
                    return $exe.Trim()
                }
            } catch {
                continue
            }
        }
    }
    $py = Get-Command python -ErrorAction SilentlyContinue
    if ($py) {
        return $py.Source
    }
    return $null
}

$pythonExe = Get-PreferredPython
if (-not $pythonExe) {
    Write-Host "Python not found. Install Python 3.11 or 3.12 from python.org" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment with $pythonExe ..."
    & $pythonExe -m venv .venv
}

. .venv\Scripts\Activate.ps1
$venvVersion = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($venvVersion -match '^3\.(1[4-9]|[2-9][0-9])') {
    Write-Warning "venv is Python $venvVersion — recreate with 3.12 for webrtcvad/pyaudio wheels: Remove-Item -Recurse .venv; .\run.ps1"
}

$env:PYTHONUTF8 = "1"
pip install -q -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Warning "Some pip packages failed — retrying without webrtcvad (needs MSVC on Windows)..."
    Get-Content requirements.txt | Where-Object { $_ -notmatch '^\s*webrtcvad' } | Set-Content .requirements-install-tmp.txt
    pip install -q -r .requirements-install-tmp.txt
    Remove-Item .requirements-install-tmp.txt -ErrorAction SilentlyContinue
}
if ($LASTEXITCODE -ne 0) {
    Write-Warning "Some pip packages still failed (often PyAudio on exotic Python builds). Jarvis may still run via sounddevice."
}

if (Test-Path ".env") {
    Get-Content .env | ForEach-Object {
        if ($_ -match '^([^#=]+)=(.*)$') {
            [System.Environment]::SetEnvironmentVariable($Matches[1].Trim(), $Matches[2].Trim(), 'Process')
        }
    }
}

python main.py
