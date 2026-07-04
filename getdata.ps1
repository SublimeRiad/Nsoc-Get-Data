# NSOC Data Usage Collector — PowerShell launcher
# Usage: powershell -ExecutionPolicy Bypass -File getdata.ps1
Write-Host "NSOC Data Usage Collector"
Write-Host "========================="
Write-Host ""

# Path to Python script
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PyScript = Join-Path $ScriptDir "get_data_usage.py"

# Check Python
$python = Get-Command python.exe -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Error "Python not found. Install Python 3.8+ first."
    exit 1
}

# Run the script
Write-Host "Running data collection..."
python.exe $PyScript --silent

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Data collection complete"
} else {
    Write-Error "✗ Script failed with exit code $LASTEXITCODE"
}

# For testing: run with verbose output
if ($args -contains "-verbose") {
    python.exe $PyScript
}
