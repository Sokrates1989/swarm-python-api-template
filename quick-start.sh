#!/bin/bash
#
# quick-start.sh
#
# Quick start tool for Swarm Python API Template:
# 1. Checks Docker installation
# 2. Runs interactive setup if needed
# 3. Provides deployment and management options

set -e

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source modules
source "${SCRIPT_DIR}/setup/modules/secret-manager.sh"
source "${SCRIPT_DIR}/setup/modules/health-check.sh"
source "${SCRIPT_DIR}/setup/modules/stack-conflict-check.sh"
source "${SCRIPT_DIR}/setup/modules/deploy-stack.sh"
source "${SCRIPT_DIR}/setup/modules/config-builder.sh"

# Source Cognito setup script if available
cognito_script="${SCRIPT_DIR}/setup/modules/cognito_setup.sh"
if [ -f "$cognito_script" ]; then
    # shellcheck disable=SC1091
    source "$cognito_script"
fi

echo "🚀 Swarm Python API Template - Quick Start"
echo "==========================================="
echo ""

# Docker availability check
echo "🔍 Checking Docker installation..."
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed!"
    echo "📥 Please install Docker from: https://www.docker.com/get-started"
    exit 1
fi

# Docker daemon check
if ! docker info &> /dev/null; then
    echo "❌ Docker daemon is not running!"
    echo "🔄 Please start Docker Desktop or the Docker service"
    exit 1
fi

# Docker Compose check
if ! docker compose version &> /dev/null; then
    echo "❌ Docker Compose is not available!"
    echo "📥 Please install a current Docker version with Compose plugin"
    exit 1
fi

echo "✅ Docker is installed and running"
echo ""

# Check if initial setup is needed (same logic as setup wizard)
SETUP_DONE=false
if [ -f .setup-complete ]; then
    SETUP_DONE=true
elif [ -f .env ] && [ -f swarm-stack.yml ]; then
    SETUP_DONE=true
fi

if [ "$SETUP_DONE" = false ]; then
    echo "🚀 First-time setup detected!"
    echo ""
    echo "This appears to be your first time setting up this deployment."
    echo "Would you like to run the interactive setup wizard?"
    echo ""
    echo "The setup wizard will help you configure:"
    echo "  - Database type (PostgreSQL or Neo4j)"
    echo "  - Proxy type (Traefik or no-proxy)"
    echo "  - Database mode (local or external)"
    echo "  - Docker image and version"
    echo "  - Domain/port configuration"
    echo "  - Swarm stack settings"
    echo ""
    
    read -p "Run setup wizard now? (Y/n): " runSetup
    if [[ ! "$runSetup" =~ ^[Nn]$ ]]; then
        echo ""
        echo "Starting setup wizard..."
        ./setup/setup-wizard.sh
        echo ""
    else
        echo ""
        echo "⚠️  Setup wizard skipped."
        echo "You'll need to manually configure .env and swarm-stack.yml"
        echo "See README.md for manual setup instructions."
        echo ""
        exit 0
    fi
    echo ""
fi

# Check if configuration files exist
if [ ! -f .env ]; then
    echo "❌ .env file not found!"
    echo "Please run the setup wizard or create .env manually."
    exit 1
fi

if [ ! -f swarm-stack.yml ]; then
    echo "❌ swarm-stack.yml not found!"
    echo "Please run the setup wizard or create swarm-stack.yml manually."
    exit 1
fi

# Read configuration from .env
STACK_NAME=$(grep "^STACK_NAME=" .env 2>/dev/null | cut -d'=' -f2 | tr -d ' "' || echo "api_production")
API_URL=$(grep "^API_URL=" .env 2>/dev/null | cut -d'=' -f2 | tr -d ' "' || echo "api.example.com")
DB_TYPE=$(grep "^DB_TYPE=" .env 2>/dev/null | cut -d'=' -f2 | tr -d ' "' || echo "postgresql")
PROXY_TYPE=$(grep "^PROXY_TYPE=" .env 2>/dev/null | cut -d'=' -f2 | tr -d ' "' || echo "none")
IMAGE_NAME=$(grep "^IMAGE_NAME=" .env 2>/dev/null | cut -d'=' -f2 | tr -d ' "' || echo "")
IMAGE_VERSION=$(grep "^IMAGE_VERSION=" .env 2>/dev/null | cut -d'=' -f2 | tr -d ' "' || echo "")

echo "📋 Current Configuration"
echo "========================"
echo "Stack Name:     $STACK_NAME"
echo "API Domain:     $API_URL"
echo "Database Type:  $DB_TYPE"
echo "Docker Image:   $IMAGE_NAME:$IMAGE_VERSION"
echo ""

# Main menu
echo "Choose an option:"
echo "1) Deploy to Docker Swarm"
echo "2) Check deployment status"
echo "3) View service logs"
echo "4) Update API image"
echo "5) Scale services"
echo "6) Remove deployment"
echo "7) Re-run setup wizard"
echo "8) Manage Docker secrets"
if declare -F run_cognito_setup >/dev/null; then
    echo "9) Configure AWS Cognito"
    echo "10) Exit"
else
    echo "9) Exit"
fi
echo ""
if declare -F run_cognito_setup >/dev/null; then
    read -p "Your choice (1-10): " choice
else
    read -p "Your choice (1-9): " choice
fi

case $choice in
    1)
        echo "🚀 Deploying to Docker Swarm..."
        echo ""
        echo "⚠️  Make sure you have:"
        echo "   - Created Docker secrets"
        echo "   - Configured your domain DNS"
        echo "   - Created data directories"
        echo ""
        
        # Use the deploy-stack module for consistent deployment with absolute stack path
        STACK_FILE="$(pwd)/swarm-stack.yml"
        deploy_stack "$STACK_NAME" "$STACK_FILE"
        ;;
    2)
        echo "🏥 Running deployment health check..."
        echo ""
        check_deployment_health "$STACK_NAME" "$DB_TYPE" "$PROXY_TYPE" "$API_URL"
        ;;
    3)
        echo "📜 Service Logs"
        echo ""
        echo "Which service logs do you want to view?"
        echo "1) API"
        echo "2) Database"
        echo "3) Redis"
        echo "4) All"
        echo ""
        read -p "Your choice (1-4): " log_choice
        
        case $log_choice in
            1)
                docker service logs -f "${STACK_NAME}_api"
                ;;
            2)
                if [ "$DB_TYPE" = "neo4j" ]; then
                    docker service logs -f "${STACK_NAME}_neo4j"
                else
                    docker service logs -f "${STACK_NAME}_postgres"
                fi
                ;;
            3)
                docker service logs -f "${STACK_NAME}_redis"
                ;;
            4)
                docker service logs -f "$STACK_NAME"
                ;;
            *)
                echo "Invalid choice"
                ;;
        esac
        ;;
    4)
        echo "🔄 Update API Image"
        echo ""
        read -p "Enter new image version [$IMAGE_VERSION]: " new_version
        new_version="${new_version:-$IMAGE_VERSION}"
        
        echo ""
        echo "Pulling image: $IMAGE_NAME:$new_version"
        docker pull "$IMAGE_NAME:$new_version"
        
        echo ""
        echo "Updating service..."
        docker service update --image "$IMAGE_NAME:$new_version" "${STACK_NAME}_api"
        
        # Persist the new version to .env
        if [ -f .env ]; then
            if grep -q '^IMAGE_VERSION=' .env; then
                sed -i "s/^IMAGE_VERSION=.*/IMAGE_VERSION=$new_version/" .env
            else
                echo "IMAGE_VERSION=$new_version" >> .env
            fi
            echo "Saved IMAGE_VERSION=$new_version to .env"
        else
            echo "⚠️  .env not found; skipping persistence of IMAGE_VERSION"
        fi
        
        echo ""
        echo "✅ Service update initiated!"
        echo "Monitor progress with: docker service ps ${STACK_NAME}_api"
        ;;
    5)
        echo "📊 Scale Services"
        echo ""
        echo "Which service do you want to scale?"
        echo "1) API"
        echo "2) Redis"
        if [ "$DB_TYPE" = "postgresql" ]; then
            echo "3) PostgreSQL"
        elif [ "$DB_TYPE" = "neo4j" ]; then
            echo "3) Neo4j"
        fi
        echo ""
        read -p "Your choice: " scale_choice
        
        read -p "Number of replicas: " replicas
        
        case $scale_choice in
            1)
                docker service scale "${STACK_NAME}_api=$replicas"
                # Persist API replicas
                if [ -f .env ]; then
                    if grep -q '^API_REPLICAS=' .env; then
                        sed -i "s/^API_REPLICAS=.*/API_REPLICAS=$replicas/" .env
                    else
                        echo "API_REPLICAS=$replicas" >> .env
                    fi
                    echo "Saved API_REPLICAS=$replicas to .env"
                fi
                ;;
            2)
                docker service scale "${STACK_NAME}_redis=$replicas"
                # Persist Redis replicas
                if [ -f .env ]; then
                    if grep -q '^REDIS_REPLICAS=' .env; then
                        sed -i "s/^REDIS_REPLICAS=.*/REDIS_REPLICAS=$replicas/" .env
                    else
                        echo "REDIS_REPLICAS=$replicas" >> .env
                    fi
                    echo "Saved REDIS_REPLICAS=$replicas to .env"
                fi
                ;;
            3)
                if [ "$DB_TYPE" = "neo4j" ]; then
                    docker service scale "${STACK_NAME}_neo4j=$replicas"
                    # Persist Neo4j replicas
                    if [ -f .env ]; then
                        if grep -q '^NEO4J_REPLICAS=' .env; then
                            sed -i "s/^NEO4J_REPLICAS=.*/NEO4J_REPLICAS=$replicas/" .env
                        else
                            echo "NEO4J_REPLICAS=$replicas" >> .env
                        fi
                        echo "Saved NEO4J_REPLICAS=$replicas to .env"
                    fi
                else
                    docker service scale "${STACK_NAME}_postgres=$replicas"
                    # Persist Postgres replicas
                    if [ -f .env ]; then
                        if grep -q '^POSTGRES_REPLICAS=' .env; then
                            sed -i "s/^POSTGRES_REPLICAS=.*/POSTGRES_REPLICAS=$replicas/" .env
                        else
                            echo "POSTGRES_REPLICAS=$replicas" >> .env
                        fi
                        echo "Saved POSTGRES_REPLICAS=$replicas to .env"
                    fi
                fi
                ;;
            *)
                echo "Invalid choice"
                ;;
        esac
        ;;
    6)
        echo "🗑️  Remove Deployment"
        echo ""
        echo "⚠️  WARNING: This will remove all services in the stack."
        echo "Data in volumes will be preserved."
        echo ""
        read -p "Are you sure? Type 'yes' to confirm: " confirm
        if [ "$confirm" = "yes" ]; then
            echo ""
            echo "Removing stack: $STACK_NAME"
            docker stack rm "$STACK_NAME"
            echo ""
            echo "✅ Stack removal initiated!"
            echo "Wait for all services to be removed before redeploying."
        else
            echo "Removal cancelled."
        fi
        ;;
    7)
        echo "🔄 Re-running setup wizard..."
        echo ""
        ./setup/setup-wizard.sh
        ;;
    8)
        echo "🔑 Manage Docker Secrets"
        echo ""
        
        # Convert stack name to uppercase and replace non-alphanumeric chars with underscore
        STACK_NAME_UPPER=$(echo "$STACK_NAME" | tr '[:lower:]' '[:upper:]' | sed 's/[^A-Z0-9]/_/g')
        
        # Define secret names
        DB_PASSWORD_SECRET="${STACK_NAME_UPPER}_DB_PASSWORD"
        ADMIN_API_KEY_SECRET="${STACK_NAME_UPPER}_ADMIN_API_KEY"
        BACKUP_RESTORE_API_KEY_SECRET="${STACK_NAME_UPPER}_BACKUP_RESTORE_API_KEY"
        BACKUP_DELETE_API_KEY_SECRET="${STACK_NAME_UPPER}_BACKUP_DELETE_API_KEY"
        
        # Check which secrets exist
        echo "📋 Current Secret Status:"
        echo "------------------------"
        
        if docker secret inspect "$DB_PASSWORD_SECRET" &>/dev/null; then
            echo "✅ Database password secret exists"
        else
            echo "❌ Database password secret missing"
        fi
        
        if docker secret inspect "$ADMIN_API_KEY_SECRET" &>/dev/null; then
            echo "✅ Admin API key secret exists"
        else
            echo "❌ Admin API key secret missing"
        fi
        
        if docker secret inspect "$BACKUP_RESTORE_API_KEY_SECRET" &>/dev/null; then
            echo "✅ Backup restore API key secret exists"
        else
            echo "❌ Backup restore API key secret missing"
        fi
        
        if docker secret inspect "$BACKUP_DELETE_API_KEY_SECRET" &>/dev/null; then
            echo "✅ Backup delete API key secret exists"
        else
            echo "❌ Backup delete API key secret missing"
        fi
        
        echo ""
        echo "What would you like to do?"
        echo "1) Create/update all secrets"
        echo "2) List all secrets"
        echo "3) Back to main menu"
        echo ""
        read -p "Your choice (1-3): " secret_choice
        
        case $secret_choice in
            1)
                # Check if stack is running
                echo ""
                echo "🔍 Checking for running stack..."
                
                if docker stack ls --format "{{.Name}}" | grep -q "^${STACK_NAME}$"; then
                    echo "⚠️  WARNING: Stack '$STACK_NAME' is currently running!"
                    echo ""
                    echo "Secrets cannot be updated while in use by a running stack."
                    echo ""
                    read -p "Remove stack before updating secrets? (y/N): " REMOVE_STACK
                    
                    if [[ "$REMOVE_STACK" =~ ^[Yy]$ ]]; then
                        echo ""
                        echo "Removing stack: $STACK_NAME"
                        docker stack rm "$STACK_NAME"
                        
                        echo "Waiting for stack to be fully removed..."
                        while docker stack ls --format "{{.Name}}" | grep -q "^${STACK_NAME}$"; do
                            echo -n "."
                            sleep 2
                        done
                        echo ""
                        echo "✅ Stack removed successfully"
                        echo ""
                        
                        # Now create secrets
                        create_docker_secrets "$DB_PASSWORD_SECRET" "$ADMIN_API_KEY_SECRET" "$BACKUP_RESTORE_API_KEY_SECRET" "$BACKUP_DELETE_API_KEY_SECRET"
                    else
                        echo ""
                        echo "⚠️  Secret creation cancelled."
                        echo "Stop the stack manually with: docker stack rm $STACK_NAME"
                        echo "Then run this option again."
                    fi
                else
                    echo "✅ No running stack found"
                    echo ""
                    # Use the secret-manager module
                    create_docker_secrets "$DB_PASSWORD_SECRET" "$ADMIN_API_KEY_SECRET" "$BACKUP_RESTORE_API_KEY_SECRET" "$BACKUP_DELETE_API_KEY_SECRET"
                fi
                ;;
            2)
                list_docker_secrets
                ;;
            3)
                echo "Returning to main menu..."
                ;;
            *)
                echo "Invalid choice"
                ;;
        esac
        ;;
    9)
        if declare -F run_cognito_setup >/dev/null; then
            run_cognito_setup
            
            # Check if Cognito was configured (AWS_REGION indicates Cognito setup was run)
            cognito_region=$(grep "^AWS_REGION=" .env 2>/dev/null | cut -d'=' -f2)
            
            if [ -n "$cognito_region" ]; then
                echo ""
                echo "🔧 Updating stack file with Cognito secrets..."
                # Generate stack name upper for secret names
                STACK_NAME_UPPER=$(echo "$STACK_NAME" | tr '[:lower:]' '[:upper:]' | sed 's/[^A-Z0-9]/_/g')
                # Add Cognito secrets to stack file
                add_cognito_to_stack "$(pwd)/swarm-stack.yml" "$(pwd)" "$STACK_NAME_UPPER"
                
                echo ""
                echo "🔍 Checking for running stack..."
                
                # Check if stack is already running
                if docker stack ls --format "{{.Name}}" | grep -q "^${STACK_NAME}$"; then
                    echo "✅ Stack '$STACK_NAME' is currently running"
                    echo ""
                    read -p "Redeploy stack to apply Cognito configuration? (Y/n): " REDEPLOY
                    
                    if [[ ! "$REDEPLOY" =~ ^[Nn]$ ]]; then
                        STACK_FILE="$(pwd)/swarm-stack.yml"
                        ENV_FILE="$(pwd)/.env"

                        echo ""
                        echo "Redeploying stack with Cognito configuration..."

                        docker stack deploy -c <(docker-compose -f "$STACK_FILE" --env-file "$ENV_FILE" config) "$STACK_NAME"

                        if [ $? -eq 0 ]; then
                            echo ""
                            echo "✅ Stack redeployed successfully"
                            echo ""

                            # Run health check
                            echo "🏥 Running health check..."
                            check_deployment_health "$STACK_NAME" "$DB_TYPE" "$PROXY_TYPE" "$API_URL"
                        else
                            echo "❌ Deployment failed"
                        fi
                    else
                        echo ""
                        echo "ℹ️  Skipping redeployment. You can redeploy manually with:"
                        echo "   docker stack deploy -c swarm-stack.yml $STACK_NAME"
                    fi
                else
                    echo "⚠️  No running stack found"
                    echo ""
                    read -p "Deploy stack now with Cognito configuration? (Y/n): " DEPLOY_NOW
                    
                    if [[ ! "$DEPLOY_NOW" =~ ^[Nn]$ ]]; then
                        # Use the deploy-stack module
                        STACK_FILE="$(pwd)/swarm-stack.yml"
                        deploy_stack "$STACK_NAME" "$STACK_FILE"
                        
                        if [ $? -eq 0 ]; then
                            # Run health check
                            check_deployment_health "$STACK_NAME" "$DB_TYPE" "$PROXY_TYPE" "$API_URL"
                        fi
                    else
                        echo ""
                        echo "ℹ️  Skipping deployment. You can deploy manually with:"
                        echo "   docker stack deploy -c swarm-stack.yml $STACK_NAME"
                    fi
                fi
            fi
        else
            echo "👋 Goodbye!"
            exit 0
        fi
        ;;
    10)
        echo "👋 Goodbye!"
        exit 0
        ;;
    *)
        echo "❌ Invalid choice"
        exit 1
        ;;
esac

echo ""
echo "Done!"
