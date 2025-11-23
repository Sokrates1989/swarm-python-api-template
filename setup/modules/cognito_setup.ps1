# Shared helpers for configuring AWS Cognito environment variables.
# This script can be dot-sourced by other PowerShell scripts (setup-wizard.ps1, quick-start.ps1)
# to provide a consistent interactive configuration flow.

$script:CognitoScriptDir = Split-Path -Parent $PSCommandPath
$script:CognitoProjectRoot = Split-Path -Parent $script:CognitoScriptDir
$script:CognitoEnvPath = Join-Path $script:CognitoProjectRoot '.env'

# Import secret-manager module for file-based secret creation
$secretManagerPath = Join-Path $script:CognitoScriptDir 'secret-manager.ps1'
if (Test-Path $secretManagerPath) {
    Import-Module $secretManagerPath -Force
}

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
    
    # Check if already configured
    $hasExisting = -not [string]::IsNullOrWhiteSpace($currentRegion)
    
    if ($hasExisting -and -not $Force) {
        Write-Host "`n⚠️  Existing AWS Region configuration detected:" -ForegroundColor Yellow
        Write-Host "  AWS_REGION=$currentRegion" -ForegroundColor Gray
        
        $overwrite = Read-Host "`nDo you want to overwrite this configuration? (y/N)"
        if ($overwrite -notmatch '^[Yy]$') {
            Write-Host "ℹ️  Keeping existing configuration." -ForegroundColor Yellow
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
    Write-Host "🌍 AWS Region" -ForegroundColor Cyan
    Write-Host "  Example: eu-central-1" -ForegroundColor Gray
    Write-Host "  AWS Console: top-right corner or Pool details" -ForegroundColor Gray
    Write-Host "  Flutter config: look for 'Region' in amplifyconfiguration.dart" -ForegroundColor Gray
    $region = Get-RequiredValue -Prompt "Enter AWS Region" -Current $currentRegion
    
    # Save only AWS_REGION to .env (secrets will be stored as Docker secrets only)
    Set-CognitoEnvValue -Key 'AWS_REGION' -Value $region
    
    # Confirm
    Write-Host "`n✅ AWS Region saved to $script:CognitoEnvPath" -ForegroundColor Green
    Write-Host "  AWS_REGION=$region" -ForegroundColor Gray
    
    # Create Docker secrets for Cognito configuration
    Write-Host "`n🔑 Creating Docker Secrets for AWS Cognito" -ForegroundColor Cyan
    Write-Host "==========================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Cognito secrets must be stored as Docker secrets (not in .env)." -ForegroundColor Gray
    Write-Host "You'll enter each secret value in Notepad." -ForegroundColor Gray
    Write-Host ""
    
    # Get stack name from .env
    $stackName = Get-CognitoEnvValue -Key 'STACK_NAME'
    if (-not $stackName) {
        $stackName = "api_production"
    }
    
    # Generate secret names
    $stackNameUpper = $stackName.ToUpper() -replace '[^A-Z0-9]', '_'
    $poolIdSecret = "${stackNameUpper}_COGNITO_USER_POOL_ID"
    $clientIdSecret = "${stackNameUpper}_COGNITO_APP_CLIENT_ID"
    $accessKeySecret = "${stackNameUpper}_AWS_ACCESS_KEY_ID"
    $secretKeySecret = "${stackNameUpper}_AWS_SECRET_ACCESS_KEY"
    
    # Ask which optional secrets to create
    Write-Host "Which secrets do you want to create?" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Required:"
    Write-Host "  - $poolIdSecret (Cognito User Pool ID)" -ForegroundColor Gray
    Write-Host ""
    $createClient = Read-Host "Create App Client ID secret? (y/N)"
    $createIam = Read-Host "Create IAM Access Key secrets? (y/N)"
    Write-Host ""
    
    $createSecrets = Read-Host "Create Docker secrets for Cognito configuration? (Y/n)"
    if ($createSecrets -notmatch '^[Nn]$') {
        Write-Host ""
        Write-Host "You'll be prompted to enter each secret value in Notepad." -ForegroundColor Gray
        Write-Host "The secrets will be securely stored in Docker and the temporary files will be deleted." -ForegroundColor Gray
        Write-Host ""
        
        # Create required secrets
        New-SingleDockerSecret -SecretName $poolIdSecret
        
        # Create optional secrets
        if ($createClient -match '^[Yy]$') {
            New-SingleDockerSecret -SecretName $clientIdSecret
        }
        
        if ($createIam -match '^[Yy]$') {
            New-SingleDockerSecret -SecretName $accessKeySecret
            New-SingleDockerSecret -SecretName $secretKeySecret
        }
        
        Write-Host ""
        Write-Host "✅ Cognito secrets created" -ForegroundColor Green
    } else {
        Write-Host "ℹ️  Skipping secret creation. You can create them manually later." -ForegroundColor Yellow
    }
    
    return $true
}
