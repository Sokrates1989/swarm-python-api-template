<#
.SYNOPSIS
    Authentication Provider Selection Module for Python API Template.

.DESCRIPTION
    Handles selection and configuration of authentication providers.
    Supports AWS Cognito and Keycloak as authentication backends.

.NOTES
    Source this file and call Set-AuthProvider
#>

# =============================================================================
# Constants
# =============================================================================

$script:AUTH_PROVIDER_COGNITO = "cognito"
$script:AUTH_PROVIDER_KEYCLOAK = "keycloak"
$script:AUTH_PROVIDER_DUAL = "dual"
$script:AUTH_PROVIDER_NONE = "none"

# =============================================================================
# Helper Functions
# =============================================================================

function Get-AuthEnvValue {
    <#
    .SYNOPSIS
        Gets a value from the .env file.
    #>
    param([string]$Key)
    
    $envFile = Join-Path $PSScriptRoot "..\..\..\.env"
    if (-not (Test-Path $envFile)) { return "" }
    
    $content = Get-Content $envFile -Raw
    if ($content -match "(?m)^$Key=(.*)$") {
        return $matches[1].Trim()
    }
    return ""
}

function Set-AuthEnvValue {
    <#
    .SYNOPSIS
        Sets a value in the .env file.
    #>
    param([string]$Key, [string]$Value)
    
    $envFile = Join-Path $PSScriptRoot "..\..\..\.env"
    
    if (-not (Test-Path $envFile)) {
        "$Key=$Value" | Out-File -FilePath $envFile -Encoding utf8
        return
    }
    
    $content = Get-Content $envFile -Raw
    if ($content -match "(?m)^$Key=") {
        $content = $content -replace "(?m)^$Key=.*$", "$Key=$Value"
    } else {
        $content = $content.TrimEnd() + "`n$Key=$Value`n"
    }
    $content | Out-File -FilePath $envFile -Encoding utf8 -NoNewline
}

# =============================================================================
# Provider Detection
# =============================================================================

function Get-CurrentAuthProvider {
    <#
    .SYNOPSIS
        Gets the currently configured authentication provider.
    #>
    $provider = Get-AuthEnvValue "AUTH_PROVIDER"
    
    if ([string]::IsNullOrWhiteSpace($provider)) {
        # Check for Cognito config as fallback
        $cognitoPool = Get-AuthEnvValue "COGNITO_USER_POOL_ID"
        if (-not [string]::IsNullOrWhiteSpace($cognitoPool)) {
            return $script:AUTH_PROVIDER_COGNITO
        }
        
        # Check for Keycloak config
        $keycloakUrl = Get-AuthEnvValue "KEYCLOAK_SERVER_URL"
        if (-not [string]::IsNullOrWhiteSpace($keycloakUrl)) {
            return $script:AUTH_PROVIDER_KEYCLOAK
        }
        
        return $script:AUTH_PROVIDER_NONE
    }
    return $provider
}

function Test-AuthConfigured {
    <#
    .SYNOPSIS
        Checks if authentication is configured.
    #>
    $provider = Get-CurrentAuthProvider
    return $provider -ne $script:AUTH_PROVIDER_NONE
}

# =============================================================================
# Provider Selection UI
# =============================================================================

function Show-AuthProviderSelection {
    <#
    .SYNOPSIS
        Displays auth provider selection menu.
    #>
    Write-Host ""
    Write-Host "Authentication Provider Selection" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Choose your authentication backend:"
    Write-Host ""
    Write-Host "  1) AWS Cognito" -ForegroundColor Gray
    Write-Host "     - Managed auth service from AWS" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  2) Keycloak" -ForegroundColor Gray
    Write-Host "     - Open-source identity management" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  3) Dual (Keycloak + Cognito fallback)" -ForegroundColor Gray
    Write-Host "     - Tries Keycloak first, then Cognito" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  4) None (no authentication)" -ForegroundColor Gray
    Write-Host ""
    
    $choice = Read-Host "Your choice (1-4) [1]"
    if ([string]::IsNullOrWhiteSpace($choice)) { $choice = "1" }
    
    switch ($choice) {
        "1" { return $script:AUTH_PROVIDER_COGNITO }
        "2" { return $script:AUTH_PROVIDER_KEYCLOAK }
        "3" { return $script:AUTH_PROVIDER_DUAL }
        "4" { return $script:AUTH_PROVIDER_NONE }
        default { return $script:AUTH_PROVIDER_COGNITO }
    }
}

# =============================================================================
# Cognito Configuration
# =============================================================================

function Set-CognitoAuth {
    <#
    .SYNOPSIS
        Configures AWS Cognito authentication.
    #>
    Write-Host ""
    Write-Host "AWS Cognito Configuration" -ForegroundColor Blue
    Write-Host ""
    Write-Host "You'll need from your AWS Cognito User Pool:"
    Write-Host "  - User Pool ID (e.g., us-east-1_xxxxxxxxx)"
    Write-Host "  - App Client ID"
    Write-Host "  - AWS Region"
    Write-Host ""
    
    $currentRegion = Get-AuthEnvValue "AWS_REGION"
    $currentPool = Get-AuthEnvValue "COGNITO_USER_POOL_ID"
    $currentClient = Get-AuthEnvValue "COGNITO_APP_CLIENT_ID"
    
    $defaultRegion = if ($currentRegion) { $currentRegion } else { "us-east-1" }
    $region = Read-Host "AWS Region [$defaultRegion]"
    if ([string]::IsNullOrWhiteSpace($region)) { $region = $defaultRegion }
    
    $poolId = Read-Host "User Pool ID [$currentPool]"
    if ([string]::IsNullOrWhiteSpace($poolId)) { $poolId = $currentPool }
    while ([string]::IsNullOrWhiteSpace($poolId)) {
        Write-Host "User Pool ID is required" -ForegroundColor Yellow
        $poolId = Read-Host "User Pool ID"
    }
    
    $clientId = Read-Host "App Client ID [$currentClient]"
    if ([string]::IsNullOrWhiteSpace($clientId)) { $clientId = $currentClient }
    
    # Update .env
    Set-AuthEnvValue "AUTH_PROVIDER" $script:AUTH_PROVIDER_COGNITO
    Set-AuthEnvValue "AWS_REGION" $region
    Set-AuthEnvValue "COGNITO_USER_POOL_ID" $poolId
    Set-AuthEnvValue "COGNITO_APP_CLIENT_ID" $clientId
    
    Write-Host ""
    Write-Host "[OK] AWS Cognito configured" -ForegroundColor Green
    Write-Host "  Region: $region"
    Write-Host "  User Pool: $poolId"
}

# =============================================================================
# Keycloak Configuration
# =============================================================================

function Set-KeycloakAuth {
    <#
    .SYNOPSIS
        Configures Keycloak authentication.
    #>
    Write-Host ""
    Write-Host "Keycloak Configuration" -ForegroundColor Blue
    Write-Host ""
    Write-Host "You'll need from your Keycloak server:"
    Write-Host "  - Server URL (e.g., https://auth.example.com)"
    Write-Host "  - Realm name"
    Write-Host "  - Client ID"
    Write-Host ""
    
    $currentUrl = Get-AuthEnvValue "KEYCLOAK_SERVER_URL"
    $currentRealm = Get-AuthEnvValue "KEYCLOAK_REALM"
    $currentClient = Get-AuthEnvValue "KEYCLOAK_CLIENT_ID"
    $currentInternal = Get-AuthEnvValue "KEYCLOAK_INTERNAL_URL"
    
    $defaultUrl = if ($currentUrl) { $currentUrl } else { "http://localhost:9090" }
    $serverUrl = Read-Host "Keycloak Server URL [$defaultUrl]"
    if ([string]::IsNullOrWhiteSpace($serverUrl)) { $serverUrl = $defaultUrl }
    
    $defaultRealm = if ($currentRealm) { $currentRealm } else { "my-app" }
    $realm = Read-Host "Realm name [$defaultRealm]"
    if ([string]::IsNullOrWhiteSpace($realm)) { $realm = $defaultRealm }
    
    $defaultClient = if ($currentClient) { $currentClient } else { "$realm-backend" }
    $clientId = Read-Host "Client ID [$defaultClient]"
    if ([string]::IsNullOrWhiteSpace($clientId)) { $clientId = $defaultClient }

    $internalUrl = Read-Host "Internal URL (optional) [$currentInternal]"
    if ([string]::IsNullOrWhiteSpace($internalUrl)) { $internalUrl = $currentInternal }
    
    # Update .env
    Set-AuthEnvValue "AUTH_PROVIDER" $script:AUTH_PROVIDER_KEYCLOAK
    Set-AuthEnvValue "KEYCLOAK_SERVER_URL" $serverUrl
    Set-AuthEnvValue "KEYCLOAK_INTERNAL_URL" $internalUrl
    Set-AuthEnvValue "KEYCLOAK_REALM" $realm
    Set-AuthEnvValue "KEYCLOAK_CLIENT_ID" $clientId
    
    # Derive OIDC endpoints
    $issuerUrl = "$serverUrl/realms/$realm"
    Set-AuthEnvValue "KEYCLOAK_ISSUER_URL" $issuerUrl
    Set-AuthEnvValue "KEYCLOAK_JWKS_URL" "$issuerUrl/protocol/openid-connect/certs"
    
    Write-Host ""
    Write-Host "[OK] Keycloak configured" -ForegroundColor Green
    Write-Host "  Server: $serverUrl"
    if (-not [string]::IsNullOrWhiteSpace($internalUrl)) {
        Write-Host "  Internal: $internalUrl"
    }
    Write-Host "  Realm: $realm"
    Write-Host "  Client: $clientId"
}

# =============================================================================
# Main Setup Function
# =============================================================================

function Set-AuthProvider {
    <#
    .SYNOPSIS
        Main entry point for auth provider setup.
    #>
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  Authentication Provider Setup" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    
    # Check existing configuration
    if (Test-AuthConfigured) {
        $current = Get-CurrentAuthProvider
        Write-Host ""
        Write-Host "Current provider: $current" -ForegroundColor Gray
        Write-Host ""
        
        $reconfigure = Read-Host "Reconfigure authentication? (y/N)"
        if ($reconfigure -notmatch "^[Yy]$") {
            Write-Host "Keeping current configuration." -ForegroundColor Blue
            return
        }
    }
    
    # Select provider
    $provider = Show-AuthProviderSelection
    
    Write-Host ""
    Write-Host "Selected: $provider" -ForegroundColor Blue
    
    # Configure based on selection
    switch ($provider) {
        $script:AUTH_PROVIDER_COGNITO { Set-CognitoAuth }
        $script:AUTH_PROVIDER_KEYCLOAK { Set-KeycloakAuth }
        $script:AUTH_PROVIDER_DUAL {
            Set-KeycloakAuth
            Set-CognitoAuth
            Set-AuthEnvValue "AUTH_PROVIDER" $script:AUTH_PROVIDER_DUAL
        }
        $script:AUTH_PROVIDER_NONE {
            Set-AuthEnvValue "AUTH_PROVIDER" $script:AUTH_PROVIDER_NONE
            Write-Host ""
            Write-Host "[OK] Authentication disabled" -ForegroundColor Green
        }
    }
    
    Write-Host ""
    Write-Host "Authentication provider setup complete!" -ForegroundColor Green
    Write-Host ""
    
    # Show next steps
    if ($provider -eq $script:AUTH_PROVIDER_KEYCLOAK) {
        Write-Host "Next steps for Keycloak:" -ForegroundColor Yellow
        Write-Host "  1. Ensure Keycloak server is running" -ForegroundColor Gray
        Write-Host "  2. Create realm and client in Keycloak admin" -ForegroundColor Gray
        Write-Host "  3. Configure social providers (optional)" -ForegroundColor Gray
    } elseif ($provider -eq $script:AUTH_PROVIDER_DUAL) {
        Write-Host "Next steps for Dual auth:" -ForegroundColor Yellow
        Write-Host "  1. Ensure Keycloak server is running" -ForegroundColor Gray
        Write-Host "  2. Verify Cognito pool settings in AWS Console" -ForegroundColor Gray
        Write-Host "  3. Update CORS settings for your frontend" -ForegroundColor Gray
    } elseif ($provider -eq $script:AUTH_PROVIDER_COGNITO) {
        Write-Host "Next steps for Cognito:" -ForegroundColor Yellow
        Write-Host "  1. Verify User Pool settings in AWS Console" -ForegroundColor Gray
        Write-Host "  2. Configure social identity providers (optional)" -ForegroundColor Gray
    }
    Write-Host ""
}

function Show-AuthStatus {
    <#
    .SYNOPSIS
        Shows current auth provider status.
    #>
    $provider = Get-CurrentAuthProvider
    
    Write-Host ""
    Write-Host "Authentication Status" -ForegroundColor Cyan
    
    switch ($provider) {
        $script:AUTH_PROVIDER_COGNITO {
            Write-Host "[OK] Provider: AWS Cognito" -ForegroundColor Green
            Write-Host "  Region: $(Get-AuthEnvValue 'AWS_REGION')"
            Write-Host "  Pool: $(Get-AuthEnvValue 'COGNITO_USER_POOL_ID')"
        }
        $script:AUTH_PROVIDER_KEYCLOAK {
            Write-Host "[OK] Provider: Keycloak" -ForegroundColor Green
            Write-Host "  Server: $(Get-AuthEnvValue 'KEYCLOAK_SERVER_URL')"
            Write-Host "  Realm: $(Get-AuthEnvValue 'KEYCLOAK_REALM')"
        }
        $script:AUTH_PROVIDER_DUAL {
            Write-Host "[OK] Provider: Dual (Keycloak + Cognito)" -ForegroundColor Green
            Write-Host "  Keycloak Server: $(Get-AuthEnvValue 'KEYCLOAK_SERVER_URL')"
            Write-Host "  Keycloak Realm: $(Get-AuthEnvValue 'KEYCLOAK_REALM')"
            Write-Host "  Cognito Region: $(Get-AuthEnvValue 'AWS_REGION')"
            Write-Host "  Cognito Pool: $(Get-AuthEnvValue 'COGNITO_USER_POOL_ID')"
        }
        default {
            Write-Host "[WARN] Provider: Not configured" -ForegroundColor Yellow
        }
    }
    Write-Host ""
}
