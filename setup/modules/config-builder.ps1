# Configuration builder module
# Builds .env and swarm-stack.yml from templates

function New-EnvFile {
    param(
        [string]$DbType,
        [string]$DbMode,
        [string]$ProxyType,
        [string]$ProjectRoot
    )
    
    Write-Host "⚙️  Building .env file..."
    
    # Start with base template
    $envContent = Get-Content "$ProjectRoot\setup\env-templates\.env.base.template" -Raw
    
    # Add database configuration
    if ($DbType -eq "postgresql") {
        if ($DbMode -eq "local") {
            $envContent += Get-Content "$ProjectRoot\setup\env-templates\.env.postgres-local.template" -Raw
        } else {
            $envContent += Get-Content "$ProjectRoot\setup\env-templates\.env.postgres-external.template" -Raw
        }
    } elseif ($DbType -eq "neo4j") {
        if ($DbMode -eq "local") {
            $envContent += Get-Content "$ProjectRoot\setup\env-templates\.env.neo4j-local.template" -Raw
        } else {
            $envContent += Get-Content "$ProjectRoot\setup\env-templates\.env.neo4j-external.template" -Raw
        }
    }
    
    # Add proxy configuration
    if ($ProxyType -eq "traefik") {
        $envContent += Get-Content "$ProjectRoot\setup\env-templates\.env.proxy-traefik.template" -Raw
    } else {
        $envContent += Get-Content "$ProjectRoot\setup\env-templates\.env.proxy-none.template" -Raw
    }
    
    # Write to .env file
    Set-Content -Path "$ProjectRoot\.env" -Value $envContent -NoNewline
    
    Write-Host "✅ .env file created" -ForegroundColor Green
}

function New-StackFile {
    param(
        [string]$DbType,
        [string]$DbMode,
        [string]$ProxyType,
        [string]$ProjectRoot,
        [string]$SslMode = "direct"  # Default to direct SSL if not specified
    )
    
    Write-Host "⚙️  Building swarm-stack.yml..."
    
    # Start with base
    $stackContent = Get-Content "$ProjectRoot\setup\compose-modules\base.yml" -Raw
    
    # Build API service from template with snippet injection
    $tempApi = "$ProjectRoot\setup\compose-modules\api.temp.yml"
    Copy-Item "$ProjectRoot\setup\compose-modules\api.template.yml" $tempApi
    
    $apiContent = Get-Content $tempApi -Raw
    
    # Inject database environment snippet
    # Map postgresql -> postgres for file names
    $dbFileName = $DbType
    if ($DbType -eq "postgresql") {
        $dbFileName = "postgres"
    }
    
    $dbEnvSnippet = "$ProjectRoot\setup\compose-modules\snippets\db-${dbFileName}-${DbMode}.env.yml"
    if (Test-Path $dbEnvSnippet) {
        $dbEnvContent = Get-Content $dbEnvSnippet -Raw
        $apiContent = $apiContent -replace '###DATABASE_ENV###', $dbEnvContent
    } else {
        $apiContent = $apiContent -replace '###DATABASE_ENV###', ''
    }
    
    # Inject proxy network snippet (only for Traefik)
    if ($ProxyType -eq "traefik") {
        $proxyNetworkSnippet = "$ProjectRoot\setup\compose-modules\snippets\proxy-traefik.network.yml"
        if (Test-Path $proxyNetworkSnippet) {
            $proxyNetworkContent = Get-Content $proxyNetworkSnippet -Raw
            $apiContent = $apiContent -replace '###PROXY_NETWORK###', $proxyNetworkContent
        } else {
            $apiContent = $apiContent -replace '###PROXY_NETWORK###', ''
        }
    } else {
        $apiContent = $apiContent -replace '###PROXY_NETWORK###', ''
    }
    
    # Inject proxy configuration snippet
    if ($ProxyType -eq "traefik") {
        # Inject Traefik labels at ###PROXY_LABELS### based on SSL mode
        $proxyLabelsSnippet = "$ProjectRoot\setup\compose-modules\snippets\proxy-traefik-${SslMode}-ssl.labels.yml"
        if (Test-Path $proxyLabelsSnippet) {
            $proxyLabelsContent = Get-Content $proxyLabelsSnippet -Raw
            $apiContent = $apiContent -replace '###PROXY_LABELS###', $proxyLabelsContent
        } else {
            $apiContent = $apiContent -replace '###PROXY_LABELS###', ''
        }
        # Remove ###PROXY_PORTS### placeholder (not used for Traefik)
        $apiContent = $apiContent -replace '###PROXY_PORTS###', ''
    } else {
        # Inject ports at ###PROXY_PORTS###
        $proxyPortsSnippet = "$ProjectRoot\setup\compose-modules\snippets\proxy-none.ports.yml"
        if (Test-Path $proxyPortsSnippet) {
            $proxyPortsContent = Get-Content $proxyPortsSnippet -Raw
            $apiContent = $apiContent -replace '###PROXY_PORTS###', $proxyPortsContent
        } else {
            $apiContent = $apiContent -replace '###PROXY_PORTS###', ''
        }
        # Remove ###PROXY_LABELS### placeholder (not used for direct ports)
        $apiContent = $apiContent -replace '###PROXY_LABELS###', ''
    }
    
    # Append API service to stack
    $stackContent += $apiContent
    
    # Clean up temp file
    Remove-Item $tempApi -ErrorAction SilentlyContinue
    
    # Add database service if local deployment
    if ($DbMode -eq "local") {
        # Map postgresql -> postgres for file names
        $dbFileName = $DbType
        if ($DbType -eq "postgresql") {
            $dbFileName = "postgres"
        }
        $stackContent += Get-Content "$ProjectRoot\setup\compose-modules\${dbFileName}-local.yml" -Raw
    }
    
    # Add footer (networks and secrets)
    $stackContent += Get-Content "$ProjectRoot\setup\compose-modules\footer.yml" -Raw
    
    # Write to swarm-stack.yml file
    Set-Content -Path "$ProjectRoot\swarm-stack.yml" -Value $stackContent -NoNewline
    
    Write-Host "✅ swarm-stack.yml created" -ForegroundColor Green
}

function Update-EnvValue {
    param(
        [string]$EnvFile,
        [string]$Key,
        [string]$Value
    )
    
    $content = Get-Content $EnvFile
    $content = $content -replace "^${Key}=.*", "${Key}=${Value}"
    Set-Content -Path $EnvFile -Value $content
}

function Update-StackSecrets {
    param(
        [string]$StackFile,
        [string]$DbPasswordSecret,
        [string]$AdminApiKeySecret,
        [string]$BackupRestoreApiKeySecret,
        [string]$BackupDeleteApiKeySecret
    )
    
    $content = Get-Content $StackFile -Raw
    $content = $content -replace 'XXX_CHANGE_ME_DB_PASSWORD_XXX', $DbPasswordSecret
    $content = $content -replace 'XXX_CHANGE_ME_ADMIN_API_KEY_XXX', $AdminApiKeySecret
    $content = $content -replace 'XXX_CHANGE_ME_BACKUP_RESTORE_API_KEY_XXX', $BackupRestoreApiKeySecret
    $content = $content -replace 'XXX_CHANGE_ME_BACKUP_DELETE_API_KEY_XXX', $BackupDeleteApiKeySecret
    Set-Content -Path $StackFile -Value $content -NoNewline
}

function Update-StackNetwork {
    param(
        [string]$StackFile,
        [string]$TraefikNetwork
    )
    
    $content = Get-Content $StackFile -Raw
    $content = $content -replace 'XXX_CHANGE_ME_TRAEFIK_NETWORK_NAME_XXX', $TraefikNetwork
    Set-Content -Path $StackFile -Value $content -NoNewline
}

function Add-CognitoToStack {
    param(
        [string]$StackFile,
        [string]$ProjectRoot,
        [string]$StackNameUpper
    )
    
    # Generate secret names
    $poolIdSecret = "${StackNameUpper}_COGNITO_USER_POOL_ID"
    $clientIdSecret = "${StackNameUpper}_COGNITO_APP_CLIENT_ID"
    $accessKeySecret = "${StackNameUpper}_AWS_ACCESS_KEY_ID"
    $secretKeySecret = "${StackNameUpper}_AWS_SECRET_ACCESS_KEY"
    
    # Read the stack file
    $content = Get-Content $StackFile -Raw
    
    # Check if Cognito secrets are already added
    if ($content -match "COGNITO_USER_POOL_ID_FILE") {
        Write-Host "ℹ️  Cognito configuration already present in stack file" -ForegroundColor Yellow
        return $true
    }
    
    Write-Host "⚙️  Adding AWS Cognito secrets to stack file..." -ForegroundColor Cyan
    
    # Add Cognito secrets to API service secrets section
    # Find the line with the last secret and add Cognito secrets after it
    $pattern = '(\s+- ".*_BACKUP_DELETE_API_KEY.*")'
    $replacement = "`$1`r`n      - `"$poolIdSecret`"`r`n      - `"$clientIdSecret`"`r`n      - `"$accessKeySecret`"`r`n      - `"$secretKeySecret`""
    $content = $content -replace $pattern, $replacement
    
    # Add Cognito environment variables after BACKUP_DELETE_API_KEY_FILE
    $cognitoEnvSnippet = "$ProjectRoot\setup\compose-modules\snippets\cognito-env.yml"
    if (Test-Path $cognitoEnvSnippet) {
        $cognitoEnvContent = Get-Content $cognitoEnvSnippet -Raw
        # Replace placeholder secret names in snippet
        $cognitoEnvContent = $cognitoEnvContent -replace 'XXX_CHANGE_ME_COGNITO_USER_POOL_ID_XXX', $poolIdSecret
        $cognitoEnvContent = $cognitoEnvContent -replace 'XXX_CHANGE_ME_COGNITO_APP_CLIENT_ID_XXX', $clientIdSecret
        $cognitoEnvContent = $cognitoEnvContent -replace 'XXX_CHANGE_ME_AWS_ACCESS_KEY_ID_XXX', $accessKeySecret
        $cognitoEnvContent = $cognitoEnvContent -replace 'XXX_CHANGE_ME_AWS_SECRET_ACCESS_KEY_XXX', $secretKeySecret
        
        $pattern = '(BACKUP_DELETE_API_KEY_FILE: /run/secrets/.*)'
        $replacement = "`$1`r`n$cognitoEnvContent"
        $content = $content -replace $pattern, $replacement
    }
    
    # Add Cognito secrets to footer secrets section
    $pattern = '(\s+".*_BACKUP_DELETE_API_KEY.*":\s+external: true)'
    $replacement = "`$1`r`n  `"$poolIdSecret`":`r`n    external: true`r`n  `"$clientIdSecret`":`r`n    external: true`r`n  `"$accessKeySecret`":`r`n    external: true`r`n  `"$secretKeySecret`":`r`n    external: true"
    $content = $content -replace $pattern, $replacement
    
    # Write updated content back to file
    Set-Content -Path $StackFile -Value $content -NoNewline
    
    Write-Host "✅ Cognito secrets added to stack file" -ForegroundColor Green
    return $true
}

function Backup-ExistingFiles {
    param([string]$ProjectRoot)
    
    $timestamp = Get-Date -Format "yyyy_MM_dd__HH_mm_ss"
    
    # Create backup directories
    New-Item -ItemType Directory -Force -Path "$ProjectRoot\backup\env" | Out-Null
    New-Item -ItemType Directory -Force -Path "$ProjectRoot\backup\swarm-stack-yml" | Out-Null
    
    if (Test-Path "$ProjectRoot\.env") {
        $backupFile = "$ProjectRoot\backup\env\.env.$timestamp"
        Copy-Item "$ProjectRoot\.env" $backupFile
        Write-Host "📋 Backed up .env to backup\env\.env.$timestamp"
    }
    
    if (Test-Path "$ProjectRoot\swarm-stack.yml") {
        $backupFile = "$ProjectRoot\backup\swarm-stack-yml\swarm-stack.yml.$timestamp"
        Copy-Item "$ProjectRoot\swarm-stack.yml" $backupFile
        Write-Host "📋 Backed up swarm-stack.yml to backup\swarm-stack-yml\swarm-stack.yml.$timestamp"
    }
}

Export-ModuleMember -Function New-EnvFile, New-StackFile, Update-EnvValue, Update-StackSecrets, Update-StackNetwork, Add-CognitoToStack, Backup-ExistingFiles
