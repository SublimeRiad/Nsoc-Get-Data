# --- Configuration de l'API ---
$apiBaseUrl = "https://nsoc.aiootech.com/apirest.php"
# WARNING: Replace with your actual tokens or use a secure management method
$appToken   = "ig5tWvB2NK5DkEacnySyiNWTjqEHp0calKi7okq7"
$userToken  = "vGmLoJ74Rs1wlvN9u9zq4bwYnTeKLAeaOpHzdeD6"

# GLPI Constants verified:
$computerLiveScreensPluginFieldContainerId = 15 
$targetGlpiField = "livescreenfield" 
$executionTimeField = "executiontimefieldtwo"

# --- Path Configuration ---
$pythonScriptPath = Join-Path -Path $PSScriptRoot -ChildPath "screeneye.py" 
# ---

Write-Host "Script Execution Date: (Determined by Python)"

# --- Prerequisites: Install Python and Dependencies ---
$requiredPackages = @("mss", "opencv-python", "numpy", "Pillow")
$pythonExecutable = "python.exe"

function Install-PythonDependencies {
    param(
        [Parameter(Mandatory=$true)]
        [string[]]$Packages
    )
    Write-Host "...Checking for Python and Pip installation..."
    
    try {
        & $pythonExecutable --version | Out-Null
    } catch {
        Write-Error "Python not found. Please install it and ensure it's accessible via the PATH environment variable."
        exit 1
    }

    Write-Host "...Installing or updating Python dependencies..."
    foreach ($pkg in $Packages) {
        Write-Host "Installing $pkg..."
        try {
            & $pythonExecutable -m pip install $pkg | Out-Null
        } catch {
            Write-Error "Failed to install dependency '$pkg': $($_.Exception.Message)"
        }
    }
}

Install-PythonDependencies -Packages $requiredPackages

# --- Execute Python Script and Capture Raw JSON String ---

$fullJsonOutput = $null
try {
    Write-Host "...Executing screeneye.py and capturing JSON output..."
    $jsonString = & $pythonExecutable $pythonScriptPath
    $fullJsonOutput = $jsonString | Select-Object -Last 1
    
    if ([string]::IsNullOrEmpty($fullJsonOutput)) {
        Write-Error "No JSON output received from the Python script."
        return
    }

    $dataObject = $fullJsonOutput | ConvertFrom-Json
    
    # NOUVEAU: Extraction et formatage du timestamp en heure de DUBAÏ (UTC+4)
    $pythonTimestamp = $dataObject.timestamp
    $dateTimeObj = [datetime]::Parse($pythonTimestamp)
    
    # Conversion en heure de Dubaï (UTC+4)
    $dubaiTime = $dateTimeObj.ToUniversalTime().AddHours(4)
    $executionTime = $dubaiTime.ToString('MM/dd/yyyy HH:mm') # Format d'insertion GLPI
    
    Write-Host "--- Screen Analysis Result ---"
    Write-Host "Extracted Status: $($dataObject.status)"
    Write-Host "Python Timestamp (Dubai Time): $executionTime" # Affichage de l'heure ajustée

} catch {
    Write-Error "An unexpected error occurred during Python execution: $_"
    return
}

# --- Step 1: Session-Token Initiation ---
Write-Host "Step 1: Session-Token Initiation"

try {
    $initSessionUri = "$apiBaseUrl/initSession"
    $initHeaders = @{
        "App-Token"     = $appToken
        "Authorization" = "user_token $userToken"
    }
    $sessionResponse = Invoke-RestMethod -Uri $initSessionUri -Headers $initHeaders -Method Get
    $sessionToken = $sessionResponse.session_token
    if ([string]::IsNullOrEmpty($sessionToken)) {
        throw "Failed to retrieve Session-Token."
    }
    Write-Host "Session-Token retrieved."
} catch {
    Write-Error "Error during session initialization: $($_.Exception.Message)"
    exit
}

# --- Header Definition ---
$headers = @{
    "App-Token"     = $appToken
    "Session-Token" = $sessionToken
    "Content-Type"  = "application/json"
}

# --- Step 2: Retrieve the GLPI Computer ID ---
$currentHostname = $env:COMPUTERNAME
$computerId = $null
try {
    Write-Host "Step 2: Searching for the Computer ID for hostname: $currentHostname"
    $uriWithFilter = "$apiBaseUrl/search/Computer?forcedisplay[]=2&criteria[0][field]=1&criteria[0][searchtype]=contains&criteria[0][value]=$currentHostname"
    $apiResponse = Invoke-RestMethod -Uri $uriWithFilter -Headers $headers -Method Get

    if ($apiResponse.data -and $apiResponse.data.Count -gt 0) {
        $computerId = $apiResponse.data[0].'2' 
        if ($null -ne $computerId) {
            Write-Host "Computer ID found: $computerId"
        } else {
            Write-Error "The 'ID' property was not found in the API response."
            exit
        }
    } else {
        Write-Error "No computer found with hostname: $currentHostname"
        exit
    }
} catch {
    Write-Error "An error occurred during the API request for the Computer ID: $_"
    exit
}

# --- Step 3: Search (GET simple) then Update (PATCH) or Create (POST) ---
Write-Host "Step 3: Searching for existing entry by simple GET then PATCH or POST..."

# Échapper le JSON pour l'insérer comme VALEUR de chaîne dans le Payload GLPI
$escapedJson = $fullJsonOutput -replace '"', '\"'

try {
    $pluginTableName = "PluginFieldsComputerlivescreen" 
    $postUri = "$apiBaseUrl/$pluginTableName"
    
    # RECHERCHE ROBUSTE (GET simple + filtre PowerShell)
    Write-Host "🔍 Attempting simple GET: $apiBaseUrl/$pluginTableName"
    $apiResponse = Invoke-RestMethod -Uri "$apiBaseUrl/$pluginTableName" -Headers $headers -Method Get
    
    # Filtrer les résultats par items_id côté PowerShell
    $targetObject = $apiResponse | Where-Object { $_.items_id -eq $computerId}
    
    $objectId = $null
    
    if ($null -ne $targetObject) {
        # Objet trouvé: On passe en mode PATCH
        $objectId = $targetObject.id
    }

    # --- AFFICHAGE DE DÉBOGAGE ---
    if ($null -ne $objectId) {
        Write-Host "🔍 Found Plugin Object ID (objectId): $objectId"
        Write-Host "--- Attempting PATCH (Update existing entry) ---"
    } else {
        Write-Warning "🔍 Found Plugin Object ID (objectId): NULL. Will attempt POST (Create new entry)."
    }
    # ----------------------------

    if ($null -ne $objectId) {
        # --- Update (PATCH) ---
        $putUri = "$apiBaseUrl/$pluginTableName/$objectId"
        
        $updatePayload = @"
{
    "input": {
        "id": $objectId,
        "items_id": $computerId,
        "itemtype": "Computer",
        "plugin_fields_containers_id": $computerLiveScreensPluginFieldContainerId,
        "$targetGlpiField": "$escapedJson",
        "$executionTimeField": "$executionTime"
    }
}
"@
        $updateResponse = Invoke-RestMethod -Uri $putUri -Headers $headers -Method Patch -Body $updatePayload -ContentType 'application/json'

        Write-Host "✅ Update (PATCH) completed successfully!"
    } else {
        # --- Create (POST) ---
        
        $CreatePayload = @"
{
    "input": {
        "items_id": $computerId,
        "itemtype": "Computer",
        "plugin_fields_containers_id": $computerLiveScreensPluginFieldContainerId,
        "entities_id": 0,
        "$targetGlpiField": "$escapedJson",
        "$executionTimeField": "$executionTime"
    }
}
"@
        $createResponse = Invoke-RestMethod -Uri $postUri -Headers $headers -Method Post -Body $CreatePayload -ContentType 'application/json'

        Write-Host "✅ New entry added successfully (POST)!"
    }
}
catch {
    Write-Error "An error occurred while communicating with the GLPI API (Step 3)."
    Write-Error "The error likely occurred during the simple GET request, possibly due to reading rights."
    Write-Error $_.Exception.Message
}
