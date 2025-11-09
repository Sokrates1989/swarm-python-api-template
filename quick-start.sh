#!/bin/bash
#
# quick-start.sh
#
# Quick start tool for Swarm Python API Template:
# 1. Checks Docker installation
# 2. Runs interactive setup if needed
# 3. Provides deployment and management options

set -e

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
echo "8) Create Docker secrets"
echo "9) Exit"
echo ""
read -p "Your choice (1-9): " choice

case $choice in
    1)
        echo "🚀 Deploying to Docker Swarm..."
        echo ""
        echo "⚠️  Make sure you have:"
        echo "   - Created Docker secrets"
        echo "   - Configured your domain DNS"
        echo "   - Created data directories"
        echo ""
        read -p "Continue with deployment? (y/N): " confirm
        if [[ "$confirm" =~ ^[Yy]$ ]]; then
            echo ""
            echo "Deploying stack: $STACK_NAME"
            docker stack deploy -c swarm-stack.yml "$STACK_NAME"
            echo ""
            echo "✅ Deployment initiated!"
            echo ""
            echo "Check status with:"
            echo "  docker stack services $STACK_NAME"
            echo ""
            echo "View logs with:"
            echo "  docker service logs -f ${STACK_NAME}_api"
        else
            echo "Deployment cancelled."
        fi
        ;;
    2)
        echo "📊 Checking deployment status..."
        echo ""
        docker stack services "$STACK_NAME"
        echo ""
        echo "For detailed task status:"
        echo "  docker service ps ${STACK_NAME}_api --no-trunc"
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
                ;;
            2)
                docker service scale "${STACK_NAME}_redis=$replicas"
                ;;
            3)
                if [ "$DB_TYPE" = "neo4j" ]; then
                    docker service scale "${STACK_NAME}_neo4j=$replicas"
                else
                    docker service scale "${STACK_NAME}_postgres=$replicas"
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
        echo "🔑 Create Docker Secrets"
        echo ""
        echo "This will help you create the required Docker secrets."
        echo ""
        
        # Convert stack name to uppercase and replace non-alphanumeric chars with underscore
        STACK_NAME_UPPER=$(echo "$STACK_NAME" | tr '[:lower:]' '[:upper:]' | sed 's/[^A-Z0-9]/_/g')
        
        # Detect available editor
        if command -v nano &> /dev/null; then
            EDITOR="nano"
        elif command -v vi &> /dev/null; then
            EDITOR="vi"
        elif command -v vim &> /dev/null; then
            EDITOR="vim"
        else
            echo "❌ No text editor found (nano, vi, or vim required)"
            echo "Please install a text editor and try again."
            exit 1
        fi
        
        echo "Creating Database Password Secret..."
        echo "-----------------------------------"
        echo "Opening editor for database password..."
        echo "Please enter the password, save, and close the editor."
        echo ""
        
        $EDITOR secret.txt
        docker secret create "${STACK_NAME_UPPER}_DB_PASSWORD" secret.txt 2>/dev/null
        if [ $? -eq 0 ]; then
            echo "✅ Secret ${STACK_NAME_UPPER}_DB_PASSWORD created successfully"
        else
            echo "⚠️  Secret ${STACK_NAME_UPPER}_DB_PASSWORD may already exist"
        fi
        rm -f secret.txt
        echo ""
        
        echo "Creating Admin API Key Secret..."
        echo "--------------------------------"
        echo "Opening editor for admin API key..."
        echo "Please enter the API key, save, and close the editor."
        echo ""
        
        $EDITOR secret.txt
        docker secret create "${STACK_NAME_UPPER}_ADMIN_API_KEY" secret.txt 2>/dev/null
        if [ $? -eq 0 ]; then
            echo "✅ Secret ${STACK_NAME_UPPER}_ADMIN_API_KEY created successfully"
        else
            echo "⚠️  Secret ${STACK_NAME_UPPER}_ADMIN_API_KEY may already exist"
        fi
        rm -f secret.txt
        echo ""
        
        echo "✅ Secrets created!"
        echo ""
        echo "List secrets with: docker secret ls"
        ;;
    9)
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
