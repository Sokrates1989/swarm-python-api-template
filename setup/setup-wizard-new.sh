#!/bin/bash

# Interactive Setup Script for Swarm Python API Template
# This script coordinates the setup process using modular components

set -e

# Get the directory where this script is located (setup/)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# Get the project root directory (parent of setup/)
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# Source modules
source "$SCRIPT_DIR/modules/network-check.sh"
source "$SCRIPT_DIR/modules/data-dirs.sh"
source "$SCRIPT_DIR/modules/deploy-stack.sh"

echo "🚀 Swarm Python API Template - Setup Wizard"
echo "============================================"
echo ""
echo "This wizard will guide you through the complete setup and deployment."
echo ""

# Check if setup is already complete
SETUP_ALREADY_DONE=false

if [ -f .setup-complete ]; then
    SETUP_ALREADY_DONE=true
    echo "⚠️  Setup has already been completed."
elif [ -f .env ] && [ -f swarm-stack.yml ]; then
    SETUP_ALREADY_DONE=true
    echo "⚠️  Setup appears to have been done manually."
fi

if [ "$SETUP_ALREADY_DONE" = true ]; then
    read -p "Run setup again? This will overwrite configuration (y/N): " RERUN_SETUP
    if [[ ! "$RERUN_SETUP" =~ ^[Yy]$ ]]; then
        echo "Setup cancelled."
        exit 0
    fi
    echo ""
fi

# Backup existing files
if [ -f .env ]; then
    BACKUP_FILE=".env.backup.$(date +%Y%m%d_%H%M%S)"
    cp .env "$BACKUP_FILE"
    echo "📋 Backed up .env to $BACKUP_FILE"
fi

if [ -f swarm-stack.yml ]; then
    BACKUP_FILE="swarm-stack.yml.backup.$(date +%Y%m%d_%H%M%S)"
    cp swarm-stack.yml "$BACKUP_FILE"
    echo "📋 Backed up swarm-stack.yml to $BACKUP_FILE"
fi

echo ""
echo "Let's configure your deployment!"
echo ""

# =============================================================================
# CONFIGURATION PHASE
# =============================================================================

# Database Type
echo "🗄️  Database Configuration"
echo "-------------------------"
echo "1) PostgreSQL (relational data)"
echo "2) Neo4j (graph data)"
echo ""
read -p "Your choice (1-2) [1]: " DB_CHOICE
DB_CHOICE="${DB_CHOICE:-1}"

case $DB_CHOICE in
    1) DB_TYPE="postgresql" ;;
    2) DB_TYPE="neo4j" ;;
    *) DB_TYPE="postgresql" ;;
esac
echo "✅ Selected: $DB_TYPE"
echo ""

# Proxy Type
echo "🌐 Proxy Configuration"
echo "---------------------"
echo "1) Traefik (automatic HTTPS)"
echo "2) No proxy (direct port)"
echo ""
read -p "Your choice (1-2) [1]: " PROXY_CHOICE
PROXY_CHOICE="${PROXY_CHOICE:-1}"

case $PROXY_CHOICE in
    1) PROXY_TYPE="traefik" ;;
    2) PROXY_TYPE="no-proxy" ;;
    *) PROXY_TYPE="traefik" ;;
esac
echo "✅ Selected: $PROXY_TYPE"
echo ""

# Database Mode
echo "Choose database mode:"
echo "1) Local (deploy in swarm)"
echo "2) External (existing server)"
echo ""
read -p "Your choice (1-2) [1]: " DB_MODE_CHOICE
DB_MODE_CHOICE="${DB_MODE_CHOICE:-1}"

case $DB_MODE_CHOICE in
    1) DB_MODE="local"; DEPLOY_DATABASE=true ;;
    2) DB_MODE="external"; DEPLOY_DATABASE=false ;;
    *) DB_MODE="local"; DEPLOY_DATABASE=true ;;
esac
echo "✅ Selected: $DB_MODE"
echo ""

# Build configuration files
echo "⚙️  Building configuration..."
cat "setup/env-templates/.env.base.template" > .env

if [ "$DB_TYPE" = "postgresql" ]; then
    if [ "$DB_MODE" = "local" ]; then
        cat "setup/env-templates/.env.postgres.template" >> .env
    else
        cat "setup/env-templates/.env.postgres-external.template" >> .env
    fi
elif [ "$DB_TYPE" = "neo4j" ]; then
    if [ "$DB_MODE" = "local" ]; then
        cat "setup/env-templates/.env.neo4j.template" >> .env
    else
        cat "setup/env-templates/.env.neo4j-external.template" >> .env
    fi
fi

# Build swarm-stack.yml
cat "setup/compose-modules/base.yml" > swarm-stack.yml

if [ "$DEPLOY_DATABASE" = true ]; then
    if [ "$DB_TYPE" = "postgresql" ]; then
        cat "setup/compose-modules/postgres.yml" >> swarm-stack.yml
    elif [ "$DB_TYPE" = "neo4j" ]; then
        cat "setup/compose-modules/neo4j.yml" >> swarm-stack.yml
    fi
fi

cat "setup/compose-modules/redis.yml" >> swarm-stack.yml

if [ "$PROXY_TYPE" = "traefik" ]; then
    cat "setup/compose-modules/traefik-labels.yml" >> swarm-stack.yml
else
    cat "setup/compose-modules/no-proxy-ports.yml" >> swarm-stack.yml
fi

echo "✅ Configuration files created"
echo ""

# Collect user inputs
read -p "Stack name [python-api-template]: " STACK_NAME
STACK_NAME="${STACK_NAME:-python-api-template}"

read -p "Data root directory [$(pwd)]: " DATA_ROOT
DATA_ROOT="${DATA_ROOT:-$(pwd)}"

if [ "$PROXY_TYPE" = "traefik" ]; then
    read -p "API domain (e.g., api.example.com): " API_URL
    while [ -z "$API_URL" ]; do
        echo "⚠️  Domain is required for Traefik"
        read -p "API domain: " API_URL
    done
else
    read -p "Published port [8000]: " PUBLISHED_PORT
    PUBLISHED_PORT="${PUBLISHED_PORT:-8000}"
fi

# Docker image
echo ""
echo "🐳 Docker Image Configuration"
echo "----------------------------"

IMAGE_VERIFIED=false
while [ "$IMAGE_VERIFIED" = false ]; do
    read -p "Docker image name (e.g., sokrates1989/python-api-template): " IMAGE_NAME
    read -p "Image version [latest]: " IMAGE_VERSION
    IMAGE_VERSION="${IMAGE_VERSION:-latest}"
    
    echo "Verifying image: ${IMAGE_NAME}:${IMAGE_VERSION}"
    docker pull "${IMAGE_NAME}:${IMAGE_VERSION}" 2>&1
    
    if [ $? -eq 0 ]; then
        echo "✅ Image verified"
        IMAGE_VERIFIED=true
    else
        echo ""
        echo "❌ Failed to pull image"
        echo "1) Login to Docker registry"
        echo "2) Re-enter image info"
        echo "3) Skip verification"
        echo "4) Cancel setup"
        read -p "Your choice (1-4): " IMAGE_CHOICE
        
        case $IMAGE_CHOICE in
            1) docker login ;;
            2) continue ;;
            3) IMAGE_VERIFIED=true ;;
            4) exit 1 ;;
        esac
    fi
done

# Update .env
sed -i "s|^STACK_NAME=.*|STACK_NAME=$STACK_NAME|" .env
sed -i "s|^DATA_ROOT=.*|DATA_ROOT=$DATA_ROOT|" .env
sed -i "s|^IMAGE_NAME=.*|IMAGE_NAME=$IMAGE_NAME|" .env
sed -i "s|^IMAGE_VERSION=.*|IMAGE_VERSION=$IMAGE_VERSION|" .env

if [ "$PROXY_TYPE" = "traefik" ]; then
    sed -i "s|^API_URL=.*|API_URL=$API_URL|" .env
else
    sed -i "s|^PUBLISHED_PORT=.*|PUBLISHED_PORT=$PUBLISHED_PORT|" .env
fi

# Replicas
read -p "API replicas [1]: " API_REPLICAS
API_REPLICAS="${API_REPLICAS:-1}"
sed -i "s|^API_REPLICAS=.*|API_REPLICAS=$API_REPLICAS|" .env

if [ "$DEPLOY_DATABASE" = true ]; then
    read -p "Database replicas [1]: " DB_REPLICAS
    DB_REPLICAS="${DB_REPLICAS:-1}"
    
    if [ "$DB_TYPE" = "postgresql" ]; then
        sed -i "s|^POSTGRES_REPLICAS=.*|POSTGRES_REPLICAS=$DB_REPLICAS|" .env
    elif [ "$DB_TYPE" = "neo4j" ]; then
        sed -i "s|^NEO4J_REPLICAS=.*|NEO4J_REPLICAS=$DB_REPLICAS|" .env
    fi
fi

read -p "Redis replicas [1]: " REDIS_REPLICAS
REDIS_REPLICAS="${REDIS_REPLICAS:-1}"
sed -i "s|^REDIS_REPLICAS=.*|REDIS_REPLICAS=$REDIS_REPLICAS|" .env

# Secret names
STACK_NAME_UPPER=$(echo "$STACK_NAME" | tr '[:lower:]' '[:upper:]' | sed 's/[^A-Z0-9]/_/g')

read -p "Database password secret [${STACK_NAME_UPPER}_DB_PASSWORD]: " DB_PASSWORD_SECRET
DB_PASSWORD_SECRET="${DB_PASSWORD_SECRET:-${STACK_NAME_UPPER}_DB_PASSWORD}"

read -p "Admin API key secret [${STACK_NAME_UPPER}_ADMIN_API_KEY]: " ADMIN_API_KEY_SECRET
ADMIN_API_KEY_SECRET="${ADMIN_API_KEY_SECRET:-${STACK_NAME_UPPER}_ADMIN_API_KEY}"

sed -i "s|XXX_CHANGE_ME_DB_PASSWORD_XXX|$DB_PASSWORD_SECRET|g" swarm-stack.yml
sed -i "s|XXX_CHANGE_ME_ADMIN_API_KEY_XXX|$ADMIN_API_KEY_SECRET|g" swarm-stack.yml

echo ""
echo "✅ Configuration complete"
echo ""

# Mark setup as complete
touch .setup-complete

# =============================================================================
# SECRET CREATION
# =============================================================================

echo "🔑 Create Docker Secrets"
echo "======================="
echo ""

read -p "Create secrets now? (Y/n): " CREATE_SECRETS
if [[ ! "$CREATE_SECRETS" =~ ^[Nn]$ ]]; then
    # Detect editor
    if command -v nano &> /dev/null; then
        EDITOR="nano"
    elif command -v vi &> /dev/null; then
        EDITOR="vi"
    elif command -v vim &> /dev/null; then
        EDITOR="vim"
    else
        echo "❌ No text editor found"
        exit 1
    fi
    
    echo ""
    echo "Creating: $DB_PASSWORD_SECRET"
    read -p "Press any key to open editor..." -n 1 -r
    echo ""
    $EDITOR secret.txt
    docker secret create "$DB_PASSWORD_SECRET" secret.txt 2>/dev/null && echo "✅ Created" || echo "⚠️  May already exist"
    rm -f secret.txt
    
    echo ""
    echo "Creating: $ADMIN_API_KEY_SECRET"
    read -p "Press any key to open editor..." -n 1 -r
    echo ""
    $EDITOR secret.txt
    docker secret create "$ADMIN_API_KEY_SECRET" secret.txt 2>/dev/null && echo "✅ Created" || echo "⚠️  May already exist"
    rm -f secret.txt
    
    echo ""
    echo "✅ Secrets created"
    echo ""
fi

# =============================================================================
# DEPLOYMENT PHASE
# =============================================================================

# Network verification
network_verify "$API_URL" "$PROXY_TYPE"
if [ $? -ne 0 ]; then
    echo "❌ Network verification failed"
    exit 1
fi

# Create data directories
create_data_directories "$DATA_ROOT" "$DB_TYPE"
if [ $? -ne 0 ]; then
    echo "❌ Failed to create data directories"
    exit 1
fi

# Deploy stack
deploy_stack "$STACK_NAME" "swarm-stack.yml"
if [ $? -ne 0 ]; then
    echo "❌ Deployment failed"
    exit 1
fi

# Health check
check_deployment_health "$STACK_NAME" "$DB_TYPE" "$PROXY_TYPE" "$API_URL"

echo ""
echo "🎉 Setup and deployment complete!"
echo ""
