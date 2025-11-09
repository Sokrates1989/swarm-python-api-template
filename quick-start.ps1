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

# Check if initial setup is needed
if (-not (Test-Path .setup-complete)) {
    Write-Host " First-time setup detected!" -ForegroundColor Cyan
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
        docker compose -f interactive-scripts/docker-compose.setup.yml run --rm setup
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
Write-Host "8) Create Docker secrets" -ForegroundColor Gray
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
        docker compose -f interactive-scripts/docker-compose.setup.yml run --rm setup
    }
    "8" {
        Write-Host "Create Docker Secrets" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "This will help you create the required Docker secrets." -ForegroundColor Yellow
        Write-Host ""
        
        $dbPassword = Read-Host "Enter the database password" -AsSecureString
        $dbPasswordPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($dbPassword))
        
        $adminKey = Read-Host "Enter the admin API key" -AsSecureString
        $adminKeyPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($adminKey))
        
        Write-Host ""
        Write-Host "Creating secrets..." -ForegroundColor Cyan
        
        try {
            $dbPasswordPlain | docker secret create "DB_PASSWORD_${STACK_NAME}" - 2>&1 | Out-Null
        } catch {
            Write-Host "Secret may already exist: DB_PASSWORD_${STACK_NAME}" -ForegroundColor Yellow
        }
        
        try {
            $adminKeyPlain | docker secret create "ADMIN_API_KEY_${STACK_NAME}" - 2>&1 | Out-Null
        } catch {
            Write-Host "Secret may already exist: ADMIN_API_KEY_${STACK_NAME}" -ForegroundColor Yellow
        }
        
        Write-Host ""
        Write-Host "Secrets created (or already exist)" -ForegroundColor Green
        Write-Host ""
        Write-Host "List secrets with: docker secret ls" -ForegroundColor Yellow
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
