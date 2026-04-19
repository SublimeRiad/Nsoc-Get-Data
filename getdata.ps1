# --- API Configuration ---
$apiBaseUrl    = "https://nsoc.aiootech.com/apirest.php"
$appToken      = "ig5tWvB2NK5DkEacnySyiNWTjqEHp0calKi7okq7"
$userToken     = "vGmLoJ74Rs1wlvN9u9zq4bwYnTeKLAeaOpHzdeD6"

# --- Execution Time ---
$executionTime = Get-Date -Format 'dd/MM/yyyy HH:mm'
Write-Host "Script Execution Date : $executionTime"

# --- PowerShell Script to run Python and get output ---
$pythonScriptPath = "C:\Dataupdate\get_data_usage.py"

try {
    Write-Host "...Retrieving data via Python..."
    
    $jsonString = python.exe $pythonScriptPath
    
    if ([string]::IsNullOrEmpty($jsonString)) {
        Write-Error "No JSON output received from Python script."
        return
    }

    $dataObject = $jsonString | ConvertFrom-Json
    
    if ($dataObject.error) {
        Write-Error "Error detected in Python output. Message: $($dataObject.message)"
        return
    }
    
    if (-not $dataObject -or (-not $dataObject.hostname)) {
        Write-Error "Failed to convert output to JSON or incomplete data received."
        return
    }

    # --- Display retrieved values ---
    Write-Host ""
    Write-Host "--- Data Retrieved ---"
    Write-Host "Hostname    : $($dataObject.hostname)"
    Write-Host "Phone       : $($dataObject.msisdn)"
    Write-Host "Total       : $($dataObject.total_gb) GB"
    Write-Host "Used        : $($dataObject.used_gb) GB"
    Write-Host "Remaining   : $($dataObject.left_gb) GB"
    Write-Host "Percentage  : $($dataObject.data_percent) %"
    Write-Host "----------------------------------------"

} catch {
    Write-Error "An unexpected error occurred during the Python call: $_"
    exit
}

# --- Step 1: Session Token Initiation ---
Write-Host "Step 1: Session Token Initiation"
try {
    $initSessionUri = "$apiBaseUrl/initSession"
    $initHeaders = @{
        "App-Token"     = $appToken
        "Authorization" = "user_token $userToken"
    }

    $sessionResponse = Invoke-RestMethod -Uri $initSessionUri -Headers $initHeaders -Method Get
    $sessionToken = $sessionResponse.session_token

    if ([string]::IsNullOrEmpty($sessionToken)) {
        throw "Could not retrieve Session Token. Check your API tokens."
    }

    Write-Host "Session Token: $sessionToken"

} catch {
    Write-Error "Error during session initialization: $($_.Exception.Message)"
    exit
}

# --- Header Definition for subsequent requests ---
$headers = @{
    "App-Token"     = $appToken
    "Session-Token" = $sessionToken
    "Content-Type"  = "application/json"
}

# --- Step 2: Find the Computer ID in GLPI ---
$currentHostname = [System.Net.Dns]::GetHostName()

try {
    Write-Host "Searching for GLPI ID for Hostname: $currentHostname"

    $uriWithFilter = "$apiBaseUrl/search/Computer?forcedisplay[]=2&criteria[0][field]=1&criteria[0][searchtype]=contains&criteria[0][value]=$currentHostname"
    $apiResponse = Invoke-RestMethod -Uri $uriWithFilter -Headers $headers -Method Get

    if ($apiResponse.data -and $apiResponse.data.Count -gt 0) {
        $computerId = $apiResponse.data[0].'2'
        Write-Host "GLPI ID found: $computerId"
    } else {
        Write-Error "No computer found in GLPI with hostname: $currentHostname"
        exit
    }
} catch {
    Write-Error "Error during computer search: $_"
    exit
}

# --- Step 3: Search and update Custom Fields ---
Write-Host "Checking for existing custom fields entry for PC ID $computerId..."

try {
    # Request the API to filter directly by items_id to avoid scanning thousands of rows
    $searchUri = "$apiBaseUrl/PluginFieldsComputerdata/?searchText[items_id]=$computerId"
    $pluginResponse = Invoke-RestMethod -Uri $searchUri -Headers $headers -Method Get
    
    $targetEntry = $null
    if ($pluginResponse.Count -gt 0) {
        $targetEntry = $pluginResponse[0]
    }

    if ($null -ne $targetEntry -and $null -ne $targetEntry.id) {
        # --- CASE 1: UPDATE ---
        $objectId = $targetEntry.id
        Write-Host "Existing entry found (Object ID: $objectId). Updating..."

        $putUri = "$apiBaseUrl/PluginFieldsComputerdata/$objectId"
        $updatePayload = @{
            input = @{
                id                 = $objectId
                items_id           = [int]$computerId
                phonenumberfield   = "$($dataObject.msisdn) "
                totaldatafield     = "$($dataObject.total_gb) Gb"
                dataleftfield      = "$($dataObject.left_gb) Gb"
                datausedfield      = "$($dataObject.used_gb) Gb"
                percentfield       = "$($dataObject.data_percent) %"
                executiontimefield = "$executionTime"
            }
        } | ConvertTo-Json

        $updateResponse = Invoke-RestMethod -Uri $putUri -Headers $headers -Method Put -Body $updatePayload
        Write-Host "Update completed successfully!"

    } else {
        # --- CASE 2: ADD ---
        Write-Warning "No entry found for items_id $computerId. Creating new row..."
        
        $postUri = "$apiBaseUrl/PluginFieldsComputerdata"
        $createPayload = @{
            input = @{
                items_id                    = [int]$computerId
                itemtype                    = "Computer"
                plugin_fields_containers_id = 12
                entities_id                 = 0
                phonenumberfield            = "$($dataObject.msisdn)"
                totaldatafield              = "$($dataObject.total_gb) Gb"
                dataleftfield               = "$($dataObject.left_gb) Gb"
                datausedfield               = "$($dataObject.used_gb) Gb"
                percentfield                = "$($dataObject.data_percent) %"
                executiontimefield          = "$executionTime"
            }
        } | ConvertTo-Json

        $createResponse = Invoke-RestMethod -Uri $postUri -Headers $headers -Method Post -Body $createPayload
        Write-Host "New entry added successfully!"
    }
}
catch {
    Write-Error "An error occurred while communicating with the Fields plugin."
    Write-Error $_.Exception.Message
}

# --- Final Step: Kill Session ---
try {
    Invoke-RestMethod -Uri "$apiBaseUrl/killSession" -Headers $headers -Method Get
    Write-Host "Session closed."
} catch {
    # Ignore if kill session fails
}
