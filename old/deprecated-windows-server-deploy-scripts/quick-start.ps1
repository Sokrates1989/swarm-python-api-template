# quick-start.ps1
# PowerShell version of quick-start.sh
# Quick start tool for Swarm Python API Template

$ErrorActionPreference = "Stop"

# Get script directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# Import modules
Import-Module "$ScriptDir\setup\modules\health-check.ps1" -Force
Import-Module "$ScriptDir\setup\modules\stack-conflict-check.ps1" -Force
Import-Module "$ScriptDir\setup\modules\deploy-stack.ps1" -Force
Import-Module "$ScriptDir\setup\modules\config-builder.ps1" -Force
Import-Module "$ScriptDir\setup\modules\secret-manager.ps1" -Force
Import-Module "$ScriptDir\setup\modules\ci-cd-github.ps1" -Force
Import-Module "$ScriptDir\setup\modules\menu_handlers.ps1" -Force

# Source Cognito setup script if available
$cognitoScript = Join-Path $ScriptDir "setup\modules\cognito_setup.ps1"
if (Test-Path $cognitoScript) {
    . $cognitoScript
}

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
    if (Get-Command docker-compose -ErrorAction SilentlyContinue) {
        $null = docker-compose --version 2>&1
        if ($LASTEXITCODE -ne 0) { throw "Docker Compose not available" }
    } else {
        $null = docker compose version 2>&1
        if ($LASTEXITCODE -ne 0) { throw "Docker Compose not available" }
    }
} catch {
    Write-Host "[ERROR] Docker Compose is not available!" -ForegroundColor Red
    Write-Host "Please install Docker Compose v1 (docker-compose) or a current Docker version with the Compose plugin" -ForegroundColor Yellow
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
$PROXY_TYPE = "none"
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
    
    $proxyTypeLine = $envContent | Where-Object { $_ -match "^PROXY_TYPE=" }
    if ($proxyTypeLine) {
        $PROXY_TYPE = ($proxyTypeLine -split "=", 2)[1].Trim().Trim('"')
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
Show-MainMenu -StackName $STACK_NAME -ApiUrl $API_URL -DbType $DB_TYPE -ProxyType $PROXY_TYPE -ImageName $IMAGE_NAME -ImageVersion $IMAGE_VERSION
