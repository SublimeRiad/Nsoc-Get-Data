# --- Configuration de l'API ---
$apiBaseUrl    = "https://nsoc.aiootech.com/apirest.php"
$appToken      = "ig5tWvB2NK5DkEacnySyiNWTjqEHp0calKi7okq7"    # Remplace par ton jeton d'application GLPI
$userToken     = "vGmLoJ74Rs1wlvN9u9zq4bwYnTeKLAeaOpHzdeD6"   # Remplace par ton jeton d'utilisateur GLPI
#$itemsIdToFind = 243                 # L'ID du PC à mettre à jour


Write-Host 
"Script Execution Date : $executionTime"




# --- PowerShell Script to run Python and get output ---

# Set the correct path to your Python script
$pythonScriptPath = "get_data_usage.py"

try {
    Write-Host "...Python..."
    
    # Execute the Python script and capture only the standard output
    $jsonString = python.exe $pythonScriptPath
    
    # Check if the output is empty
    if ([string]::IsNullOrEmpty($jsonString)) {
        Write-Error "Aucune sortie JSON reçue du script Python."
        return
    }

    # Convert the JSON string to a PowerShell object
    $dataObject = $jsonString | ConvertFrom-Json
    
    # Check for an error message from the Python script
    if ($dataObject.error) {
        Write-Error "Erreur détectée dans la sortie Python. Message : $($dataObject.message)"
        return
    }
    
    # Check if the object was created correctly
    if (-not $dataObject -or (-not $dataObject.hostname)) {
        Write-Error "Impossible de convertir la sortie en JSON ou données incomplètes."
        return
    }


    # --- Use the values ---
    Write-Host ""
    Write-Host "--- Data ---"
    Write-Host "Nom d'hôte  : $($dataObject.hostname)"
    Write-Host "Phone      : $($dataObject.msisdn)"
    Write-Host "Total       : $($dataObject.total_gb) GB"
    Write-Host "Utilisé     : $($dataObject.used_gb) GB"
    Write-Host "Restant     : $($dataObject.left_gb) GB"
    Write-Host "Pourcentage : $($dataObject.data_percent) %"
    Write-Host "----------------------------------------"

}
catch {
    Write-Error "Une erreur inattendue est survenue : $_"
}


# --- Données à mettre à jour ---
# Remplace les noms de champs et les valeurs par ceux que tu veux modifier

Write-Host "Étape 1 : Session-Token Initiation"
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
        throw "Le Session-Token n'a pas pu être récupéré. Vérifie tes jetons d'API."
    }

    Write-Host "Session-Token : $sessionToken"

} catch {
    Write-Error "Erreur lors de l'initialisation de la session : $($_.Exception.Message)"
    exit
}

# --- Header Definition ---
$headers = @{
    "App-Token"   = $appToken
    "Session-Token" = $sessionToken
    "Content-Type" = "application/json"
}



# --- Get the local computer's hostname ---
$currentHostname = $env:COMPUTERNAME

try {
    Write-Host "Searching for the computer ID for hostname: $currentHostname"

    # The 'listSearchOptions' JSON indicates:
    # 'Name' field has ID 1
    # 'ID' field has ID 2
    # We use the 'criteria' parameter for a targeted search.
    
    # 1. Build the API URI with the correct search criteria.
    # The URL requests the 'ID' field ('2') to be displayed,
    # and filters by the 'Name' field ('1') being equal to the current hostname.
    $uriWithFilter = "$apiBaseUrl/search/Computer?forcedisplay[]=2&criteria[0][field]=1&criteria[0][searchtype]=contains&criteria[0][value]=$currentHostname"

    # 2. Perform the GET request to the GLPI API.
    $apiResponse = Invoke-RestMethod -Uri $uriWithFilter -Headers $headers -Method Get

    # 3. Check if the 'data' property exists and is not empty.
    if ($apiResponse.data -and $apiResponse.data.Count -gt 0) {
        # The search result is an array. We take the first item.
        $computerData = $apiResponse.data[0]
        
        # The ID is returned with its search ID '2' as the property name.
        $computerId = $computerData.'2'
        
        if ($null -ne $computerId) {
            Write-Host "Computer ID found for hostname '$currentHostname'."
            Write-Host "ID: $computerId"

            # You can now use the $computerId variable.
            # $itemsIdToUpdate = $computerId
        } else {
            Write-Error "The 'ID' property was not found in the API response. Full response:`n$($apiResponse | ConvertTo-Json -Depth 5)"
        }
    } else {
        Write-Error "No computer found with hostname: $currentHostname"
    }

} catch {
    Write-Error "An error occurred during the API request: $_"
    # To see the full response content for debugging, you can use this:
    # Write-Error "Response details: $($_.Exception.Response.Content)"
}


Write-Host "Searching for the object ID for PC "$computerId"..."

# --- Step 1: Get all entries and find the object's ID ---
try {
    # Perform a GET request to retrieve all plugin data
    $apiResponse = Invoke-RestMethod -Uri "$apiBaseUrl/PluginFieldsComputerdata" -Headers $headers -Method Get

    # Use Where-Object to find the object with the correct items_id
    $targetObject = $apiResponse | Where-Object { $_.items_id -eq $computerId}

    # Check if a matching object was found
    if ($null -ne $targetObject) {
        $objectId = $targetObject.id
        Write-Host "The found object ID is: $objectId"

        # --- Step 2: Update the object via a PUT request ---
        Write-Host "Updating fields for object ID $objectId..."

        $putUri = "$apiBaseUrl/PluginFieldsComputerdata/$objectId"

        # Perform the Patch request for the update
$updatePayload = @"
{
    "input": 
        {
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

$CreatePayload = @"
{
    "input": 
        {
            "id": "",
            "itemtype": "Computer",
            "plugin_fields_containers_id": 12,
            "entities_id": 0,
            "phonenumberfield": "$($dataObject.msisdn) ",
            "totaldatafield": "$($dataObject.total_gb) Gb",
            "dataleftfield": "$($dataObject.left_gb) Gb",
            "datausedfield": "$($dataObject.used_gb) Gb",
            "percentfield": "$($dataObject.data_percent) %",
            "executiontimefield": "$executionTime"
        }
    }
"@

# You can now use $updatePayload in your API call.
Write-Host "Generated Payload:"
Write-Host $updatePayload

        $updateResponse = Invoke-RestMethod -Uri $putUri -Headers $headers -Method Patch -Body ($updatePayload)

        Write-Host "Update completed successfully!"
    } else {
        Write-Warning "No object matching items_id $computerId was found.we will add "
        $updateResponse = Invoke-RestMethod -Uri "$apiBaseUrl/PluginFieldsComputerdata" -Headers $headers -Method Post -Body ($CreatePayload)

        Write-Host "Added completed successfully!"
    }
}
catch {
    Write-Error "An error occurred while communicating with the GLPI API."
    Write-Error $_.Exception.Message
}
