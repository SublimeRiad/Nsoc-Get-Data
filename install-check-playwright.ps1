# NSOC Data Usage Collector - Playwright/Chromium Installation Check & Runner
# Installs in C:\ProgramData\ms-playwright so SYSTEM deploy and user runs both work
# Usage: powershell -ExecutionPolicy Bypass -File install-check-playwright.ps1

Write-Host "======================================"
Write-Host "NSOC - Playwright/Chromium Setup & Run"
Write-Host "======================================"
Write-Host ""

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$GetDataScript = Join-Path $ScriptDir "getdata.ps1"

# Set Chromium path to shared location
$env:PLAYWRIGHT_BROWSERS_PATH = "C:\ProgramData\ms-playwright"
[Environment]::SetEnvironmentVariable("PLAYWRIGHT_BROWSERS_PATH", "C:\ProgramData\ms-playwright", "Machine")

# ── 1. Check Python ──
$python = Get-Command python.exe -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Error "Python not found! Install Python 3.8+ first."
    pause
    exit 1
}
Write-Host "[OK] Python found: $($python.Source)"

# ── 2. Check if Playwright is installed ──
$playwrightInstalled = $false
try {
    $check = python -c "import playwright; print('OK')" 2>&1
    if ($check -match "OK") {
        $playwrightInstalled = $true
    }
} catch {}

# ── 3. Check if Chromium is installed in ProgramData ──
$chromiumInstalled = $false
$chromiumPath = "C:\ProgramData\ms-playwright"
if (Test-Path $chromiumPath) {
    $chromiumDirs = Get-ChildItem -Path $chromiumPath -Directory -ErrorAction SilentlyContinue
    if ($chromiumDirs -and $chromiumDirs.Count -gt 0) {
        $chromiumInstalled = $true
    }
}
# Also check via Playwright dry-run
if (-not $chromiumInstalled -and $playwrightInstalled) {
    try {
        $check = python -m playwright install --dry-run chromium 2>&1
        if ($check -match "already" -or $check -match "skip") {
            $chromiumInstalled = $true
        }
    } catch {}
}

# ── 4. Install what's missing ──
if (-not $playwrightInstalled) {
    Write-Host "[...] Installing Playwright package..."
    pip install playwright
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to install Playwright!"
        pause
        exit 1
    }
    $playwrightInstalled = $true
    Write-Host "[OK] Playwright installed!"
} else {
    Write-Host "[OK] Playwright already installed"
}

if (-not $chromiumInstalled) {
    Write-Host "[...] Installing Chromium browser for Playwright (~150 MB)..."
    Write-Host "      Target: $chromiumPath"
    Write-Host "      This may take a few minutes..."
    
    # Ensure target directory exists
    if (-not (Test-Path $chromiumPath)) {
        New-Item -ItemType Directory -Path $chromiumPath -Force | Out-Null
    }
    
    python -m playwright install chromium
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to install Chromium!"
        pause
        exit 1
    }
    $chromiumInstalled = $true
    Write-Host "[OK] Chromium installed in $chromiumPath"
    
    # Set env variable permanently
    [Environment]::SetEnvironmentVariable("PLAYWRIGHT_BROWSERS_PATH", $chromiumPath, "Machine")
} else {
    Write-Host "[OK] Chromium already installed in $chromiumPath"
}

# ── 5. Run getdata.ps1 ──
Write-Host ""
Write-Host "======================================"
Write-Host "All dependencies OK. Running getdata.ps1..."
Write-Host "======================================"
Write-Host ""

if (Test-Path $GetDataScript) {
    & $GetDataScript @args
} else {
    Write-Error "getdata.ps1 not found at: $GetDataScript"
    pause
    exit 1
}
