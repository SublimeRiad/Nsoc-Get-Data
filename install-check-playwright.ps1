# NSOC Data Usage Collector - Playwright/Chromium Installation Check & Runner
# Checks if Playwright + Chromium are installed, installs if missing, then runs getdata.ps1
# Usage: powershell -ExecutionPolicy Bypass -File install-check-playwright.ps1

Write-Host "======================================"
Write-Host "NSOC - Playwright/Chromium Setup & Run"
Write-Host "======================================"
Write-Host ""

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$GetDataScript = Join-Path $ScriptDir "getdata.ps1"

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

# ── 3. Check if Chromium is installed for Playwright ──
$chromiumInstalled = $false
if ($playwrightInstalled) {
    try {
        $check = python -c "from playwright.sync_api import sync_playwright; exec('import os; print(os.path.exists(os.path.join(os.path.dirname(sync_playwright.__file__), \"driver\", \"node_modules\", \"playwright-core\", \".browsers\")))')" 2>&1
        $check2 = python -m playwright install --dry-run chromium 2>&1
        if ($check2 -match "already installed" -or $check2 -match "is up to date" -or $check2 -match "browsers are already installed") {
            $chromiumInstalled = $true
        }
        # Alternative: try to actually check via cache path
        $check3 = python -c "
try:
    from playwright.sync_api import sync_playwright
    import subprocess, json, os
    result = subprocess.run(['python', '-m', 'playwright', 'install', '--dry-run', 'chromium'], capture_output=True, text=True, timeout=15)
    if 'already' in result.stdout.lower() or 'skip' in result.stdout.lower():
        print('INSTALLED')
    else:
        # Check browsers path directly
        try:
            from playwright._impl._driver import compute_driver_executable
            p = os.path.expanduser('~/.cache/ms-playwright')
            if os.path.exists(p) and len(os.listdir(p)) > 0:
                print('INSTALLED')
            else:
                print('NOT_INSTALLED')
        except:
            print('NOT_INSTALLED')
except Exception as e:
    print(f'ERROR: {e}')
" 2>&1
        if ($check3 -match "INSTALLED") {
            $chromiumInstalled = $true
        }
    } catch {
        $chromiumInstalled = $false
    }
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
    Write-Host "      This may take a few minutes..."
    python -m playwright install chromium
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to install Chromium!"
        pause
        exit 1
    }
    $chromiumInstalled = $true
    Write-Host "[OK] Chromium installed!"
} else {
    Write-Host "[OK] Chromium already installed"
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
