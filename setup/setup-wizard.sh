#!/bin/bash

# Swarm Python API Template - Setup Wizard
# Interactive setup script for Linux/Mac
# This script uses modular components for maintainability

set -e

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# Source all modules
source "$SCRIPT_DIR/modules/user-prompts.sh"
source "$SCRIPT_DIR/modules/config-builder.sh"
source "$SCRIPT_DIR/modules/network-check.sh"
source "$SCRIPT_DIR/modules/data-dirs.sh"
source "$SCRIPT_DIR/modules/secret-manager.sh"
source "$SCRIPT_DIR/modules/deploy-stack.sh"
source "$SCRIPT_DIR/modules/health-check.sh"

# Source Cognito setup script if available
if [ -f "${SCRIPT_DIR}/modules/cognito_setup.sh" ]; then
    # shellcheck disable=SC1091
    source "${SCRIPT_DIR}/modules/cognito_setup.sh"
fi

# =============================================================================
# WELCOME & SETUP CHECK
# =============================================================================

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
    if ! prompt_yes_no "Run setup again? This will overwrite configuration" "N"; then
        echo "Setup cancelled."
        exit 0
    fi
    echo ""
fi

# Backup existing files
backup_existing_files "$PROJECT_ROOT"

echo ""
echo "Let's configure your deployment!"
echo ""

# =============================================================================
# CONFIGURATION PHASE - Collect User Input
# =============================================================================

# Database Type
DB_TYPE=$(prompt_database_type)
echo "✅ Selected: $DB_TYPE"
echo ""

# Proxy Type
PROXY_TYPE=$(prompt_proxy_type)
echo "✅ Selected: $PROXY_TYPE"
echo ""

# SSL Mode (only for Traefik)
if [ "$PROXY_TYPE" = "traefik" ]; then
    SSL_MODE=$(prompt_ssl_mode)
    echo "✅ Selected: $SSL_MODE SSL"
    echo ""
else
    SSL_MODE="direct"  # Default for non-Traefik
fi

# Database Mode
DB_MODE=$(prompt_database_mode)
echo "✅ Selected: $DB_MODE"
echo ""

if [ "$DB_MODE" = "local" ]; then
    DEPLOY_DATABASE=true
else
    DEPLOY_DATABASE=false
fi

# Get Traefik network if needed (before building stack file)
if [ "$PROXY_TYPE" = "traefik" ]; then
    TRAEFIK_NETWORK=$(prompt_traefik_network)
fi

# Build configuration files
echo "⚙️  Building configuration files..."
build_env_file "$DB_TYPE" "$DB_MODE" "$PROXY_TYPE" "$PROJECT_ROOT"
build_stack_file "$DB_TYPE" "$DB_MODE" "$PROXY_TYPE" "$PROJECT_ROOT" "$SSL_MODE"

# Replace Traefik network placeholder if using Traefik
if [ "$PROXY_TYPE" = "traefik" ]; then
    update_stack_network "$PROJECT_ROOT/swarm-stack.yml" "$TRAEFIK_NETWORK"
fi

echo ""

# Collect deployment parameters
echo "📝 Deployment Configuration"
echo "==========================="
echo ""

STACK_NAME=$(prompt_stack_name)
DATA_ROOT=$(prompt_data_root "$(pwd)")

if [ "$PROXY_TYPE" = "traefik" ]; then
    API_URL=$(prompt_api_domain)
else
    PUBLISHED_PORT=$(prompt_published_port)
fi

# Docker image
IMAGE_INFO=$(prompt_docker_image)
if [ $? -ne 0 ]; then
    echo "Setup cancelled."
    exit 1
fi
IMAGE_NAME=$(echo "$IMAGE_INFO" | cut -d':' -f1)
IMAGE_VERSION=$(echo "$IMAGE_INFO" | cut -d':' -f2)

# Debug mode
echo ""
read -p "Enable debug mode? (y/N): " ENABLE_DEBUG
if [[ "$ENABLE_DEBUG" =~ ^[Yy]$ ]]; then
    DEBUG_MODE="true"
    echo "✅ Debug mode enabled"
else
    DEBUG_MODE="false"
    echo "✅ Debug mode disabled"
fi

# Update .env with collected values
update_env_values "$PROJECT_ROOT/.env" "STACK_NAME" "$STACK_NAME"
update_env_values "$PROJECT_ROOT/.env" "DATA_ROOT" "$DATA_ROOT"
update_env_values "$PROJECT_ROOT/.env" "IMAGE_NAME" "$IMAGE_NAME"
update_env_values "$PROJECT_ROOT/.env" "IMAGE_VERSION" "$IMAGE_VERSION"
update_env_values "$PROJECT_ROOT/.env" "DEBUG" "$DEBUG_MODE"

if [ "$PROXY_TYPE" = "traefik" ]; then
    update_env_values "$PROJECT_ROOT/.env" "TRAEFIK_NETWORK" "$TRAEFIK_NETWORK"
    update_env_values "$PROJECT_ROOT/.env" "API_URL" "$API_URL"
else
    update_env_values "$PROJECT_ROOT/.env" "PUBLISHED_PORT" "$PUBLISHED_PORT"
fi

# Replicas
echo ""
API_REPLICAS=$(prompt_replicas "API" 1)
update_env_values "$PROJECT_ROOT/.env" "API_REPLICAS" "$API_REPLICAS"

if [ "$DB_MODE" = "local" ]; then
    DB_REPLICAS=$(prompt_replicas "Database" 1)
    
    if [ "$DB_TYPE" = "postgresql" ]; then
        update_env_values "$PROJECT_ROOT/.env" "POSTGRES_REPLICAS" "$DB_REPLICAS"
    elif [ "$DB_TYPE" = "neo4j" ]; then
        update_env_values "$PROJECT_ROOT/.env" "NEO4J_REPLICAS" "$DB_REPLICAS"
    fi
fi

REDIS_REPLICAS=$(prompt_replicas "Redis" 1)
update_env_values "$PROJECT_ROOT/.env" "REDIS_REPLICAS" "$REDIS_REPLICAS"

# Auto-generate secret names from stack name
echo ""
STACK_NAME_UPPER=$(echo "$STACK_NAME" | tr '[:lower:]' '[:upper:]' | sed 's/[^A-Z0-9]/_/g')
DB_PASSWORD_SECRET="${STACK_NAME_UPPER}_DB_PASSWORD"
ADMIN_API_KEY_SECRET="${STACK_NAME_UPPER}_ADMIN_API_KEY"
BACKUP_RESTORE_API_KEY_SECRET="${STACK_NAME_UPPER}_BACKUP_RESTORE_API_KEY"
BACKUP_DELETE_API_KEY_SECRET="${STACK_NAME_UPPER}_BACKUP_DELETE_API_KEY"

echo "Secret names (auto-generated):"
echo "  Database password: $DB_PASSWORD_SECRET"
echo "  Admin API key: $ADMIN_API_KEY_SECRET"
echo "  Backup restore API key: $BACKUP_RESTORE_API_KEY_SECRET"
echo "  Backup delete API key: $BACKUP_DELETE_API_KEY_SECRET"

update_stack_secrets "$PROJECT_ROOT/swarm-stack.yml" "$DB_PASSWORD_SECRET" "$ADMIN_API_KEY_SECRET" "$BACKUP_RESTORE_API_KEY_SECRET" "$BACKUP_DELETE_API_KEY_SECRET"

echo ""
echo "✅ Configuration complete"
echo ""

# Mark setup as complete
touch ".setup-complete"

# AWS Cognito Configuration (optional)
if declare -F run_cognito_setup >/dev/null; then
    echo ""
    run_cognito_setup
fi

# =============================================================================
# STACK CONFLICT CHECK
# =============================================================================

echo ""
echo "🔍 Checking for existing stack..."

if docker stack ls --format "{{.Name}}" | grep -q "^${STACK_NAME}$"; then
    echo "⚠️  WARNING: Stack '$STACK_NAME' is already running!"
    echo ""
    echo "This will interfere with Docker secret creation."
    echo "Secrets cannot be updated while they are in use by a running stack."
    echo ""
    read -p "Remove existing stack before continuing? (y/N): " REMOVE_STACK
    
    if [[ "$REMOVE_STACK" =~ ^[Yy]$ ]]; then
        echo ""
        echo "Removing stack: $STACK_NAME"
        docker stack rm "$STACK_NAME"
        
        echo "Waiting for stack to be fully removed..."
        # Wait for services to be removed
        sleep 2
        while docker stack ls --format "{{.Name}}" | grep -q "^${STACK_NAME}$"; do
            echo -n "."
            sleep 2
        done
        echo ""
        echo "✅ Stack removed successfully"
        echo ""
    else
        echo ""
        echo "⚠️  Continuing with existing stack running."
        echo "Note: You may encounter errors when creating/updating secrets."
        echo ""
    fi
else
    echo "✅ No conflicting stack found"
fi

# =============================================================================
# SECRET CREATION
# =============================================================================

create_docker_secrets "$DB_PASSWORD_SECRET" "$ADMIN_API_KEY_SECRET" "$BACKUP_RESTORE_API_KEY_SECRET" "$BACKUP_DELETE_API_KEY_SECRET"

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

# Health check (with 20 second wait for initialization)
check_deployment_health "$STACK_NAME" "$DB_TYPE" "$PROXY_TYPE" "$API_URL" 20

echo ""
echo "🎉 Setup and deployment complete!"
echo ""
echo "Configuration files created:"
echo "  - .env"
echo "  - swarm-stack.yml"
echo ""
echo "Next steps:"
echo "  - Monitor services: docker stack services $STACK_NAME"
echo "  - View logs: docker service logs ${STACK_NAME}_api"
if [ "$PROXY_TYPE" = "traefik" ]; then
    echo "  - Access API: https://${API_URL}"
else
    echo "  - Access API: http://localhost:${PUBLISHED_PORT}"
fi
echo ""
