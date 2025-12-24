# Secret manager module
# Handles Docker secret creation

function New-SingleDockerSecret {
    param(
        [string]$SecretName
    )
    
    Write-Host ""
    Write-Host "Creating: $SecretName" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Instructions for Notepad:" -ForegroundColor Gray
    Write-Host "  1. Type your secret value" -ForegroundColor Gray
    Write-Host "  2. Click File > Save (or press Ctrl+S)" -ForegroundColor Gray
    Write-Host "  3. Close Notepad" -ForegroundColor Gray
    Write-Host ""
    Read-Host "Press Enter to open Notepad" | Out-Null
    Write-Host ""
    
    # Create temporary file
    $secretFile = "secret.txt"
    Set-Content -Path $secretFile -Value "" -NoNewline
    
    # Open in Notepad and wait for it to close
    Start-Process notepad.exe -ArgumentList $secretFile -Wait
    
    # Check if file has content
    if ((Test-Path $secretFile) -and ((Get-Item $secretFile).Length -gt 0)) {
        # Check if secret already exists
        $secretExists = $false
        try {
            $null = docker secret inspect $SecretName 2>&1
            if ($LASTEXITCODE -eq 0) {
                $secretExists = $true
            }
        } catch {}
        
        if ($secretExists) {
            Write-Host "⚠️  Secret '$SecretName' already exists" -ForegroundColor Yellow
            $recreate = Read-Host "Delete and recreate? (y/N)"
            if ($recreate -match '^[Yy]$') {
                Write-Host "Removing old secret..." -ForegroundColor Yellow
                docker secret rm $SecretName 2>&1 | Out-Null
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "Creating new secret..." -ForegroundColor Yellow
                    docker secret create $SecretName $secretFile 2>&1 | Out-Null
                    if ($LASTEXITCODE -eq 0) {
                        Write-Host "✅ Recreated $SecretName" -ForegroundColor Green
                    } else {
                        Write-Host "❌ Failed to create secret" -ForegroundColor Red
                        Write-Host "Error: Docker secret creation failed. Check if Docker Swarm is initialized." -ForegroundColor Yellow
                    }
                } else {
                    Write-Host "❌ Failed to remove old secret" -ForegroundColor Red
                    Write-Host "The secret might be in use by a service. Stop the service first." -ForegroundColor Yellow
                    Write-Host "Afterwards run .\quick-start.ps1 to create the secrets or rerun the complete setup wizard." -ForegroundColor Yellow
                }
            } else {
                Write-Host "⏭️  Keeping existing secret" -ForegroundColor Cyan
            }
        } else {
            Write-Host "Creating secret..." -ForegroundColor Yellow
            docker secret create $SecretName $secretFile 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "✅ Created $SecretName" -ForegroundColor Green
            } else {
                Write-Host "❌ Failed to create secret" -ForegroundColor Red
                Write-Host "Error: Docker secret creation failed. Check if Docker Swarm is initialized." -ForegroundColor Yellow
            }
        }
        
        # Delete the temporary file
        Remove-Item -Path $secretFile -Force -ErrorAction SilentlyContinue
    } else {
        Write-Host "⚠️  Secret file is empty or not saved, skipping" -ForegroundColor Yellow
        Remove-Item -Path $secretFile -Force -ErrorAction SilentlyContinue
    }
}

function New-DockerSecrets {
    param(
        [string]$DbPasswordSecret,
        [string]$AdminApiKeySecret,
        [string]$BackupRestoreApiKeySecret,
        [string]$BackupDeleteApiKeySecret
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
        Write-Host "   - $BackupRestoreApiKeySecret"
        Write-Host "   - $BackupDeleteApiKeySecret"
        Write-Host ""
        return $true
    }
    
    # Create all secrets using file-based approach
    New-SingleDockerSecret -SecretName $DbPasswordSecret
    New-SingleDockerSecret -SecretName $AdminApiKeySecret
    New-SingleDockerSecret -SecretName $BackupRestoreApiKeySecret
    New-SingleDockerSecret -SecretName $BackupDeleteApiKeySecret
    
    Write-Host ""
    Write-Host "✅ Secret creation complete" -ForegroundColor Green
    Write-Host ""
    
    return (Test-SecretsExist -DbPasswordSecret $DbPasswordSecret -AdminApiKeySecret $AdminApiKeySecret -BackupRestoreApiKeySecret $BackupRestoreApiKeySecret -BackupDeleteApiKeySecret $BackupDeleteApiKeySecret)
}

function New-SecretsFromFile {
    param(
        [string]$DbPasswordSecret,
        [string]$AdminApiKeySecret,
        [string]$BackupRestoreApiKeySecret,
        [string]$BackupDeleteApiKeySecret,
        [string]$SecretsFile = "secrets.env",
        [string]$TemplatePath
    )

    if (-not (Test-Path $SecretsFile)) {
        if ($TemplatePath -and (Test-Path $TemplatePath)) {
            Copy-Item $TemplatePath $SecretsFile -Force
            Write-Host "Created $SecretsFile from template. Please edit it and rerun." -ForegroundColor Yellow
            return $false
        }
        Write-Host "Secrets file not found: $SecretsFile" -ForegroundColor Red
        return $false
    }

    $values = @{
        DB_PASSWORD = ""
        ADMIN_API_KEY = ""
        BACKUP_RESTORE_API_KEY = ""
        BACKUP_DELETE_API_KEY = ""
    }

    Get-Content $SecretsFile | ForEach-Object {
        $line = $_.Trim()
        if (-not $line) { return }
        if ($line.StartsWith("#")) { return }
        $parts = $line -split "=", 2
        if ($parts.Count -ne 2) { return }
        $k = $parts[0].Trim()
        $v = $parts[1].Trim()
        if ($values.ContainsKey($k)) {
            $values[$k] = $v
        }
    }

    function New-SingleSecretFromValue {
        param(
            [string]$SecretName,
            [string]$SecretValue
        )

        $SecretValue = $SecretValue.Trim()
        if ([string]::IsNullOrWhiteSpace($SecretValue)) {
            return $false
        }

        $exists = $false
        try {
            docker secret inspect $SecretName 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { $exists = $true }
        } catch {}

        if ($exists) {
            $recreate = Read-Host "Secret '$SecretName' exists. Delete and recreate? (y/N)"
            if ($recreate -match '^[Yy]$') {
                docker secret rm $SecretName 2>$null | Out-Null
            } else {
                return $true
            }
        }

        $SecretValue | docker secret create $SecretName - 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    }

    $ok = $true
    if (-not (New-SingleSecretFromValue -SecretName $DbPasswordSecret -SecretValue $values.DB_PASSWORD)) { $ok = $false }
    if (-not (New-SingleSecretFromValue -SecretName $AdminApiKeySecret -SecretValue $values.ADMIN_API_KEY)) { $ok = $false }
    if (-not (New-SingleSecretFromValue -SecretName $BackupRestoreApiKeySecret -SecretValue $values.BACKUP_RESTORE_API_KEY)) { $ok = $false }
    if (-not (New-SingleSecretFromValue -SecretName $BackupDeleteApiKeySecret -SecretValue $values.BACKUP_DELETE_API_KEY)) { $ok = $false }

    if (-not $ok) {
        return $false
    }

    return (Test-SecretsExist -DbPasswordSecret $DbPasswordSecret -AdminApiKeySecret $AdminApiKeySecret -BackupRestoreApiKeySecret $BackupRestoreApiKeySecret -BackupDeleteApiKeySecret $BackupDeleteApiKeySecret)
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
        [string]$AdminApiKeySecret,
        [string]$BackupRestoreApiKeySecret,
        [string]$BackupDeleteApiKeySecret
    )

    $missing = $false

    docker secret inspect $DbPasswordSecret 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { $missing = $true }

    docker secret inspect $AdminApiKeySecret 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { $missing = $true }

    docker secret inspect $BackupRestoreApiKeySecret 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { $missing = $true }

    docker secret inspect $BackupDeleteApiKeySecret 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { $missing = $true }

    return (-not $missing)
}

Export-ModuleMember -Function New-DockerSecrets, New-SecretsFromFile, Get-DockerSecrets, Test-SecretsExist, New-SingleDockerSecret
