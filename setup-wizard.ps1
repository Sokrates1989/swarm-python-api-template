# Swarm Python API Template - Setup Wizard
# Interactive setup script for Windows
# This script uses modular components for maintainability

$ErrorActionPreference = "Stop"

# Get the directory where this script is located
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = $ScriptDir
Set-Location $ProjectRoot

# Import all modules
Import-Module "$ScriptDir\setup\modules\user-prompts.ps1" -Force
Import-Module "$ScriptDir\setup\modules\config-builder.ps1" -Force
Import-Module "$ScriptDir\setup\modules\network-check.ps1" -Force
Import-Module "$ScriptDir\setup\modules\data-dirs.ps1" -Force
Import-Module "$ScriptDir\setup\modules\secret-manager.ps1" -Force
Import-Module "$ScriptDir\setup\modules\deploy-stack.ps1" -Force

# =============================================================================
# WELCOME & SETUP CHECK
# =============================================================================

Write-Host "🚀 Swarm Python API Template - Setup Wizard" -ForegroundColor Cyan
Write-Host "============================================"
Write-Host ""
Write-Host "This wizard will guide you through the complete setup and deployment."
Write-Host ""

# Check if setup is already complete
$SetupAlreadyDone = $false

if (Test-Path ".setup-complete") {
    $SetupAlreadyDone = $true
    Write-Host "⚠️  Setup has already been completed." -ForegroundColor Yellow
} elseif ((Test-Path ".env") -and (Test-Path "swarm-stack.yml")) {
    $SetupAlreadyDone = $true
    Write-Host "⚠️  Setup appears to have been done manually." -ForegroundColor Yellow
}

if ($SetupAlreadyDone) {
    if (-not (Get-YesNo "Run setup again? This will overwrite configuration" "N")) {
        Write-Host "Setup cancelled."
        exit 0
    }
    Write-Host ""
}

# Backup existing files
Backup-ExistingFiles $ProjectRoot

Write-Host ""
Write-Host "Let's configure your deployment!"
Write-Host ""

# =============================================================================
# CONFIGURATION PHASE - Collect User Input
# =============================================================================

# Database Type
$DbType = Get-DatabaseType
Write-Host "✅ Selected: $DbType" -ForegroundColor Green
Write-Host ""

# Proxy Type
$ProxyType = Get-ProxyType
Write-Host "✅ Selected: $ProxyType" -ForegroundColor Green
Write-Host ""

# Database Mode
$DbMode = Get-DatabaseMode
Write-Host "✅ Selected: $DbMode" -ForegroundColor Green
Write-Host ""

$DeployDatabase = ($DbMode -eq "local")

# Build configuration files
Write-Host "⚙️  Building configuration files..." -ForegroundColor Cyan
New-EnvFile -DbType $DbType -DbMode $DbMode -ProxyType $ProxyType -ProjectRoot $ProjectRoot
New-StackFile -DbType $DbType -DbMode $DbMode -ProxyType $ProxyType -ProjectRoot $ProjectRoot
Write-Host ""

# Collect deployment parameters
Write-Host "📝 Deployment Configuration" -ForegroundColor Cyan
Write-Host "==========================="
Write-Host ""

$StackName = Get-StackName
$DataRoot = Get-DataRoot (Get-Location).Path

if ($ProxyType -eq "traefik") {
    $TraefikNetwork = Get-TraefikNetwork
    $ApiUrl = Get-ApiDomain
} else {
    $PublishedPort = Get-PublishedPort
}

# Docker image
$ImageInfo = Get-DockerImage
if ($null -eq $ImageInfo) {
    Write-Host "Setup cancelled."
    exit 1
}
$ImageName = $ImageInfo.Name
$ImageVersion = $ImageInfo.Version

# Update .env with collected values
Update-EnvValue -EnvFile "$ProjectRoot\.env" -Key "STACK_NAME" -Value $StackName
Update-EnvValue -EnvFile "$ProjectRoot\.env" -Key "DATA_ROOT" -Value $DataRoot
Update-EnvValue -EnvFile "$ProjectRoot\.env" -Key "IMAGE_NAME" -Value $ImageName
Update-EnvValue -EnvFile "$ProjectRoot\.env" -Key "IMAGE_VERSION" -Value $ImageVersion

if ($ProxyType -eq "traefik") {
    Update-EnvValue -EnvFile "$ProjectRoot\.env" -Key "TRAEFIK_NETWORK" -Value $TraefikNetwork
    Update-EnvValue -EnvFile "$ProjectRoot\.env" -Key "API_URL" -Value $ApiUrl
} else {
    Update-EnvValue -EnvFile "$ProjectRoot\.env" -Key "PUBLISHED_PORT" -Value $PublishedPort
}

# Replicas
Write-Host ""
$ApiReplicas = Get-Replicas -ServiceName "API" -DefaultCount 1
Update-EnvValue -EnvFile "$ProjectRoot\.env" -Key "API_REPLICAS" -Value $ApiReplicas

if ($DbMode -eq "local") {
    $DbReplicas = Get-Replicas -ServiceName "Database" -DefaultCount 1
    
    if ($DbType -eq "postgresql") {
        Update-EnvValue -EnvFile "$ProjectRoot\.env" -Key "POSTGRES_REPLICAS" -Value $DbReplicas
    } elseif ($DbType -eq "neo4j") {
        Update-EnvValue -EnvFile "$ProjectRoot\.env" -Key "NEO4J_REPLICAS" -Value $DbReplicas
    }
}

$RedisReplicas = Get-Replicas -ServiceName "Redis" -DefaultCount 1
Update-EnvValue -EnvFile "$ProjectRoot\.env" -Key "REDIS_REPLICAS" -Value $RedisReplicas

# Auto-generate secret names from stack name
Write-Host ""
$StackNameUpper = $StackName.ToUpper() -replace '[^A-Z0-9]', '_'
$DbPasswordSecret = "${StackNameUpper}_DB_PASSWORD"
$AdminApiKeySecret = "${StackNameUpper}_ADMIN_API_KEY"

Write-Host "Secret names (auto-generated):"
Write-Host "  Database password: $DbPasswordSecret"
Write-Host "  Admin API key: $AdminApiKeySecret"

Update-StackSecrets -StackFile "$ProjectRoot\swarm-stack.yml" -DbPasswordSecret $DbPasswordSecret -AdminApiKeySecret $AdminApiKeySecret

Write-Host ""
Write-Host "✅ Configuration complete" -ForegroundColor Green
Write-Host ""

# Mark setup as complete
New-Item -ItemType File -Path ".setup-complete" -Force | Out-Null

# =============================================================================
# SECRET CREATION
# =============================================================================

$secretsCreated = New-DockerSecrets -DbPasswordSecret $DbPasswordSecret -AdminApiKeySecret $AdminApiKeySecret

# =============================================================================
# DEPLOYMENT PHASE
# =============================================================================

# Network verification
if (-not (Network-Verify -ApiUrl $ApiUrl -ProxyType $ProxyType)) {
    Write-Host "❌ Network verification failed" -ForegroundColor Red
    exit 1
}

# Create data directories
if (-not (New-DataDirectories -DataRoot $DataRoot -DbType $DbType)) {
    Write-Host "❌ Failed to create data directories" -ForegroundColor Red
    exit 1
}

# Deploy stack
if (-not (Invoke-StackDeploy -StackName $StackName -StackFile "swarm-stack.yml")) {
    Write-Host "❌ Deployment failed" -ForegroundColor Red
    exit 1
}

# Health check
Test-DeploymentHealth -StackName $StackName -DbType $DbType -ProxyType $ProxyType -ApiUrl $ApiUrl

Write-Host ""
Write-Host "🎉 Setup and deployment complete!" -ForegroundColor Green
Write-Host ""
Write-Host "Configuration files created:"
Write-Host "  - .env"
Write-Host "  - swarm-stack.yml"
Write-Host ""
Write-Host "Next steps:"
Write-Host "  - Monitor services: docker stack services $StackName"
Write-Host "  - View logs: docker service logs ${StackName}_api"
if ($ProxyType -eq "traefik") {
    Write-Host "  - Access API: https://${ApiUrl}"
} else {
    Write-Host "  - Access API: http://localhost:${PublishedPort}"
}
Write-Host ""
