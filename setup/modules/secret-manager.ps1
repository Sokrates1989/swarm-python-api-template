# Secret manager module
# Handles Docker secret creation

function New-DockerSecrets {
    param(
        [string]$DbPasswordSecret,
        [string]$AdminApiKeySecret
    )
    
    Write-Host "🔑 Create Docker Secrets" -ForegroundColor Cyan
    Write-Host "======================="
    Write-Host ""
    
    $CreateSecrets = Read-Host "Create secrets now? (Y/n)"
    if ($CreateSecrets -eq "n" -or $CreateSecrets -eq "N") {
        Write-Host "Skipping secret creation."
        Write-Host ""
        Write-Host "⚠️  Remember to create these secrets before deploying:" -ForegroundColor Yellow
        Write-Host "   - $DbPasswordSecret"
        Write-Host "   - $AdminApiKeySecret"
        Write-Host ""
        return $true
    }
    
    Write-Host ""
    Write-Host "Creating: $DbPasswordSecret" -ForegroundColor Cyan
    Write-Host "Enter the database password (input will be hidden):"
    $SecurePassword = Read-Host -AsSecureString
    $Password = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecurePassword)
    )
    
    $Password | docker secret create $DbPasswordSecret - 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ Created $DbPasswordSecret" -ForegroundColor Green
    } else {
        Write-Host "⚠️  Secret may already exist: $DbPasswordSecret" -ForegroundColor Yellow
    }
    
    Write-Host ""
    Write-Host "Creating: $AdminApiKeySecret" -ForegroundColor Cyan
    Write-Host "Enter the admin API key (input will be hidden):"
    $SecureApiKey = Read-Host -AsSecureString
    $ApiKey = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureApiKey)
    )
    
    $ApiKey | docker secret create $AdminApiKeySecret - 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ Created $AdminApiKeySecret" -ForegroundColor Green
    } else {
        Write-Host "⚠️  Secret may already exist: $AdminApiKeySecret" -ForegroundColor Yellow
    }
    
    Write-Host ""
    Write-Host "✅ Secret creation complete" -ForegroundColor Green
    Write-Host ""
    
    return $true
}

function Get-DockerSecrets {
    Write-Host "📋 Existing Docker Secrets" -ForegroundColor Cyan
    Write-Host "========================="
    Write-Host ""
    docker secret ls
    Write-Host ""
}

function Test-SecretsExist {
    param(
        [string]$DbPasswordSecret,
        [string]$AdminApiKeySecret
    )
    
    $dbExists = (docker secret ls --filter "name=${DbPasswordSecret}" --format "{{.Name}}") -eq $DbPasswordSecret
    $apiExists = (docker secret ls --filter "name=${AdminApiKeySecret}" --format "{{.Name}}") -eq $AdminApiKeySecret
    
    if (-not $dbExists -or -not $apiExists) {
        Write-Host "⚠️  Required secrets not found:" -ForegroundColor Yellow
        if (-not $dbExists) {
            Write-Host "   - $DbPasswordSecret (missing)" -ForegroundColor Red
        } else {
            Write-Host "   - $DbPasswordSecret (exists)" -ForegroundColor Green
        }
        if (-not $apiExists) {
            Write-Host "   - $AdminApiKeySecret (missing)" -ForegroundColor Red
        } else {
            Write-Host "   - $AdminApiKeySecret (exists)" -ForegroundColor Green
        }
        Write-Host ""
        return $false
    }
    
    Write-Host "✅ All required secrets exist" -ForegroundColor Green
    Write-Host ""
    return $true
}

Export-ModuleMember -Function New-DockerSecrets, Get-DockerSecrets, Test-SecretsExist
