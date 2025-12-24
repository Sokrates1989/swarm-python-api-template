function Show-MainMenu {
    <#
    .SYNOPSIS
    Main interactive menu loop.

    .DESCRIPTION
    Provides interactive actions for Swarm deployment, including deploy/remove, health checks, logs,
    image updates, scaling, secrets management, CI/CD helper, and optional Cognito configuration.
    #>
    param(
        [string]$StackName,
        [string]$ApiUrl,
        [string]$DbType,
        [string]$ProxyType,
        [string]$ImageName,
        [string]$ImageVersion
    )

    $hasCognito = [bool](Get-Command Invoke-CognitoSetup -ErrorAction SilentlyContinue)

    while ($true) {
        $menuNext = 1
        $MENU_SETUP_WIZARD = $menuNext; $menuNext++
        $MENU_SETUP_SECRETS = $menuNext; $menuNext++
        $MENU_SETUP_COGNITO = $null
        if ($hasCognito) { $MENU_SETUP_COGNITO = $menuNext; $menuNext++ }
        $MENU_DEPLOY = $menuNext; $menuNext++
        $MENU_STATUS = $menuNext; $menuNext++
        $MENU_LOGS = $menuNext; $menuNext++
        $MENU_UPDATE_IMAGE = $menuNext; $menuNext++
        $MENU_SCALE = $menuNext; $menuNext++
        $MENU_REMOVE = $menuNext; $menuNext++
        $MENU_CICD = $menuNext; $menuNext++
        $MENU_EXIT = $menuNext

        Write-Host "" 
        Write-Host "================ Main Menu ================" -ForegroundColor Yellow
        Write-Host "" 

        Write-Host "Setup:" -ForegroundColor Yellow
        Write-Host "  $MENU_SETUP_WIZARD) Re-run setup wizard" -ForegroundColor Gray
        Write-Host "  $MENU_SETUP_SECRETS) Manage Docker secrets" -ForegroundColor Gray
        if ($hasCognito) {
            Write-Host "  $MENU_SETUP_COGNITO) Configure AWS Cognito" -ForegroundColor Gray
        }
        Write-Host "" 

        Write-Host "Deployment:" -ForegroundColor Yellow
        Write-Host "  $MENU_DEPLOY) Deploy to Docker Swarm" -ForegroundColor Gray
        Write-Host "  $MENU_STATUS) Check deployment status" -ForegroundColor Gray
        Write-Host "  $MENU_LOGS) View service logs" -ForegroundColor Gray
        Write-Host "" 

        Write-Host "Management:" -ForegroundColor Yellow
        Write-Host "  $MENU_UPDATE_IMAGE) Update API image" -ForegroundColor Gray
        Write-Host "  $MENU_SCALE) Scale services" -ForegroundColor Gray
        Write-Host "  $MENU_REMOVE) Remove deployment" -ForegroundColor Gray
        Write-Host "" 

        Write-Host "CI/CD:" -ForegroundColor Yellow
        Write-Host "  $MENU_CICD) GitHub Actions CI/CD helper" -ForegroundColor Gray
        Write-Host "" 

        Write-Host "  $MENU_EXIT) Exit" -ForegroundColor Gray

        Write-Host ""
        $choice = Read-Host "Your choice (1-$MENU_EXIT)"

        if ($hasCognito -and ($choice -eq "$MENU_SETUP_COGNITO")) {
            Invoke-CognitoSetup
            Write-Host "" 
            continue
        }

        switch ($choice) {
        "$MENU_DEPLOY" {
            $stackFile = Join-Path (Get-Location).Path "swarm-stack.yml"
            Invoke-StackDeploy -StackName $StackName -StackFile $stackFile
        }
        "$MENU_STATUS" {
            Check-DeploymentHealth -StackName $StackName -DbType $DbType -ProxyType $ProxyType -ApiUrl $ApiUrl
        }
        "$MENU_LOGS" {
            Write-Host "Service Logs" -ForegroundColor Cyan
            Write-Host ""
            Write-Host "Which service logs do you want to view?" -ForegroundColor Yellow
            Write-Host "1) API" -ForegroundColor Gray
            Write-Host "2) Database" -ForegroundColor Gray
            Write-Host "3) Redis" -ForegroundColor Gray
            Write-Host "4) All" -ForegroundColor Gray
            Write-Host ""
            $logChoice = Read-Host "Your choice (1-4)"

            switch ($logChoice) {
                "1" { docker service logs -f "${StackName}_api" }
                "2" {
                    if ($DbType -eq "neo4j") {
                        docker service logs -f "${StackName}_neo4j"
                    } else {
                        docker service logs -f "${StackName}_postgres"
                    }
                }
                "3" { docker service logs -f "${StackName}_redis" }
                "4" {
                    $services = docker service ls --filter "label=com.docker.stack.namespace=$StackName" --format "{{.Name}}" 2>$null
                    if (-not $services) {
                        Write-Host "No services found for stack: $StackName" -ForegroundColor Yellow
                    } else {
                        foreach ($svc in $services) {
                            Write-Host "" 
                            Write-Host "===== $svc =====" -ForegroundColor Cyan
                            docker service logs --tail 50 $svc 2>$null
                        }
                    }
                }
                default { Write-Host "Invalid choice" -ForegroundColor Red }
            }
        }
        "$MENU_UPDATE_IMAGE" {
            $newVersion = Read-Host "Enter new image version [$ImageVersion]"
            if ([string]::IsNullOrWhiteSpace($newVersion)) { $newVersion = $ImageVersion }

            docker pull "${ImageName}:${newVersion}"
            docker service update --image "${ImageName}:${newVersion}" "${StackName}_api"

            if (Test-Path .env) {
                Update-EnvValue -EnvFile ".env" -Key "IMAGE_VERSION" -Value $newVersion
                Write-Host "Saved IMAGE_VERSION=$newVersion to .env" -ForegroundColor Green
            }
        }
        "$MENU_SCALE" {
            Write-Host "Scale Services" -ForegroundColor Cyan
            Write-Host ""
            Write-Host "Which service do you want to scale?" -ForegroundColor Yellow
            Write-Host "1) API" -ForegroundColor Gray
            Write-Host "2) Redis" -ForegroundColor Gray
            if ($DbType -eq "postgresql") {
                Write-Host "3) PostgreSQL" -ForegroundColor Gray
            } elseif ($DbType -eq "neo4j") {
                Write-Host "3) Neo4j" -ForegroundColor Gray
            }
            Write-Host ""
            $scaleChoice = Read-Host "Your choice"
            $replicas = Read-Host "Number of replicas"

            switch ($scaleChoice) {
                "1" {
                    docker service scale "${StackName}_api=$replicas"
                    if (Test-Path .env) {
                        Update-EnvValue -EnvFile ".env" -Key "API_REPLICAS" -Value $replicas
                    }
                }
                "2" {
                    docker service scale "${StackName}_redis=$replicas"
                    if (Test-Path .env) {
                        Update-EnvValue -EnvFile ".env" -Key "REDIS_REPLICAS" -Value $replicas
                    }
                }
                "3" {
                    if ($DbType -eq "neo4j") {
                        docker service scale "${StackName}_neo4j=$replicas"
                        if (Test-Path .env) {
                            Update-EnvValue -EnvFile ".env" -Key "NEO4J_REPLICAS" -Value $replicas
                        }
                    } else {
                        docker service scale "${StackName}_postgres=$replicas"
                        if (Test-Path .env) {
                            Update-EnvValue -EnvFile ".env" -Key "POSTGRES_REPLICAS" -Value $replicas
                        }
                    }
                }
                default { Write-Host "Invalid choice" -ForegroundColor Red }
            }
        }
        "$MENU_REMOVE" {
            $confirm = Read-Host "Are you sure? Type 'yes' to confirm"
            if ($confirm -eq "yes") {
                docker stack rm $StackName
                Write-Host "Stack removal initiated!" -ForegroundColor Green
            }
        }
        "$MENU_SETUP_WIZARD" {
            .\setup\setup-wizard.ps1
        }
        "$MENU_SETUP_SECRETS" {
            Write-Host "🔑 Manage Docker Secrets" -ForegroundColor Cyan
            Write-Host ""

            $stackNameUpper = $StackName.ToUpper() -replace '[^A-Z0-9]', '_'

            $dbPasswordSecret = "${stackNameUpper}_DB_PASSWORD"
            $adminApiKeySecret = "${stackNameUpper}_ADMIN_API_KEY"
            $backupRestoreApiKeySecret = "${stackNameUpper}_BACKUP_RESTORE_API_KEY"
            $backupDeleteApiKeySecret = "${stackNameUpper}_BACKUP_DELETE_API_KEY"

            Write-Host "📋 Current Secret Status:" -ForegroundColor Yellow
            Write-Host "------------------------"

            foreach ($secretName in @($dbPasswordSecret, $adminApiKeySecret, $backupRestoreApiKeySecret, $backupDeleteApiKeySecret)) {
                try {
                    $null = docker secret inspect $secretName 2>&1
                    if ($LASTEXITCODE -eq 0) {
                        Write-Host "✅ $secretName" -ForegroundColor Green
                    } else {
                        Write-Host "❌ $secretName" -ForegroundColor Red
                    }
                } catch {
                    Write-Host "❌ $secretName" -ForegroundColor Red
                }
            }

            Write-Host ""
            Write-Host "What would you like to do?" -ForegroundColor Yellow
            Write-Host "1) Create/update all secrets" -ForegroundColor Gray
            Write-Host "2) List all secrets" -ForegroundColor Gray
            Write-Host "3) Back to main menu" -ForegroundColor Gray
            Write-Host ""

            $secretChoice = Read-Host "Your choice (1-3)"
            switch ($secretChoice) {
                "1" {
                    New-DockerSecrets -DbPasswordSecret $dbPasswordSecret -AdminApiKeySecret $adminApiKeySecret -BackupRestoreApiKeySecret $backupRestoreApiKeySecret -BackupDeleteApiKeySecret $backupDeleteApiKeySecret | Out-Null
                }
                "2" {
                    Get-DockerSecrets
                }
                "3" {
                }
                Default {
                    Write-Host "Invalid choice" -ForegroundColor Red
                }
            }
        }
        "$MENU_CICD" {
            Invoke-GitHubCICDHelper
        }
        "$MENU_EXIT" {
            Write-Host "Goodbye!" -ForegroundColor Cyan
            exit 0
        }
        default {
            Write-Host "Invalid choice" -ForegroundColor Red
        }
        }

        Write-Host ""
    }
}

Export-ModuleMember -Function Show-MainMenu
