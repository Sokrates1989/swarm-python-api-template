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
Import-Module "$ScriptDir\modules\stack-conflict-check.ps1" -Force
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

# Build configuration files
Write-Host "⚙️  Building configuration files..." -ForegroundColor Cyan
New-EnvFile -DbType $DbType -DbMode $DbMode -ProxyType $ProxyType -ProjectRoot $ProjectRoot
New-StackFile -DbType $DbType -DbMode $DbMode -ProxyType $ProxyType -ProjectRoot $ProjectRoot -SslMode $SslMode

Write-Host ""

Write-Host "📝 Deployment Configuration" -ForegroundColor Cyan
Write-Host "==========================="
Write-Host ""
Write-Host "How would you like to configure deployment settings?"
Write-Host "1) Edit .env file (built from templates) and let the wizard read values from it"
Write-Host "2) Answer questions interactively now (recommended)"
Write-Host ""
$configMode = Read-Host "Your choice (1-2) [2]"
if ([string]::IsNullOrWhiteSpace($configMode)) { $configMode = "2" }

$envFile = Join-Path $ProjectRoot ".env"

if ($configMode -eq "1") {
    $editor = $env:EDITOR
    if ([string]::IsNullOrWhiteSpace($editor)) { $editor = "notepad" }
    Write-Host "Opening .env in editor: $editor" -ForegroundColor Cyan
    & $editor $envFile
    Write-Host ""

    $envContent = Get-Content $envFile -Raw

    if ($envContent -match "STACK_NAME=(.+)") { $StackName = $matches[1].Trim() } else { $StackName = "python-api-template" }
    if ($envContent -match "DATA_ROOT=(.+)") { $DataRoot = $matches[1].Trim() } else { $DataRoot = "/gluster_storage/swarm/python-api-template/api.example.com" }

    if ($ProxyType -eq "traefik") {
        if ($envContent -match "API_URL=(.+)") { $ApiUrl = $matches[1].Trim() } else { $ApiUrl = "" }
        if ($envContent -match "TRAEFIK_NETWORK=(.+)") { $TraefikNetwork = $matches[1].Trim() } else { $TraefikNetwork = "" }

        if ([string]::IsNullOrWhiteSpace($ApiUrl)) {
            $ApiUrl = Get-ApiDomain
            Update-EnvValue -EnvFile "$ProjectRoot\.env" -Key "API_URL" -Value $ApiUrl
        }
        if ([string]::IsNullOrWhiteSpace($TraefikNetwork)) {
            $TraefikNetwork = Get-TraefikNetwork
            Update-EnvValue -EnvFile "$ProjectRoot\.env" -Key "TRAEFIK_NETWORK" -Value $TraefikNetwork
        }
        Update-StackNetwork -StackFile "$ProjectRoot\swarm-stack.yml" -TraefikNetwork $TraefikNetwork
    }
    else {
        if ($envContent -match "PUBLISHED_PORT=(.+)") { $PublishedPort = $matches[1].Trim() } else { $PublishedPort = "8000" }
    }
}
else {
    $StackName = Get-StackName
    $DataRoot = Get-DataRoot (Get-Location).Path

    if ($ProxyType -eq "traefik") {
        $ApiUrl = Get-ApiDomain
        $TraefikNetwork = Get-TraefikNetwork
        Update-StackNetwork -StackFile "$ProjectRoot\swarm-stack.yml" -TraefikNetwork $TraefikNetwork
    } else {
        $PublishedPort = Get-PublishedPort
    }

    $ImageInfo = Get-DockerImage
    if ($null -eq $ImageInfo) {
        Write-Host "Setup cancelled."
        exit 1
    }
    $ImageName = $ImageInfo.Name
    $ImageVersion = $ImageInfo.Version

    Write-Host ""
    $EnableDebug = Read-Host "Enable debug mode? (y/N)"
    if ($EnableDebug -match '^[Yy]$') {
        $DebugMode = "true"
        Write-Host "✅ Debug mode enabled" -ForegroundColor Green
    } else {
        $DebugMode = "false"
        Write-Host "✅ Debug mode disabled" -ForegroundColor Green
    }

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
}

if ($configMode -ne "1") {
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
}

# Auto-generate secret names from stack name
Write-Host ""
$StackNameUpper = $StackName.ToUpper() -replace '[^A-Z0-9]', '_'
$DbPasswordSecret = "${StackNameUpper}_DB_PASSWORD"
$AdminApiKeySecret = "${StackNameUpper}_ADMIN_API_KEY"
$BackupRestoreApiKeySecret = "${StackNameUpper}_BACKUP_RESTORE_API_KEY"
$BackupDeleteApiKeySecret = "${StackNameUpper}_BACKUP_DELETE_API_KEY"

Write-Host "Secret names (auto-generated):"
Write-Host "  Database password: $DbPasswordSecret"
Write-Host "  Admin API key: $AdminApiKeySecret"
Write-Host "  Backup restore API key: $BackupRestoreApiKeySecret"
Write-Host "  Backup delete API key: $BackupDeleteApiKeySecret"

Update-StackSecrets -StackFile "$ProjectRoot\swarm-stack.yml" -DbPasswordSecret $DbPasswordSecret -AdminApiKeySecret $AdminApiKeySecret -BackupRestoreApiKeySecret $BackupRestoreApiKeySecret -BackupDeleteApiKeySecret $BackupDeleteApiKeySecret

Write-Host ""
Write-Host "✅ Configuration complete" -ForegroundColor Green
Write-Host ""

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

Test-StackConflict -StackName $StackName

# =============================================================================
# SECRET CREATION
# =============================================================================

Write-Host ""
Write-Host "Secrets Setup" -ForegroundColor Cyan
Write-Host "================"
Write-Host ""
Write-Host "How would you like to configure secrets?"
Write-Host "1) Edit secrets.env from template and create secrets from file now"
Write-Host "2) Enter secrets interactively now (recommended)"
Write-Host ""
$secretsMode = Read-Host "Your choice (1-2) [2]"
if ([string]::IsNullOrWhiteSpace($secretsMode)) { $secretsMode = "2" }

$secretsFile = Join-Path $ProjectRoot "secrets.env"
$secretsTemplate = Join-Path $ProjectRoot "setup\templates\secrets.env.template"

switch ($secretsMode) {
    "1" {
        if (-not (Test-Path $secretsFile)) {
            if (Test-Path $secretsTemplate) {
                Copy-Item $secretsTemplate $secretsFile -Force
            } else {
                Write-Host "Template $secretsTemplate not found" -ForegroundColor Red
                exit 1
            }
        }
        $editor = $env:EDITOR
        if ([string]::IsNullOrWhiteSpace($editor)) { $editor = "notepad" }
        & $editor $secretsFile
        $secretsCreated = New-SecretsFromFile -DbPasswordSecret $DbPasswordSecret -AdminApiKeySecret $AdminApiKeySecret -BackupRestoreApiKeySecret $BackupRestoreApiKeySecret -BackupDeleteApiKeySecret $BackupDeleteApiKeySecret -SecretsFile $secretsFile -TemplatePath $secretsTemplate
    }
    default {
        $secretsCreated = New-DockerSecrets -DbPasswordSecret $DbPasswordSecret -AdminApiKeySecret $AdminApiKeySecret -BackupRestoreApiKeySecret $BackupRestoreApiKeySecret -BackupDeleteApiKeySecret $BackupDeleteApiKeySecret
    }
}

if (-not $secretsCreated) {
    Write-Host "Required secrets are missing. Cannot proceed." -ForegroundColor Red
    exit 1
}

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

# Mark setup as complete
New-Item -ItemType File -Path ".setup-complete" -Force | Out-Null

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
