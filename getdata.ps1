# --- Configuration de l'API ---
$apiBaseUrl    = "https://nsoc.aiootech.com/apirest.php"
$appToken      = "ig5tWvB2NK5DkEacnySyiNWTjqEHp0calKi7okq7"
$userToken     = "vGmLoJ74Rs1wlvN9u9zq4bwYnTeKLAeaOpHzdeD6"

Write-Host 
"Script Execution Date : $executionTime"

# --- PowerShell Script to run Python and get output ---
$pythonScriptPath = "C:\Program Files\GLPI-Agent\get_data_usage.py"

try {
    Write-Host "...Python..."
    
    $jsonString = python.exe $pythonScriptPath
    
    if ([string]::IsNullOrEmpty($jsonString)) {
        Write-Error "Aucune sortie JSON reÃ§ue du script Python."
        return
    }

    $dataObject = $jsonString | ConvertFrom-Json
    
    if ($dataObject.error) {
        Write-Error "Erreur dÃ©tectÃ©e dans la sortie Python. Message : $($dataObject.message)"
        return
    }
    
    if (-not $dataObject -or (-not $dataObject.hostname)) {
        Write-Error "Impossible de convertir la sortie en JSON ou donnÃ©es incomplÃ¨tes."
        return
    }

    # --- Use the values ---
    Write-Host ""
    Write-Host "--- Data ---"
    Write-Host "Nom d'hÃ´te  : $($dataObject.hostname)"
    Write-Host "Phone      : $($dataObject.msisdn)"
    Write-Host "Total       : $($dataObject.total_gb) GB"
    Write-Host "UtilisÃ©     : $($dataObject.used_gb) GB"
    Write-Host "Restant     : $($dataObject.left_gb) GB"
    Write-Host "Pourcentage : $($dataObject.data_percent) %"
    Write-Host "----------------------------------------"

} catch {
    Write-Error "Une erreur inattendue est survenue : $_"
}

# --- DonnÃ©es Ã  mettre Ã  jour ---
Write-Host "Ã‰tape 1 : Session-Token Initiation"
$executionTime = Get-Date -Format 'dd/MM/yyyy HH:mm'

try {
    $initSessionUri = "$apiBaseUrl/initSession"
    $initHeaders = @{
        "App-Token"     = $appToken
        "Authorization" = "user_token $userToken"
    }

    $sessionResponse = Invoke-RestMethod -Uri $initSessionUri -Headers $initHeaders -Method Get
    $sessionToken = $sessionResponse.session_token

    if ([string]::IsNullOrEmpty($sessionToken)) {
        throw "Le Session-Token n'a pas pu Ãªtre rÃ©cupÃ©rÃ©. VÃ©rifie tes jetons d'API."
    }

    Write-Host "Session-Token : $sessionToken"

} catch {
    Write-Error "Erreur lors de l'initialisation de la session : $($_.Exception.Message)"
    exit
}

# --- Header Definition ---
$headers = @{
    "App-Token"     = $appToken
    "Session-Token" = $sessionToken
    "Content-Type"  = "application/json"
}

# --- Get the local computer's hostname ---
$currentHostname = $env:COMPUTERNAME

try {
    Write-Host "Searching for the computer ID for hostname: $currentHostname"

    $uriWithFilter = "$apiBaseUrl/search/Computer?forcedisplay[]=2&criteria[0][field]=1&criteria[0][searchtype]=contains&criteria[0][value]=$currentHostname"
    $apiResponse = Invoke-RestMethod -Uri $uriWithFilter -Headers $headers -Method Get

    if ($apiResponse.data -and $apiResponse.data.Count -gt 0) {
        $computerData = $apiResponse.data[0]
        $computerId = $computerData.'2'
        
        if ($null -ne $computerId) {
            Write-Host "Computer ID found for hostname '$currentHostname'."
            Write-Host "ID: $computerId"
        } else {
            Write-Error "The 'ID' property was not found in the API response."
        }
    } else {
        Write-Error "No computer found with hostname: $currentHostname"
        exit
    }
} catch {
    Write-Error "An error occurred during the API request: $_"
    exit
}

Write-Host "Searching for the object ID for PC $computerId..."

# --- Step 1: Get all entries and find the object's ID ---
try {
    $apiResponse = Invoke-RestMethod -Uri "$apiBaseUrl/PluginFieldsComputerdata" -Headers $headers -Method Get
    $targetObject = $apiResponse | Where-Object { $_.items_id -eq $computerId}
    
    $putUri = "$apiBaseUrl/PluginFieldsComputerdata/$objectId"
    $postUri = "$apiBaseUrl/PluginFieldsComputerdata"

    if ($null -ne $targetObject) {
        $objectId = $targetObject.id
        Write-Host "The found object ID is: $objectId"
        Write-Host "Updating fields for object ID $objectId..."

        $putUri = "$apiBaseUrl/PluginFieldsComputerdata/$objectId"
        $updatePayload = @"
{
    "input": {
        "id": $objectId,
        "items_id": $computerId,
        "phonenumberfield": "$($dataObject.msisdn) ",
        "totaldatafield": "$($dataObject.total_gb) Gb",
        "dataleftfield": "$($dataObject.left_gb) Gb",
        "datausedfield": "$($dataObject.used_gb) Gb",
        "percentfield": "$($dataObject.data_percent) %",
        "executiontimefield": "$executionTime"
    }
}
"@
        Write-Host "Generated Payload for update:"
        Write-Host $updatePayload
        $updateResponse = Invoke-RestMethod -Uri $putUri -Headers $headers -Method Patch -Body $updatePayload

        Write-Host "Update completed successfully!"
    } else {
        Write-Warning "No object matching items_id $computerId was found. We will add a new one."
        
        $CreatePayload = @"
{
    "input": {
        "items_id": $computerId,
        "itemtype": "Computer",
        "plugin_fields_containers_id": 12,
        "entities_id": 0,
        "phonenumberfield": "$($dataObject.msisdn)",
        "totaldatafield": "$($dataObject.total_gb) Gb",
        "dataleftfield": "$($dataObject.left_gb) Gb",
        "datausedfield": "$($dataObject.used_gb) Gb",
        "percentfield": "$($dataObject.data_percent) %",
        "executiontimefield": "$executionTime"
    }
}
"@
        Write-Host "Generated Payload for creation:"
        Write-Host $CreatePayload
        $createResponse = Invoke-RestMethod -Uri $postUri -Headers $headers -Method Post -Body $CreatePayload

        Write-Host "New entry added successfully!"
    }
}
catch {
    Write-Error "An error occurred while communicating with the GLPI API."
    Write-Error $_.Exception.Message
}
