# Swarm Python API Template - Setup Wizard
# Interactive setup script for Windows
# This script uses modular components for maintainability

$ErrorActionPreference = "Stop"

# Get the directory where this script is located
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

# Import all modules
Import-Module "$ScriptDir\modules\user-prompts.ps1" -Force
Import-Module "$ScriptDir\modules\config-builder.ps1" -Force
Import-Module "$ScriptDir\modules\network-check.ps1" -Force
Import-Module "$ScriptDir\modules\data-dirs.ps1" -Force
Import-Module "$ScriptDir\modules\secret-manager.ps1" -Force
Import-Module "$ScriptDir\modules\deploy-stack.ps1" -Force
Import-Module "$ScriptDir\modules\health-check.ps1" -Force

# Source Cognito setup script if available
$cognitoScript = Join-Path $ScriptDir "modules\cognito_setup.ps1"
if (Test-Path $cognitoScript) {
    . $cognitoScript
}

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

# SSL Mode (only for Traefik)
if ($ProxyType -eq "traefik") {
    $SslMode = Get-SslMode
    Write-Host "✅ Selected: $SslMode SSL" -ForegroundColor Green
    Write-Host ""
} else {
    $SslMode = "direct"  # Default for non-Traefik
}

# Database Mode
$DbMode = Get-DatabaseMode
Write-Host "✅ Selected: $DbMode" -ForegroundColor Green
Write-Host ""

$DeployDatabase = ($DbMode -eq "local")

# Get Traefik network if needed (before building stack file)
if ($ProxyType -eq "traefik") {
    $TraefikNetwork = Get-TraefikNetwork
}

# Build configuration files
Write-Host "⚙️  Building configuration files..." -ForegroundColor Cyan
New-EnvFile -DbType $DbType -DbMode $DbMode -ProxyType $ProxyType -ProjectRoot $ProjectRoot
New-StackFile -DbType $DbType -DbMode $DbMode -ProxyType $ProxyType -ProjectRoot $ProjectRoot -SslMode $SslMode

# Replace Traefik network placeholder if using Traefik
if ($ProxyType -eq "traefik") {
    Update-StackNetwork -StackFile "$ProjectRoot\swarm-stack.yml" -TraefikNetwork $TraefikNetwork
}

Write-Host ""

# Collect deployment parameters
Write-Host "📝 Deployment Configuration" -ForegroundColor Cyan
Write-Host "==========================="
Write-Host ""

$StackName = Get-StackName
$DataRoot = Get-DataRoot (Get-Location).Path

if ($ProxyType -eq "traefik") {
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

# Debug mode
Write-Host ""
$EnableDebug = Read-Host "Enable debug mode? (y/N)"
if ($EnableDebug -match '^[Yy]$') {
    $DebugMode = "true"
    Write-Host "✅ Debug mode enabled" -ForegroundColor Green
} else {
    $DebugMode = "false"
    Write-Host "✅ Debug mode disabled" -ForegroundColor Green
}

# Update .env with collected values
Update-EnvValue -EnvFile "$ProjectRoot\.env" -Key "STACK_NAME" -Value $StackName
Update-EnvValue -EnvFile "$ProjectRoot\.env" -Key "DATA_ROOT" -Value $DataRoot
Update-EnvValue -EnvFile "$ProjectRoot\.env" -Key "IMAGE_NAME" -Value $ImageName
Update-EnvValue -EnvFile "$ProjectRoot\.env" -Key "IMAGE_VERSION" -Value $ImageVersion
Update-EnvValue -EnvFile "$ProjectRoot\.env" -Key "DEBUG" -Value $DebugMode

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

Update-StackSecrets -StackFile "$ProjectRoot\swarm-stack.yml" -DbPasswordSecret $DbPasswordSecret -AdminApiKeySecret $AdminApiKeySecret -BackupRestoreApiKeySecret $BackupRestoreApiKeySecret -BackupDeleteApiKeySecret $BackupDeleteApiKeySecret

Write-Host ""
Write-Host "✅ Configuration complete" -ForegroundColor Green
Write-Host ""

# Mark setup as complete
New-Item -ItemType File -Path ".setup-complete" -Force | Out-Null

# AWS Cognito Configuration (optional)
if (Get-Command Invoke-CognitoSetup -ErrorAction SilentlyContinue) {
    Write-Host ""
    Invoke-CognitoSetup
    
    # Check if Cognito was configured (AWS_REGION indicates Cognito setup was run)
    $envContent = Get-Content ".env" -ErrorAction SilentlyContinue
    $cognitoRegionLine = $envContent | Where-Object { $_ -match "^AWS_REGION=" }
    
    if ($cognitoRegionLine) {
        $cognitoRegion = ($cognitoRegionLine -split "=", 2)[1].Trim()
        
        if ($cognitoRegion) {
            Write-Host ""
            Write-Host "🔧 Updating stack file with Cognito secrets..." -ForegroundColor Cyan
            # Add Cognito secrets to stack file
            Add-CognitoToStack -StackFile "$ProjectRoot\swarm-stack.yml" -ProjectRoot $ProjectRoot -StackNameUpper $StackNameUpper
        }
    }
}

# =============================================================================
# STACK CONFLICT CHECK
# =============================================================================

Write-Host ""
Write-Host "🔍 Checking for existing stack..." -ForegroundColor Yellow

$stackExists = docker stack ls --format "{{.Name}}" | Select-String -Pattern "^${StackName}$"

if ($stackExists) {
    Write-Host "⚠️  WARNING: Stack '$StackName' is already running!" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "This will interfere with Docker secret creation." -ForegroundColor Yellow
    Write-Host "Secrets cannot be updated while they are in use by a running stack." -ForegroundColor Yellow
    Write-Host ""
    $removeStack = Read-Host "Remove existing stack before continuing? (y/N)"
    
    if ($removeStack -match '^[Yy]$') {
        Write-Host ""
        Write-Host "Removing stack: $StackName" -ForegroundColor Cyan
        docker stack rm $StackName
        
        Write-Host "Waiting for stack to be fully removed..." -ForegroundColor Yellow
        do {
            Write-Host "." -NoNewline
            Start-Sleep -Seconds 2
            $stackStillExists = docker stack ls --format "{{.Name}}" | Select-String -Pattern "^${StackName}$"
        } while ($stackStillExists)
        Write-Host ""
        Write-Host "✅ Stack removed successfully" -ForegroundColor Green
        Write-Host ""
    } else {
        Write-Host ""
        Write-Host "⚠️  Continuing with existing stack running." -ForegroundColor Yellow
        Write-Host "Note: You may encounter errors when creating/updating secrets." -ForegroundColor Yellow
        Write-Host ""
    }
} else {
    Write-Host "✅ No conflicting stack found" -ForegroundColor Green
}

# =============================================================================
# SECRET CREATION
# =============================================================================

$secretsCreated = New-DockerSecrets -DbPasswordSecret $DbPasswordSecret -AdminApiKeySecret $AdminApiKeySecret -BackupRestoreApiKeySecret $BackupRestoreApiKeySecret -BackupDeleteApiKeySecret $BackupDeleteApiKeySecret

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

# Health check (with 20 second wait for initialization)
Test-DeploymentHealth -StackName $StackName -DbType $DbType -ProxyType $ProxyType -ApiUrl $ApiUrl -WaitSeconds 20

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
