# Shared helpers for configuring AWS Cognito environment variables.
# This script can be dot-sourced by other PowerShell scripts (setup-wizard.ps1, quick-start.ps1)
# to provide a consistent interactive configuration flow.

$script:CognitoScriptDir = Split-Path -Parent $PSCommandPath
$script:CognitoProjectRoot = Split-Path -Parent $script:CognitoScriptDir
$script:CognitoEnvPath = Join-Path $script:CognitoProjectRoot '.env'

function Get-CognitoEnvValue {
    param([string]$Key)
    
    if (-not (Test-Path $script:CognitoEnvPath)) {
        return $null
    }
    
    $line = Get-Content $script:CognitoEnvPath -ErrorAction SilentlyContinue | 
            Where-Object { $_ -match "^$([regex]::Escape($Key))=" } | 
            Select-Object -First 1
    
    if (-not $line) {
        return $null
    }
    
    return ($line -split '=', 2)[1]
}

function Set-CognitoEnvValue {
    param(
        [string]$Key,
        [string]$Value
    )
    
    if (-not (Test-Path $script:CognitoEnvPath)) {
        throw "Environment file does not exist: $script:CognitoEnvPath"
    }
    
    $content = Get-Content $script:CognitoEnvPath -Raw
    $pattern = "(?m)^$([regex]::Escape($Key))=.*$"
    
    if ($content -match $pattern) {
        $content = $content -replace $pattern, "$Key=$Value"
    } else {
        if (-not $content.EndsWith("`n")) {
            $content += "`n"
        }
        $content += "$Key=$Value`n"
    }
    
    Set-Content -Path $script:CognitoEnvPath -Value $content -NoNewline
}

function Invoke-CognitoSetup {
    param([switch]$Force)
    
    # Ensure .env file exists
    if (-not (Test-Path $script:CognitoEnvPath)) {
        Write-Host "[ERROR] .env file does not exist. Cannot configure Cognito." -ForegroundColor Red
        Write-Host "Please run the setup wizard first to create the .env file." -ForegroundColor Yellow
        return $false
    }
    
    # Ask if user wants to configure
    if (-not $Force) {
        $answer = Read-Host "`nWould you like to configure AWS Cognito settings now? (y/N)"
        if ($answer -notmatch '^[Yy]$') {
            Write-Host "Skipping AWS Cognito configuration." -ForegroundColor Yellow
            return $false
        }
    }
    
    # Get current values
    $currentRegion = Get-CognitoEnvValue -Key 'AWS_REGION'
    $currentPool = Get-CognitoEnvValue -Key 'COGNITO_USER_POOL_ID'
    $currentClient = Get-CognitoEnvValue -Key 'COGNITO_APP_CLIENT_ID'
    $currentAccessKey = Get-CognitoEnvValue -Key 'AWS_ACCESS_KEY_ID'
    $currentSecret = Get-CognitoEnvValue -Key 'AWS_SECRET_ACCESS_KEY'
    
    # Check if already configured
    $hasExisting = (-not [string]::IsNullOrWhiteSpace($currentRegion)) -and 
                   (-not [string]::IsNullOrWhiteSpace($currentPool))
    
    if ($hasExisting -and -not $Force) {
        Write-Host "`nExisting Cognito configuration detected:" -ForegroundColor Cyan
        Write-Host "  AWS_REGION=$currentRegion" -ForegroundColor Gray
        Write-Host "  COGNITO_USER_POOL_ID=$currentPool" -ForegroundColor Gray
        if ($currentClient) {
            Write-Host "  COGNITO_APP_CLIENT_ID=$currentClient" -ForegroundColor Gray
        }
        
        $overwrite = Read-Host "`nDo you want to overwrite this configuration? (y/N)"
        if ($overwrite -notmatch '^[Yy]$') {
            Write-Host "Keeping existing Cognito configuration." -ForegroundColor Yellow
            return $false
        }
    }
    
    # Helper function for required prompts
    function Get-RequiredValue {
        param([string]$Prompt, [string]$Current)
        
        while ($true) {
            if ($Current) {
                $response = Read-Host "$Prompt [$Current]"
            } else {
                $response = Read-Host $Prompt
            }
            
            if ([string]::IsNullOrWhiteSpace($response)) {
                if ($Current) {
                    return $Current
                }
                Write-Host "Value cannot be empty." -ForegroundColor Red
            } else {
                return $response
            }
        }
    }
    
    # Helper function for optional prompts
    function Get-OptionalValue {
        param([string]$Prompt, [string]$Current, [string]$DisplayValue)
        
        $suffix = ""
        if ($DisplayValue) {
            $suffix = " $DisplayValue"
        } elseif ($Current) {
            $suffix = " [$Current]"
        }
        
        $response = Read-Host "$Prompt$suffix"
        if ([string]::IsNullOrWhiteSpace($response)) {
            return $Current
        }
        return $response
    }
    
    # Start prompting
    Write-Host "`n================================" -ForegroundColor Cyan
    Write-Host "AWS Cognito Configuration" -ForegroundColor Cyan
    Write-Host "================================`n" -ForegroundColor Cyan
    
    Write-Host "You'll need values from your AWS Cognito User Pool." -ForegroundColor Gray
    Write-Host "Where to find them:" -ForegroundColor Gray
    Write-Host "  - AWS Console: Cognito > User pools > select your pool" -ForegroundColor Gray
    Write-Host "  - Flutter config: lib/utils/authentication/config/amplifyconfiguration.dart`n" -ForegroundColor Gray
    
    # AWS Region
    Write-Host "AWS Region" -ForegroundColor Cyan
    Write-Host "  Example: eu-central-1" -ForegroundColor Gray
    Write-Host "  AWS Console: top-right corner or Pool details" -ForegroundColor Gray
    Write-Host "  Flutter config: look for 'Region' in amplifyconfiguration.dart" -ForegroundColor Gray
    $region = Get-RequiredValue -Prompt "Enter AWS Region" -Current $currentRegion
    
    # User Pool ID
    Write-Host "`nCognito User Pool ID" -ForegroundColor Cyan
    Write-Host "  AWS Console: User pool > Pool details > User pool ID" -ForegroundColor Gray
    Write-Host "  Flutter config: use CognitoUserPool.Default.PoolId in amplifyconfiguration.dart" -ForegroundColor Gray
    $pool = Get-RequiredValue -Prompt "Enter Cognito User Pool ID" -Current $currentPool
    
    # App Client ID (optional)
    Write-Host "`nCognito App Client ID (optional)" -ForegroundColor Cyan
    Write-Host "  AWS Console: User pool > App integration > App client list" -ForegroundColor Gray
    Write-Host "  Flutter config: look for 'AppClientId' in amplifyconfiguration.dart" -ForegroundColor Gray
    $client = Get-OptionalValue -Prompt "Enter Cognito App Client ID (optional)" -Current $currentClient
    
    # IAM Credentials (optional)
    Write-Host "`nOptional: IAM credentials (only if backend requires Cognito admin APIs)" -ForegroundColor Gray
    Write-Host "  AWS Console: IAM > Users > Security credentials tab" -ForegroundColor Gray
    $accessKey = Get-OptionalValue -Prompt "AWS Access Key ID (optional)" -Current $currentAccessKey
    
    Write-Host "  Note: Secret Access Key is only shown when you create/rotate the key" -ForegroundColor Gray
    $secretDisplay = if ($currentSecret) { '[stored]' } else { $null }
    $secret = Get-OptionalValue -Prompt "AWS Secret Access Key (optional)" -Current $currentSecret -DisplayValue $secretDisplay
    
    # Save values
    Set-CognitoEnvValue -Key 'AWS_REGION' -Value $region
    Set-CognitoEnvValue -Key 'COGNITO_USER_POOL_ID' -Value $pool
    Set-CognitoEnvValue -Key 'COGNITO_APP_CLIENT_ID' -Value $client
    Set-CognitoEnvValue -Key 'AWS_ACCESS_KEY_ID' -Value $accessKey
    Set-CognitoEnvValue -Key 'AWS_SECRET_ACCESS_KEY' -Value $secret
    
    # Confirm
    Write-Host "`nSaved AWS Cognito configuration to $script:CognitoEnvPath" -ForegroundColor Green
    Write-Host "  AWS_REGION=$region" -ForegroundColor Gray
    Write-Host "  COGNITO_USER_POOL_ID=$pool" -ForegroundColor Gray
    if ($client) {
        Write-Host "  COGNITO_APP_CLIENT_ID=$client" -ForegroundColor Gray
    }
    
    return $true
}
