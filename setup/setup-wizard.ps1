# Interactive Setup Script for Swarm Python API Template (PowerShell)
# This script helps users configure their Docker Swarm deployment

$ErrorActionPreference = "Stop"

# Get the directory where this script is located (setup/)
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
# Get the project root directory (parent of setup/)
$PROJECT_ROOT = Split-Path -Parent $SCRIPT_DIR
Set-Location $PROJECT_ROOT

Write-Host "🚀 Swarm Python API Template - Initial Setup" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Working directory: $PROJECT_ROOT"
Write-Host ""

# Check if setup is already complete
$SETUP_ALREADY_DONE = $false

if (Test-Path ".setup-complete") {
    $SETUP_ALREADY_DONE = $true
    Write-Host "⚠️  Setup has already been completed (.setup-complete marker found)." -ForegroundColor Yellow
} elseif ((Test-Path ".env") -and (Test-Path "swarm-stack.yml")) {
    $SETUP_ALREADY_DONE = $true
    Write-Host "⚠️  Setup appears to have been done manually (.env and swarm-stack.yml exist)." -ForegroundColor Yellow
}

if ($SETUP_ALREADY_DONE) {
    $RERUN_SETUP = Read-Host "Do you want to run setup again? This will overwrite .env and swarm-stack.yml (y/N)"
    if ($RERUN_SETUP -notmatch "^[Yy]$") {
        Write-Host "Setup cancelled."
        exit 0
    }
    Write-Host ""
}

# Database Type Selection
Write-Host "📊 Database Selection" -ForegroundColor Cyan
Write-Host "--------------------"
Write-Host "Choose your database type:"
Write-Host "1) PostgreSQL (relational database)"
Write-Host "2) Neo4j (graph database)"
Write-Host ""

$DB_CHOICE = Read-Host "Your choice (1-2) [1]"
if ([string]::IsNullOrWhiteSpace($DB_CHOICE)) { $DB_CHOICE = "1" }

switch ($DB_CHOICE) {
    "1" {
        $DB_TYPE = "postgresql"
        Write-Host "✅ Selected: PostgreSQL" -ForegroundColor Green
    }
    "2" {
        $DB_TYPE = "neo4j"
        Write-Host "✅ Selected: Neo4j" -ForegroundColor Green
    }
    default {
        $DB_TYPE = "postgresql"
        Write-Host "⚠️  Invalid choice, defaulting to PostgreSQL" -ForegroundColor Yellow
    }
}

Write-Host ""

# Proxy Selection
Write-Host "🌐 Proxy Configuration" -ForegroundColor Cyan
Write-Host "---------------------"
Write-Host "Choose your proxy/ingress solution:"
Write-Host "1) Traefik (recommended for automatic HTTPS with Let's Encrypt)"
Write-Host "2) No proxy (direct port exposure - you manage your own proxy/load balancer)"
Write-Host ""

$PROXY_CHOICE = Read-Host "Your choice (1-2) [1]"
if ([string]::IsNullOrWhiteSpace($PROXY_CHOICE)) { $PROXY_CHOICE = "1" }

switch ($PROXY_CHOICE) {
    "1" {
        $PROXY_TYPE = "traefik"
        Write-Host "✅ Selected: Traefik (automatic HTTPS)" -ForegroundColor Green
    }
    "2" {
        $PROXY_TYPE = "no-proxy"
        Write-Host "✅ Selected: No proxy (direct port exposure)" -ForegroundColor Green
    }
    default {
        $PROXY_TYPE = "traefik"
        Write-Host "⚠️  Invalid choice, defaulting to Traefik" -ForegroundColor Yellow
    }
}

Write-Host ""

# Database Mode Selection
Write-Host "Choose database deployment mode:"
Write-Host "1) Local database (deploy database alongside API in swarm)"
Write-Host "2) External database (use existing database server)"
Write-Host ""

$DB_MODE_CHOICE = Read-Host "Your choice (1-2) [1]"
if ([string]::IsNullOrWhiteSpace($DB_MODE_CHOICE)) { $DB_MODE_CHOICE = "1" }

switch ($DB_MODE_CHOICE) {
    "1" {
        $DB_MODE = "local"
        $DEPLOY_DATABASE = $true
        Write-Host "✅ Selected: Local database (will deploy in swarm)" -ForegroundColor Green
    }
    "2" {
        $DB_MODE = "external"
        $DEPLOY_DATABASE = $false
        Write-Host "✅ Selected: External database" -ForegroundColor Green
    }
    default {
        $DB_MODE = "local"
        $DEPLOY_DATABASE = $true
        Write-Host "⚠️  Invalid choice, defaulting to local" -ForegroundColor Yellow
    }
}

Write-Host ""

# Build .env file from modular templates
Write-Host "⚙️  Building configuration files..." -ForegroundColor Cyan

# Start with base configuration
Get-Content "setup\env-templates\.env.base.template" | Set-Content ".env"

# Add database-specific configuration
if ($DB_TYPE -eq "postgresql") {
    if ($DB_MODE -eq "local") {
        Get-Content "setup\env-templates\.env.postgres-local.template" | Add-Content ".env"
        $DATABASE_MODULE = "postgres-local.yml"
    } else {
        Get-Content "setup\env-templates\.env.postgres-external.template" | Add-Content ".env"
        $DATABASE_MODULE = "postgres-external.yml"
    }
} else {
    if ($DB_MODE -eq "local") {
        Get-Content "setup\env-templates\.env.neo4j-local.template" | Add-Content ".env"
        $DATABASE_MODULE = "neo4j-local.yml"
    } else {
        Get-Content "setup\env-templates\.env.neo4j-external.template" | Add-Content ".env"
        $DATABASE_MODULE = "neo4j-external.yml"
    }
}

# Add proxy-specific configuration
if ($PROXY_TYPE -eq "traefik") {
    Get-Content "setup\env-templates\.env.proxy-traefik.template" | Add-Content ".env"
    $PROXY_MODULE = "proxy-traefik.yml"
} else {
    Get-Content "setup\env-templates\.env.proxy-none.template" | Add-Content ".env"
    $PROXY_MODULE = "proxy-none.yml"
}

# Create swarm-stack.yml from template with correct modules
Copy-Item "setup\swarm-stack.yml.template" "swarm-stack.yml"
(Get-Content "swarm-stack.yml") -replace "XXX_DATABASE_MODULE_XXX", $DATABASE_MODULE | Set-Content "swarm-stack.yml"
(Get-Content "swarm-stack.yml") -replace "XXX_PROXY_MODULE_XXX", $PROXY_MODULE | Set-Content "swarm-stack.yml"

Write-Host ""

# Docker Image Configuration
Write-Host "📦 Docker Image Configuration" -ForegroundColor Cyan
Write-Host "------------------------------"
Write-Host "This should match the image built from your main python-api-template."
Write-Host ""

$IMAGE_VERIFIED = $false
while (-not $IMAGE_VERIFIED) {
    do {
        $IMAGE_NAME = Read-Host "Enter Docker image name (e.g., username/api-name)"
        if ([string]::IsNullOrWhiteSpace($IMAGE_NAME)) {
            Write-Host "❌ Image name cannot be empty" -ForegroundColor Red
        }
    } while ([string]::IsNullOrWhiteSpace($IMAGE_NAME))

    $IMAGE_VERSION = Read-Host "Enter Docker image version/tag [0.0.1]"
    if ([string]::IsNullOrWhiteSpace($IMAGE_VERSION)) { $IMAGE_VERSION = "0.0.1" }

    Write-Host ""
    Write-Host "🔍 Verifying Docker image: ${IMAGE_NAME}:${IMAGE_VERSION}" -ForegroundColor Cyan
    
    try {
        $pullResult = docker pull "${IMAGE_NAME}:${IMAGE_VERSION}" 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✅ Image successfully pulled and verified" -ForegroundColor Green
            $IMAGE_VERIFIED = $true
        } else {
            throw "Pull failed"
        }
    } catch {
        Write-Host "❌ Could not pull image ${IMAGE_NAME}:${IMAGE_VERSION}" -ForegroundColor Red
        Write-Host ""
        Write-Host "This might be because:"
        Write-Host "  1) The image doesn't exist yet (you need to build and push it)"
        Write-Host "  2) You're not logged in to the registry"
        Write-Host "  3) The image name or version is incorrect"
        Write-Host ""
        Write-Host "What would you like to do?"
        Write-Host "1) Login to Docker registry"
        Write-Host "2) Re-enter image name/version"
        Write-Host "3) Skip verification and continue anyway"
        Write-Host "4) Cancel setup"
        Write-Host ""
        $IMAGE_CHOICE = Read-Host "Your choice (1-4)"
        
        switch ($IMAGE_CHOICE) {
            "1" {
                Write-Host ""
                Write-Host "🔐 Docker Registry Login" -ForegroundColor Cyan
                Write-Host "----------------------"
                Write-Host "For Docker Hub: docker login"
                Write-Host "For other registries: docker login <registry-url>"
                Write-Host ""
                $REGISTRY_URL = Read-Host "Enter registry URL (press Enter for Docker Hub)"
                if ([string]::IsNullOrWhiteSpace($REGISTRY_URL)) {
                    docker login
                } else {
                    docker login $REGISTRY_URL
                }
                Write-Host ""
                Write-Host "Retrying image pull..." -ForegroundColor Cyan
            }
            "2" {
                Write-Host ""
                Write-Host "Re-entering image details..." -ForegroundColor Cyan
                Write-Host ""
            }
            "3" {
                Write-Host ""
                Write-Host "⚠️  Skipping image verification" -ForegroundColor Yellow
                $IMAGE_VERIFIED = $true
            }
            "4" {
                Write-Host "Setup cancelled."
                exit 1
            }
            default {
                Write-Host "Invalid choice, please try again." -ForegroundColor Yellow
                Write-Host ""
            }
        }
    }
}

(Get-Content ".env") -replace "^IMAGE_NAME=.*", "IMAGE_NAME=$IMAGE_NAME" | Set-Content ".env"
(Get-Content ".env") -replace "^IMAGE_VERSION=.*", "IMAGE_VERSION=$IMAGE_VERSION" | Set-Content ".env"

Write-Host "✅ Image configured: ${IMAGE_NAME}:${IMAGE_VERSION}" -ForegroundColor Green
Write-Host ""

# Domain/Port Configuration
if ($PROXY_TYPE -eq "traefik") {
    Write-Host "🌐 Domain Configuration" -ForegroundColor Cyan
    Write-Host "----------------------"
    Write-Host "Enter the domain where your API will be accessible."
    Write-Host ""
    Write-Host "⚠️  IMPORTANT: Make sure your domain/subdomain is already created and" -ForegroundColor Yellow
    Write-Host "   points to your swarm manager's IP address before deploying."
    Write-Host ""
    
    do {
        $API_URL = Read-Host "API domain (e.g., api.example.com)"
        if ([string]::IsNullOrWhiteSpace($API_URL)) {
            Write-Host "❌ Domain cannot be empty" -ForegroundColor Red
        }
    } while ([string]::IsNullOrWhiteSpace($API_URL))
    
    (Get-Content ".env") -replace "^API_URL=.*", "API_URL=$API_URL" | Set-Content ".env"
    Write-Host "✅ API will be accessible at: https://${API_URL}" -ForegroundColor Green
    Write-Host ""
} else {
    Write-Host "🔌 Port Configuration" -ForegroundColor Cyan
    Write-Host "--------------------"
    Write-Host "Configure the port where your API will be accessible."
    Write-Host ""
    
    $PUBLISHED_PORT = Read-Host "Published port on host [8000]"
    if ([string]::IsNullOrWhiteSpace($PUBLISHED_PORT)) { $PUBLISHED_PORT = "8000" }
    
    (Get-Content ".env") -replace "^PUBLISHED_PORT=.*", "PUBLISHED_PORT=$PUBLISHED_PORT" | Set-Content ".env"
    Write-Host "✅ API will be accessible at: http://<your-server-ip>:${PUBLISHED_PORT}" -ForegroundColor Green
    Write-Host ""
}

# Data Root Configuration
Write-Host "💾 Data Storage Configuration" -ForegroundColor Cyan
Write-Host "----------------------------"
Write-Host "Enter the path where persistent data will be stored."
Write-Host "For multi-node swarms, use a shared filesystem like GlusterFS."
Write-Host ""

# Use project root as default data root
$DEFAULT_DATA_ROOT = "$PROJECT_ROOT"

$DATA_ROOT = Read-Host "Data root path [$DEFAULT_DATA_ROOT]"
if ([string]::IsNullOrWhiteSpace($DATA_ROOT)) { $DATA_ROOT = $DEFAULT_DATA_ROOT }

(Get-Content ".env") -replace "^DATA_ROOT=.*", "DATA_ROOT=$DATA_ROOT" | Set-Content ".env"
Write-Host "✅ Data will be stored at: $DATA_ROOT" -ForegroundColor Green
Write-Host ""

# Stack Name Configuration
Write-Host "🏷️  Stack Name Configuration" -ForegroundColor Cyan
Write-Host "---------------------------"
Write-Host "Choose a unique name for your Docker Swarm stack."
Write-Host ""

$DEFAULT_STACK_NAME = "api_production"
$STACK_NAME = Read-Host "Stack name [$DEFAULT_STACK_NAME]"
if ([string]::IsNullOrWhiteSpace($STACK_NAME)) { $STACK_NAME = $DEFAULT_STACK_NAME }

(Get-Content ".env") -replace "^STACK_NAME=.*", "STACK_NAME=$STACK_NAME" | Set-Content ".env"
Write-Host "✅ Stack name: $STACK_NAME" -ForegroundColor Green
Write-Host ""

# Database Credentials
if ($DEPLOY_DATABASE) {
    Write-Host "🔐 Database Credentials (Local Database)" -ForegroundColor Cyan
    Write-Host "---------------------------------------"
    Write-Host "These will be used to create Docker secrets."
    Write-Host ""
    
    if ($DB_TYPE -eq "postgresql") {
        $DB_NAME = Read-Host "Database name [apidb]"
        if ([string]::IsNullOrWhiteSpace($DB_NAME)) { $DB_NAME = "apidb" }
        
        $DB_USER = Read-Host "Database user [apiuser]"
        if ([string]::IsNullOrWhiteSpace($DB_USER)) { $DB_USER = "apiuser" }
        
        $DB_PORT = Read-Host "Database port [5432]"
        if ([string]::IsNullOrWhiteSpace($DB_PORT)) { $DB_PORT = "5432" }
        
        (Get-Content ".env") -replace "^DB_NAME=.*", "DB_NAME=$DB_NAME" | Set-Content ".env"
        (Get-Content ".env") -replace "^DB_USER=.*", "DB_USER=$DB_USER" | Set-Content ".env"
        (Get-Content ".env") -replace "^DB_PORT=.*", "DB_PORT=$DB_PORT" | Set-Content ".env"
        
        Write-Host "✅ PostgreSQL configured" -ForegroundColor Green
    } elseif ($DB_TYPE -eq "neo4j") {
        $DB_USER = Read-Host "Database user [neo4j]"
        if ([string]::IsNullOrWhiteSpace($DB_USER)) { $DB_USER = "neo4j" }
        
        (Get-Content ".env") -replace "^DB_USER=.*", "DB_USER=$DB_USER" | Set-Content ".env"
        
        Write-Host "✅ Neo4j configured" -ForegroundColor Green
    }
    
    Write-Host ""
    Write-Host "⚠️  IMPORTANT: You'll need to create Docker secrets for:" -ForegroundColor Yellow
    Write-Host "   - Database password"
    Write-Host "   - Admin API key"
    Write-Host ""
} else {
    Write-Host "🔐 External Database Configuration" -ForegroundColor Cyan
    Write-Host "---------------------------------"
    Write-Host "Configure connection to your existing database."
    Write-Host ""
    
    if ($DB_TYPE -eq "postgresql") {
        do {
            $DB_HOST = Read-Host "Database host"
            if ([string]::IsNullOrWhiteSpace($DB_HOST)) {
                Write-Host "❌ Database host cannot be empty" -ForegroundColor Red
            }
        } while ([string]::IsNullOrWhiteSpace($DB_HOST))
        
        $DB_PORT = Read-Host "Database port [5432]"
        if ([string]::IsNullOrWhiteSpace($DB_PORT)) { $DB_PORT = "5432" }
        
        $DB_NAME = Read-Host "Database name [apidb]"
        if ([string]::IsNullOrWhiteSpace($DB_NAME)) { $DB_NAME = "apidb" }
        
        $DB_USER = Read-Host "Database user [apiuser]"
        if ([string]::IsNullOrWhiteSpace($DB_USER)) { $DB_USER = "apiuser" }
        
        $DB_PASSWORD = Read-Host "Database password" -AsSecureString
        $DB_PASSWORD_PLAIN = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($DB_PASSWORD))
        
        (Get-Content ".env") -replace "^DB_HOST=.*", "DB_HOST=$DB_HOST" | Set-Content ".env"
        (Get-Content ".env") -replace "^DB_PORT=.*", "DB_PORT=$DB_PORT" | Set-Content ".env"
        (Get-Content ".env") -replace "^DB_NAME=.*", "DB_NAME=$DB_NAME" | Set-Content ".env"
        (Get-Content ".env") -replace "^DB_USER=.*", "DB_USER=$DB_USER" | Set-Content ".env"
        (Get-Content ".env") -replace "^DB_PASSWORD=.*", "DB_PASSWORD=$DB_PASSWORD_PLAIN" | Set-Content ".env"
        
        Write-Host "✅ PostgreSQL external connection configured" -ForegroundColor Green
    } elseif ($DB_TYPE -eq "neo4j") {
        do {
            $NEO4J_URL = Read-Host "Neo4j URL (e.g., bolt://host``:7687)"
            if ([string]::IsNullOrWhiteSpace($NEO4J_URL)) {
                Write-Host "❌ Neo4j URL cannot be empty" -ForegroundColor Red
            }
        } while ([string]::IsNullOrWhiteSpace($NEO4J_URL))
        
        $DB_USER = Read-Host "Database user [neo4j]"
        if ([string]::IsNullOrWhiteSpace($DB_USER)) { $DB_USER = "neo4j" }
        
        $DB_PASSWORD = Read-Host "Database password" -AsSecureString
        $DB_PASSWORD_PLAIN = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($DB_PASSWORD))
        
        (Get-Content ".env") -replace "^NEO4J_URL=.*", "NEO4J_URL=$NEO4J_URL" | Set-Content ".env"
        (Get-Content ".env") -replace "^DB_USER=.*", "DB_USER=$DB_USER" | Set-Content ".env"
        (Get-Content ".env") -replace "^DB_PASSWORD=.*", "DB_PASSWORD=$DB_PASSWORD_PLAIN" | Set-Content ".env"
        
        Write-Host "✅ Neo4j external connection configured" -ForegroundColor Green
    }
    
    Write-Host ""
    Write-Host "⚠️  IMPORTANT: You'll still need to create Docker secret for:" -ForegroundColor Yellow
    Write-Host "   - Admin API key"
    Write-Host ""
}

# Replicas Configuration
Write-Host "📊 Replica Configuration" -ForegroundColor Cyan
Write-Host "-----------------------"
Write-Host "Configure the number of replicas for each service."
Write-Host ""

$API_REPLICAS = Read-Host "API replicas [1]"
if ([string]::IsNullOrWhiteSpace($API_REPLICAS)) { $API_REPLICAS = "1" }
(Get-Content ".env") -replace "^API_REPLICAS=.*", "API_REPLICAS=$API_REPLICAS" | Set-Content ".env"

if ($DEPLOY_DATABASE) {
    if ($DB_TYPE -eq "postgresql") {
        $DB_REPLICAS = Read-Host "PostgreSQL replicas [1]"
        if ([string]::IsNullOrWhiteSpace($DB_REPLICAS)) { $DB_REPLICAS = "1" }
        (Get-Content ".env") -replace "^POSTGRES_REPLICAS=.*", "POSTGRES_REPLICAS=$DB_REPLICAS" | Set-Content ".env"
    } elseif ($DB_TYPE -eq "neo4j") {
        $DB_REPLICAS = Read-Host "Neo4j replicas [1]"
        if ([string]::IsNullOrWhiteSpace($DB_REPLICAS)) { $DB_REPLICAS = "1" }
        (Get-Content ".env") -replace "^NEO4J_REPLICAS=.*", "NEO4J_REPLICAS=$DB_REPLICAS" | Set-Content ".env"
    }
}

$REDIS_REPLICAS = Read-Host "Redis replicas [1]"
if ([string]::IsNullOrWhiteSpace($REDIS_REPLICAS)) { $REDIS_REPLICAS = "1" }
(Get-Content ".env") -replace "^REDIS_REPLICAS=.*", "REDIS_REPLICAS=$REDIS_REPLICAS" | Set-Content ".env"

Write-Host "✅ Replicas configured" -ForegroundColor Green
Write-Host ""

# Secret Names Configuration
Write-Host "🔑 Docker Secrets Configuration" -ForegroundColor Cyan
Write-Host "------------------------------"
Write-Host "Enter names for Docker secrets (you'll create these manually)."
Write-Host ""

# Convert stack name to uppercase and replace non-alphanumeric chars with underscore
$STACK_NAME_UPPER = $STACK_NAME.ToUpper() -replace '[^A-Z0-9]', '_'

$DB_PASSWORD_SECRET = Read-Host "Database password secret name [DB_PASSWORD_$STACK_NAME_UPPER]"
if ([string]::IsNullOrWhiteSpace($DB_PASSWORD_SECRET)) { $DB_PASSWORD_SECRET = "DB_PASSWORD_$STACK_NAME_UPPER" }

$ADMIN_API_KEY_SECRET = Read-Host "Admin API key secret name [ADMIN_API_KEY_$STACK_NAME_UPPER]"
if ([string]::IsNullOrWhiteSpace($ADMIN_API_KEY_SECRET)) { $ADMIN_API_KEY_SECRET = "ADMIN_API_KEY_$STACK_NAME_UPPER" }

# Replace secret placeholders in swarm-stack.yml
(Get-Content "swarm-stack.yml") -replace "XXX_CHANGE_ME_DB_PASSWORD_XXX", $DB_PASSWORD_SECRET | Set-Content "swarm-stack.yml"
(Get-Content "swarm-stack.yml") -replace "XXX_CHANGE_ME_ADMIN_API_KEY_XXX", $ADMIN_API_KEY_SECRET | Set-Content "swarm-stack.yml"

Write-Host "✅ Secret names configured" -ForegroundColor Green
Write-Host ""

# Mark setup as complete
"" | Set-Content ".setup-complete"

# Summary
Write-Host "=" -NoNewline -ForegroundColor Green
Write-Host "=" * 60 -ForegroundColor Green
Write-Host "✅ Setup Complete!" -ForegroundColor Green
Write-Host "=" * 60 -ForegroundColor Green
Write-Host ""
Write-Host "Configuration Summary:" -ForegroundColor Cyan
Write-Host "  Database:     $DB_TYPE ($DB_MODE)"
Write-Host "  Proxy:        $PROXY_TYPE"
Write-Host "  Stack Name:   $STACK_NAME"
Write-Host "  Image:        ${IMAGE_NAME}:${IMAGE_VERSION}"
if ($PROXY_TYPE -eq "traefik") {
    Write-Host "  Domain:       $API_URL"
} else {
    Write-Host "  Port:         $PUBLISHED_PORT"
}
Write-Host "  Data Root:    $DATA_ROOT"
Write-Host ""

# Next Steps
Write-Host "Next Steps:" -ForegroundColor Cyan
Write-Host ""
Write-Host "1. Create Docker secrets:" -ForegroundColor Yellow
Write-Host "   docker secret create $DB_PASSWORD_SECRET <password-file>"
Write-Host "   docker secret create $ADMIN_API_KEY_SECRET <api-key-file>"
Write-Host ""
Write-Host "2. Deploy to Docker Swarm:" -ForegroundColor Yellow
Write-Host "   docker stack deploy -c swarm-stack.yml $STACK_NAME"
Write-Host ""
Write-Host "3. Check deployment status:" -ForegroundColor Yellow
Write-Host "   docker stack services $STACK_NAME"
Write-Host ""
Write-Host "4. View logs:" -ForegroundColor Yellow
Write-Host "   docker service logs -f ${STACK_NAME}_api"
Write-Host ""

if ($PROXY_TYPE -eq "traefik") {
    Write-Host "5. Access your API:" -ForegroundColor Yellow
    Write-Host "   https://${API_URL}"
} else {
    Write-Host "5. Access your API:" -ForegroundColor Yellow
    Write-Host "   http://<your-server-ip>:${PUBLISHED_PORT}"
}

Write-Host ""
Write-Host "For more information, see README.md" -ForegroundColor Cyan
Write-Host ""
