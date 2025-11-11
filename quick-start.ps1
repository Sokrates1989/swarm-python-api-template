# quick-start.ps1
# PowerShell version of quick-start.sh
# Quick start tool for Swarm Python API Template

$ErrorActionPreference = "Stop"

Write-Host "Swarm Python API Template - Quick Start" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# Check Docker availability
Write-Host "Checking Docker installation..." -ForegroundColor Yellow
try {
    $null = docker --version 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Docker not found" }
} catch {
    Write-Host "[ERROR] Docker is not installed!" -ForegroundColor Red
    Write-Host "Please install Docker from: https://www.docker.com/get-started" -ForegroundColor Yellow
    exit 1
}

# Check Docker daemon
try {
    $null = docker info 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Docker daemon not running" }
} catch {
    Write-Host "[ERROR] Docker daemon is not running!" -ForegroundColor Red
    Write-Host "Please start Docker Desktop or the Docker service" -ForegroundColor Yellow
    exit 1
}

# Check Docker Compose
try {
    $null = docker compose version 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Docker Compose not available" }
} catch {
    Write-Host "[ERROR] Docker Compose is not available!" -ForegroundColor Red
    Write-Host "Please install a current Docker version with Compose plugin" -ForegroundColor Yellow
    exit 1
}

Write-Host "Docker is installed and running" -ForegroundColor Green
Write-Host ""

# Check if initial setup is needed (same logic as setup wizard)
$SETUP_DONE = $false
if (Test-Path ".setup-complete") {
    $SETUP_DONE = $true
} elseif ((Test-Path ".env") -and (Test-Path "swarm-stack.yml")) {
    $SETUP_DONE = $true
}

if (-not $SETUP_DONE) {
    Write-Host "🚀 First-time setup detected!" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "This appears to be your first time setting up this deployment." -ForegroundColor Yellow
    Write-Host "Would you like to run the interactive setup wizard?" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "The setup wizard will help you configure:" -ForegroundColor Gray
    Write-Host "  - Database type (PostgreSQL or Neo4j)" -ForegroundColor Gray
    Write-Host "  - Proxy type (Traefik or no-proxy)" -ForegroundColor Gray
    Write-Host "  - Database mode (local or external)" -ForegroundColor Gray
    Write-Host "  - Docker image and version" -ForegroundColor Gray
    Write-Host "  - Domain/port configuration" -ForegroundColor Gray
    Write-Host "  - Swarm stack settings" -ForegroundColor Gray
    Write-Host ""
    
    $runSetup = Read-Host "Run setup wizard now? (Y/n)"
    if ($runSetup -ne "n" -and $runSetup -ne "N") {
        Write-Host ""
        Write-Host "Starting setup wizard..." -ForegroundColor Cyan
        .\setup\setup-wizard.ps1
        Write-Host ""
    } else {
        Write-Host ""
        Write-Host "Setup wizard skipped." -ForegroundColor Yellow
        Write-Host "You'll need to manually configure .env and swarm-stack.yml" -ForegroundColor Yellow
        Write-Host "See README.md for manual setup instructions." -ForegroundColor Yellow
        exit 0
    }
    Write-Host ""
}

# Check if configuration files exist
if (-not (Test-Path .env)) {
    Write-Host "[ERROR] .env file not found!" -ForegroundColor Red
    Write-Host "Please run the setup wizard or create .env manually." -ForegroundColor Yellow
    exit 1
}

if (-not (Test-Path swarm-stack.yml)) {
    Write-Host "[ERROR] swarm-stack.yml not found!" -ForegroundColor Red
    Write-Host "Please run the setup wizard or create swarm-stack.yml manually." -ForegroundColor Yellow
    exit 1
}

# Read configuration from .env
$STACK_NAME = "api_production"
$API_URL = "api.example.com"
$DB_TYPE = "postgresql"
$IMAGE_NAME = ""
$IMAGE_VERSION = ""

if (Test-Path .env) {
    $envContent = Get-Content .env -ErrorAction SilentlyContinue
    
    $stackLine = $envContent | Where-Object { $_ -match "^STACK_NAME=" }
    if ($stackLine) {
        $STACK_NAME = ($stackLine -split "=", 2)[1].Trim().Trim('"')
    }
    
    $urlLine = $envContent | Where-Object { $_ -match "^API_URL=" }
    if ($urlLine) {
        $API_URL = ($urlLine -split "=", 2)[1].Trim().Trim('"')
    }
    
    $dbTypeLine = $envContent | Where-Object { $_ -match "^DB_TYPE=" }
    if ($dbTypeLine) {
        $DB_TYPE = ($dbTypeLine -split "=", 2)[1].Trim().Trim('"')
    }
    
    $imageLine = $envContent | Where-Object { $_ -match "^IMAGE_NAME=" }
    if ($imageLine) {
        $IMAGE_NAME = ($imageLine -split "=", 2)[1].Trim().Trim('"')
    }
    
    $versionLine = $envContent | Where-Object { $_ -match "^IMAGE_VERSION=" }
    if ($versionLine) {
        $IMAGE_VERSION = ($versionLine -split "=", 2)[1].Trim().Trim('"')
    }
}

Write-Host "Current Configuration" -ForegroundColor Cyan
Write-Host "========================" -ForegroundColor Cyan
Write-Host "Stack Name:     $STACK_NAME" -ForegroundColor Gray
Write-Host "API Domain:     $API_URL" -ForegroundColor Gray
Write-Host "Database Type:  $DB_TYPE" -ForegroundColor Gray
Write-Host "Docker Image:   ${IMAGE_NAME}:${IMAGE_VERSION}" -ForegroundColor Gray
Write-Host ""

# Main menu
Write-Host "Choose an option:" -ForegroundColor Yellow
Write-Host "1) Deploy to Docker Swarm" -ForegroundColor Gray
Write-Host "2) Check deployment status" -ForegroundColor Gray
Write-Host "3) View service logs" -ForegroundColor Gray
Write-Host "4) Update API image" -ForegroundColor Gray
Write-Host "5) Scale services" -ForegroundColor Gray
Write-Host "6) Remove deployment" -ForegroundColor Gray
Write-Host "7) Re-run setup wizard" -ForegroundColor Gray
Write-Host "8) Manage Docker secrets" -ForegroundColor Gray
Write-Host "9) Exit" -ForegroundColor Gray
Write-Host ""
$choice = Read-Host "Your choice (1-9)"

switch ($choice) {
    "1" {
        Write-Host "Deploying to Docker Swarm..." -ForegroundColor Cyan
        Write-Host ""
        Write-Host "Make sure you have:" -ForegroundColor Yellow
        Write-Host "   - Created Docker secrets" -ForegroundColor Gray
        Write-Host "   - Configured your domain DNS" -ForegroundColor Gray
        Write-Host "   - Created data directories" -ForegroundColor Gray
        Write-Host ""
        $confirm = Read-Host "Continue with deployment? (y/N)"
        if ($confirm -match "^[Yy]$") {
            Write-Host ""
            Write-Host "Deploying stack: $STACK_NAME" -ForegroundColor Cyan
            
            # Deploy using swarm-stack.yml
            docker stack deploy -c swarm-stack.yml $STACK_NAME
            
            Write-Host ""
            Write-Host "Deployment initiated!" -ForegroundColor Green
            Write-Host ""
            Write-Host "Check status with:" -ForegroundColor Yellow
            Write-Host "  docker stack services $STACK_NAME" -ForegroundColor Gray
            Write-Host ""
            Write-Host "View logs with:" -ForegroundColor Yellow
            Write-Host "  docker service logs -f ${STACK_NAME}_api" -ForegroundColor Gray
        } else {
            Write-Host "Deployment cancelled." -ForegroundColor Yellow
        }
    }
    "2" {
        Write-Host "Checking deployment status..." -ForegroundColor Cyan
        Write-Host ""
        docker stack services $STACK_NAME
        Write-Host ""
        Write-Host "For detailed task status:" -ForegroundColor Yellow
        Write-Host "  docker service ps ${STACK_NAME}_api --no-trunc" -ForegroundColor Gray
    }
    "3" {
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
            "1" {
                docker service logs -f "${STACK_NAME}_api"
            }
            "2" {
                if ($DB_TYPE -eq "neo4j") {
                    docker service logs -f "${STACK_NAME}_neo4j"
                } else {
                    docker service logs -f "${STACK_NAME}_postgres"
                }
            }
            "3" {
                docker service logs -f "${STACK_NAME}_redis"
            }
            "4" {
                docker service logs -f $STACK_NAME
            }
            default {
                Write-Host "Invalid choice" -ForegroundColor Red
            }
        }
    }
    "4" {
        Write-Host "Update API Image" -ForegroundColor Cyan
        Write-Host ""
        $newVersion = Read-Host "Enter new image version [$IMAGE_VERSION]"
        if ([string]::IsNullOrWhiteSpace($newVersion)) {
            $newVersion = $IMAGE_VERSION
        }
        
        Write-Host ""
        Write-Host "Pulling image: ${IMAGE_NAME}:${newVersion}" -ForegroundColor Cyan
        docker pull "${IMAGE_NAME}:${newVersion}"
        
        Write-Host ""
        Write-Host "Updating service..." -ForegroundColor Cyan
        docker service update --image "${IMAGE_NAME}:${newVersion}" "${STACK_NAME}_api"
        
        Write-Host ""
        Write-Host "Service update initiated!" -ForegroundColor Green
        Write-Host "Monitor progress with: docker service ps ${STACK_NAME}_api" -ForegroundColor Yellow
    }
    "5" {
        Write-Host "Scale Services" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "Which service do you want to scale?" -ForegroundColor Yellow
        Write-Host "1) API" -ForegroundColor Gray
        Write-Host "2) Redis" -ForegroundColor Gray
        if ($DB_TYPE -eq "postgresql") {
            Write-Host "3) PostgreSQL" -ForegroundColor Gray
        } elseif ($DB_TYPE -eq "neo4j") {
            Write-Host "3) Neo4j" -ForegroundColor Gray
        }
        Write-Host ""
        $scaleChoice = Read-Host "Your choice"
        
        $replicas = Read-Host "Number of replicas"
        
        switch ($scaleChoice) {
            "1" {
                docker service scale "${STACK_NAME}_api=$replicas"
            }
            "2" {
                docker service scale "${STACK_NAME}_redis=$replicas"
            }
            "3" {
                if ($DB_TYPE -eq "neo4j") {
                    docker service scale "${STACK_NAME}_neo4j=$replicas"
                } else {
                    docker service scale "${STACK_NAME}_postgres=$replicas"
                }
            }
            default {
                Write-Host "Invalid choice" -ForegroundColor Red
            }
        }
    }
    "6" {
        Write-Host "Remove Deployment" -ForegroundColor Red
        Write-Host ""
        Write-Host "WARNING: This will remove all services in the stack." -ForegroundColor Yellow
        Write-Host "Data in volumes will be preserved." -ForegroundColor Yellow
        Write-Host ""
        $confirm = Read-Host "Are you sure? Type 'yes' to confirm"
        if ($confirm -eq "yes") {
            Write-Host ""
            Write-Host "Removing stack: $STACK_NAME" -ForegroundColor Cyan
            docker stack rm $STACK_NAME
            Write-Host ""
            Write-Host "Stack removal initiated!" -ForegroundColor Green
            Write-Host "Wait for all services to be removed before redeploying." -ForegroundColor Yellow
        } else {
            Write-Host "Removal cancelled." -ForegroundColor Yellow
        }
    }
    "7" {
        Write-Host "Re-running setup wizard..." -ForegroundColor Cyan
        Write-Host ""
        .\setup\setup-wizard.ps1
    }
    "8" {
        Write-Host "🔑 Manage Docker Secrets" -ForegroundColor Cyan
        Write-Host ""
        
        # Convert stack name to uppercase and replace non-alphanumeric chars with underscore
        $STACK_NAME_UPPER = $STACK_NAME.ToUpper() -replace '[^A-Z0-9]', '_'
        
        # Define secret names
        $DB_PASSWORD_SECRET = "${STACK_NAME_UPPER}_DB_PASSWORD"
        $ADMIN_API_KEY_SECRET = "${STACK_NAME_UPPER}_ADMIN_API_KEY"
        $BACKUP_RESTORE_API_KEY_SECRET = "${STACK_NAME_UPPER}_BACKUP_RESTORE_API_KEY"
        $BACKUP_DELETE_API_KEY_SECRET = "${STACK_NAME_UPPER}_BACKUP_DELETE_API_KEY"
        
        # Check which secrets exist
        Write-Host "📋 Current Secret Status:" -ForegroundColor Yellow
        Write-Host "------------------------"
        
        try {
            $null = docker secret inspect $DB_PASSWORD_SECRET 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Host "✅ Database password secret exists" -ForegroundColor Green
            } else {
                Write-Host "❌ Database password secret missing" -ForegroundColor Red
            }
        } catch {
            Write-Host "❌ Database password secret missing" -ForegroundColor Red
        }
        
        try {
            $null = docker secret inspect $ADMIN_API_KEY_SECRET 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Host "✅ Admin API key secret exists" -ForegroundColor Green
            } else {
                Write-Host "❌ Admin API key secret missing" -ForegroundColor Red
            }
        } catch {
            Write-Host "❌ Admin API key secret missing" -ForegroundColor Red
        }
        
        try {
            $null = docker secret inspect $BACKUP_RESTORE_API_KEY_SECRET 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Host "✅ Backup restore API key secret exists" -ForegroundColor Green
            } else {
                Write-Host "❌ Backup restore API key secret missing" -ForegroundColor Red
            }
        } catch {
            Write-Host "❌ Backup restore API key secret missing" -ForegroundColor Red
        }
        
        try {
            $null = docker secret inspect $BACKUP_DELETE_API_KEY_SECRET 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Host "✅ Backup delete API key secret exists" -ForegroundColor Green
            } else {
                Write-Host "❌ Backup delete API key secret missing" -ForegroundColor Red
            }
        } catch {
            Write-Host "❌ Backup delete API key secret missing" -ForegroundColor Red
        }
        
        Write-Host ""
        Write-Host "What would you like to do?" -ForegroundColor Yellow
        Write-Host "1) Create/update all secrets"
        Write-Host "2) List all secrets"
        Write-Host "3) Back to main menu"
        Write-Host ""
        $secret_choice = Read-Host "Your choice (1-3)"
        
        switch ($secret_choice) {
            "1" {
                # Check if stack is running
                Write-Host ""
                Write-Host "🔍 Checking for running stack..." -ForegroundColor Yellow
                
                $stackExists = docker stack ls --format "{{.Name}}" | Select-String -Pattern "^${STACK_NAME}$"
                
                if ($stackExists) {
                    Write-Host "⚠️  WARNING: Stack '$STACK_NAME' is currently running!" -ForegroundColor Yellow
                    Write-Host ""
                    Write-Host "Secrets cannot be updated while in use by a running stack." -ForegroundColor Yellow
                    Write-Host ""
                    $removeStack = Read-Host "Remove stack before updating secrets? (y/N)"
                    
                    if ($removeStack -match '^[Yy]$') {
                        Write-Host ""
                        Write-Host "Removing stack: $STACK_NAME" -ForegroundColor Cyan
                        docker stack rm $STACK_NAME
                        
                        Write-Host "Waiting for stack to be fully removed..." -ForegroundColor Yellow
                        do {
                            Write-Host "." -NoNewline
                            Start-Sleep -Seconds 2
                            $stackStillExists = docker stack ls --format "{{.Name}}" | Select-String -Pattern "^${STACK_NAME}$"
                        } while ($stackStillExists)
                        Write-Host ""
                        Write-Host "✅ Stack removed successfully" -ForegroundColor Green
                        Write-Host ""
                        
                        # Now create secrets
                        $secrets = @($DB_PASSWORD_SECRET, $ADMIN_API_KEY_SECRET, $BACKUP_RESTORE_API_KEY_SECRET, $BACKUP_DELETE_API_KEY_SECRET)
                        foreach ($secret in $secrets) {
                            Write-Host ""
                            Write-Host "Creating: $secret" -ForegroundColor Cyan
                            Write-Host "Opening Notepad..." -ForegroundColor Yellow
                            Write-Host "Please enter the secret value, save, and close Notepad." -ForegroundColor Yellow
                            Write-Host ""
                            Write-Host "Press any key to open editor..." -ForegroundColor Yellow
                            $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
                            Write-Host ""
                            
                            "" | Set-Content "secret.txt" -NoNewline
                            notepad secret.txt | Out-Null
                            
                            # Check if secret already exists
                            $secretExists = $false
                            try {
                                $null = docker secret inspect $secret 2>&1
                                if ($LASTEXITCODE -eq 0) {
                                    $secretExists = $true
                                }
                            } catch {}
                            
                            if ($secretExists) {
                                Write-Host "⚠️  Secret '$secret' already exists" -ForegroundColor Yellow
                                $recreate = Read-Host "Delete and recreate? (y/N)"
                                if ($recreate -match '^[Yy]$') {
                                    Write-Host "Removing old secret..." -ForegroundColor Yellow
                                    docker secret rm $secret 2>&1 | Out-Null
                                    if ($LASTEXITCODE -eq 0) {
                                        Write-Host "Creating new secret..." -ForegroundColor Yellow
                                        docker secret create $secret secret.txt 2>&1 | Out-Null
                                        if ($LASTEXITCODE -eq 0) {
                                            Write-Host "✅ Recreated $secret" -ForegroundColor Green
                                        } else {
                                            Write-Host "❌ Failed to create secret" -ForegroundColor Red
                                        }
                                    } else {
                                        Write-Host "❌ Failed to remove old secret" -ForegroundColor Red
                                        Write-Host "The secret might be in use. Stop the service first." -ForegroundColor Yellow
                                    }
                                } else {
                                    Write-Host "⏭️  Keeping existing secret" -ForegroundColor Cyan
                                }
                            } else {
                                Write-Host "Creating secret..." -ForegroundColor Yellow
                                docker secret create $secret secret.txt 2>&1 | Out-Null
                                if ($LASTEXITCODE -eq 0) {
                                    Write-Host "✅ Created $secret" -ForegroundColor Green
                                } else {
                                    Write-Host "❌ Failed to create secret" -ForegroundColor Red
                                }
                            }
                            
                            Remove-Item "secret.txt" -ErrorAction SilentlyContinue
                        }
                        
                        Write-Host ""
                        Write-Host "✅ Secret creation complete" -ForegroundColor Green
                    } else {
                        Write-Host ""
                        Write-Host "⚠️  Secret creation cancelled." -ForegroundColor Yellow
                        Write-Host "Stop the stack manually with: docker stack rm $STACK_NAME" -ForegroundColor Yellow
                        Write-Host "Then run this option again." -ForegroundColor Yellow
                    }
                } else {
                    Write-Host "✅ No running stack found" -ForegroundColor Green
                    Write-Host ""
                    
                    # Create secrets
                    $secrets = @($DB_PASSWORD_SECRET, $ADMIN_API_KEY_SECRET, $BACKUP_RESTORE_API_KEY_SECRET, $BACKUP_DELETE_API_KEY_SECRET)
                    foreach ($secret in $secrets) {
                        Write-Host ""
                        Write-Host "Creating: $secret" -ForegroundColor Cyan
                        Write-Host "Opening Notepad..." -ForegroundColor Yellow
                        Write-Host "Please enter the secret value, save, and close Notepad." -ForegroundColor Yellow
                        Write-Host ""
                        Write-Host "Press any key to open editor..." -ForegroundColor Yellow
                        $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
                        Write-Host ""
                        
                        "" | Set-Content "secret.txt" -NoNewline
                        notepad secret.txt | Out-Null
                        
                        # Check if secret already exists
                        $secretExists = $false
                        try {
                            $null = docker secret inspect $secret 2>&1
                            if ($LASTEXITCODE -eq 0) {
                                $secretExists = $true
                            }
                        } catch {}
                        
                        if ($secretExists) {
                            Write-Host "⚠️  Secret '$secret' already exists" -ForegroundColor Yellow
                            $recreate = Read-Host "Delete and recreate? (y/N)"
                            if ($recreate -match '^[Yy]$') {
                                Write-Host "Removing old secret..." -ForegroundColor Yellow
                                docker secret rm $secret 2>&1 | Out-Null
                                if ($LASTEXITCODE -eq 0) {
                                    Write-Host "Creating new secret..." -ForegroundColor Yellow
                                    docker secret create $secret secret.txt 2>&1 | Out-Null
                                    if ($LASTEXITCODE -eq 0) {
                                        Write-Host "✅ Recreated $secret" -ForegroundColor Green
                                    } else {
                                        Write-Host "❌ Failed to create secret" -ForegroundColor Red
                                    }
                                } else {
                                    Write-Host "❌ Failed to remove old secret" -ForegroundColor Red
                                    Write-Host "The secret might be in use. Stop the service first." -ForegroundColor Yellow
                                }
                            } else {
                                Write-Host "⏭️  Keeping existing secret" -ForegroundColor Cyan
                            }
                        } else {
                            Write-Host "Creating secret..." -ForegroundColor Yellow
                            docker secret create $secret secret.txt 2>&1 | Out-Null
                            if ($LASTEXITCODE -eq 0) {
                                Write-Host "✅ Created $secret" -ForegroundColor Green
                            } else {
                                Write-Host "❌ Failed to create secret" -ForegroundColor Red
                            }
                        }
                        
                        Remove-Item "secret.txt" -ErrorAction SilentlyContinue
                    }
                    
                    Write-Host ""
                    Write-Host "✅ Secret creation complete" -ForegroundColor Green
                }
            }
            "2" {
                Write-Host ""
                Write-Host "📋 Existing Docker Secrets" -ForegroundColor Cyan
                Write-Host "========================="
                Write-Host ""
                docker secret ls
            }
            "3" {
                Write-Host "Returning to main menu..." -ForegroundColor Cyan
            }
            default {
                Write-Host "Invalid choice" -ForegroundColor Red
            }
        }
    }
    "9" {
        Write-Host "Goodbye!" -ForegroundColor Cyan
        exit 0
    }
    default {
        Write-Host "Invalid choice" -ForegroundColor Red
        exit 1
    }
}

Write-Host ""
Write-Host "Done!" -ForegroundColor Green
