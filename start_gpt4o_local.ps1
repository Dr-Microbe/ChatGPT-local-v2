$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (!(Test-Path $python)) {
    Write-Host ""
    Write-Host "Could not find .venv\Scripts\python.exe" -ForegroundColor Red
    Write-Host "Create a virtual environment and install dependencies first." -ForegroundColor Yellow
    Read-Host "Press Enter to close this window"
    exit 1
}

$envFile = Join-Path $PSScriptRoot ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if (!$line -or $line.StartsWith("#") -or !$line.Contains("=")) { return }
        $name, $value = $line.Split("=", 2)
        [Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim().Trim('"'), "Process")
    }
}

try {
    Start-Job -ScriptBlock {
        Start-Sleep -Seconds 5
        Start-Process "http://127.0.0.1:8000"
    } | Out-Null

    & $python -m uvicorn app:app --reload --host 127.0.0.1 --port 8000
}
catch {
    Write-Host ""
    Write-Host "Startup error:" -ForegroundColor Red
    Write-Host $_ -ForegroundColor Yellow
    Read-Host "Press Enter to close this window"
}
