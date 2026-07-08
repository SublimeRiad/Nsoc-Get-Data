# NSOC Data Usage Collector — PowerShell launcher
# Usage: powershell -ExecutionPolicy Bypass -File getdata.ps1 [-verbose]
param([switch]$verbose)

Write-Host "NSOC Data Usage Collector"
Write-Host "========================="
Write-Host ""

# Set Chromium path for Playwright (shared install)
$env:PLAYWRIGHT_BROWSERS_PATH = "C:\ProgramData\ms-playwright"

# Path to Python script
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PyScript = Join-Path $ScriptDir "get_data_usage.py"

# Find Python: try user AppData first (SYSTEM runs don't have user PATH), then PATH
$python = $null
$userPythonDirs = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python" -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending
foreach ($dir in $userPythonDirs) {
    $candidate = Join-Path $dir.FullName "python.exe"
    if (Test-Path $candidate) {
        $python = $candidate
        break
    }
}
if (-not $python) {
    # Fallback: also check ALLUSERS profile
    $allUsersPython = Get-ChildItem "$env:ALLUSERSPROFILE\chocolatey\lib\python*" -Directory -ErrorAction SilentlyContinue
    foreach ($dir in $allUsersPython) {
        $candidate = Join-Path $dir.FullName "tools\python.exe"
        if (Test-Path $candidate) {
            $python = $candidate
            break
        }
    }
}
# Final fallback: try PATH
if (-not $python) {
    $pathPython = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pathPython) {
        $python = $pathPython.Source
    }
}

if (-not $python) {
    Write-Error "Python not found. Install Python 3.8+ first."
    exit 1
}

Write-Host "Using Python: $python"

# Run the script
if ($verbose) {
    Write-Host "Running in verbose mode..."
    & $python $PyScript
} else {
    Write-Host "Running data collection..."
    & $python $PyScript --silent
}

if ($LASTEXITCODE -eq 0) {
    Write-Host " Done - data collection complete"
} else {
    Write-Error "Script failed with exit code $LASTEXITCODE"
    
    # Check if it's a Playwright/Chromium issue and write comment to GLPI
    $hostname = $env:COMPUTERNAME
    Write-Host "Attempting to write 'Need Playwright and Chromium' comment to GLPI for $hostname..."
    
    $tokenBody = @{
        "App-Token" = "ig5tWvB2NK5DkEacnySyiNWTjqEHp0calKi7okq7"
        "Authorization" = "user_token vGmLoJ74Rs1wlvN9u9zq4bwYnTeKLAeaOpHzdeD6"
    }
    
    try {
        # 1. Init GLPI session
        $init = Invoke-RestMethod -Uri "https://nsoc.aiootech.com/apirest.php/initSession" -Headers $tokenBody -Method Get
        $sessionToken = $init.session_token
        
        $headers = @{
            "App-Token" = "ig5tWvB2NK5DkEacnySyiNWTjqEHp0calKi7okq7"
            "Session-Token" = $sessionToken
            "Content-Type" = "application/json"
        }
        
        # 2. Search computer by hostname
        $searchUrl = "https://nsoc.aiootech.com/apirest.php/search/Computer?expand_dropdowns=true&range=0-20&criteria[0][field]=1&criteria[0][searchtype]=contains&criteria[0][value]=$hostname&forcedisplay[0]=1&forcedisplay[1]=2"
        $searchResult = Invoke-RestMethod -Uri $searchUrl -Headers $headers -Method Get
        
        $computerId = $null
        if ($searchResult.data -and $searchResult.data.Count -gt 0) {
            foreach ($pc in $searchResult.data) {
                if ($pc."1" -eq $hostname) {
                    $computerId = $pc."2"
                    break
                }
            }
            if (-not $computerId) {
                $computerId = $searchResult.data[0]."2"
            }
        }
        
        if (-not $computerId) {
            Write-Error "Could not find $hostname in GLPI"
            exit 1
        }
        
        Write-Host "Found computer ID: $computerId"
        
        # 3. Search existing plugin entries for this computer
        $existingUrl = "https://nsoc.aiootech.com/apirest.php/PluginFieldsComputerdata?range=0-200"
        $existingResult = Invoke-RestMethod -Uri $existingUrl -Headers $headers -Method Get
        $entriesToDelete = @()
        if ($existingResult -is [array]) {
            foreach ($entry in $existingResult) {
                $entryItemsId = if ($entry.items_id) { $entry.items_id } elseif ($entry."2") { $entry."2" } else { $entry."1" }
                if ($entryItemsId -eq $computerId) {
                    $entryId = if ($entry.id) { $entry.id } else { $entry."3" }
                    $entriesToDelete += $entryId
                }
            }
        }
        
        # 4. Delete existing entries
        foreach ($entryId in $entriesToDelete) {
            Write-Host "Deleting old entry #$entryId..."
            Invoke-RestMethod -Uri "https://nsoc.aiootech.com/apirest.php/PluginFieldsComputerdata/$entryId" -Headers $headers -Method Delete | Out-Null
        }
        
        # 5. Create new entry with comment
        $now = (Get-Date).ToString("MM/dd/yyyy HH:mm")
        $body = @{
            "input" = @(
                @{
                    "items_id" = $computerId
                    "itemtype" = "Computer"
                    "plugin_fields_containers_id" = 12
                    "entities_id" = 0
                    "phonenumberfield" = ""
                    "totaldatafield" = "0 Gb"
                    "datausedfield" = "0 Gb"
                    "dataleftfield" = "0 Gb"
                    "percentfield" = "0 %"
                    "executiontimefield" = $now
                    "commentfield" = "Need Playwright and Chromium"
                }
            )
        } | ConvertTo-Json -Depth 10
        
        Invoke-RestMethod -Uri "https://nsoc.aiootech.com/apirest.php/PluginFieldsComputerdata" -Headers $headers -Method Post -Body $body
        Write-Host " Comment 'Need Playwright and Chromium' written to GLPI for $hostname"
        
    } catch {
        Write-Error "Failed to write GLPI comment: $_"
    }
    
    exit $LASTEXITCODE
}
