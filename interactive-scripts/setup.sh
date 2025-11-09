#!/bin/bash

# Interactive Setup Script for Swarm Python API Template
# This script helps users configure their Docker Swarm deployment

set -e

echo "🚀 Swarm Python API Template - Initial Setup"
echo "=============================================="
echo ""

# Check if setup is already complete (either via .setup-complete or manual setup)
SETUP_ALREADY_DONE=false

if [ -f .setup-complete ]; then
    SETUP_ALREADY_DONE=true
    echo "⚠️  Setup has already been completed (.setup-complete marker found)."
elif [ -f .env ] && [ -f docker-compose.yml ]; then
    SETUP_ALREADY_DONE=true
    echo "⚠️  Setup appears to have been done manually (.env and docker-compose.yml exist)."
fi

if [ "$SETUP_ALREADY_DONE" = true ]; then
    read -p "Do you want to run setup again? This will overwrite .env and docker-compose.yml (y/N): " RERUN_SETUP
    if [[ ! "$RERUN_SETUP" =~ ^[Yy]$ ]]; then
        echo "Setup cancelled."
        exit 0
    fi
    echo ""
fi

# Backup existing files if they exist
if [ -f .env ]; then
    BACKUP_FILE=".env.backup.$(date +%Y%m%d_%H%M%S)"
    cp .env "$BACKUP_FILE"
    echo "📋 Backed up existing .env to $BACKUP_FILE"
fi

if [ -f docker-compose.yml ]; then
    BACKUP_FILE="docker-compose.yml.backup.$(date +%Y%m%d_%H%M%S)"
    cp docker-compose.yml "$BACKUP_FILE"
    echo "📋 Backed up existing docker-compose.yml to $BACKUP_FILE"
fi

echo ""
echo "Let's configure your Swarm API deployment!"
echo ""

# =============================================================================
# DATABASE TYPE SELECTION
# =============================================================================
echo "🗄️  Database Configuration"
echo "-------------------------"
echo "Choose database type:"
echo "1) PostgreSQL (recommended for relational data)"
echo "2) Neo4j (recommended for graph data)"
echo ""

read -p "Your choice (1-2) [1]: " DB_CHOICE
DB_CHOICE="${DB_CHOICE:-1}"

case $DB_CHOICE in
    1)
        DB_TYPE="postgresql"
        ENV_TEMPLATE="setup/.env.postgres.template"
        COMPOSE_TEMPLATE="setup/docker-compose.postgres.yml.template"
        echo "✅ Selected: PostgreSQL"
        ;;
    2)
        DB_TYPE="neo4j"
        ENV_TEMPLATE="setup/.env.neo4j.template"
        COMPOSE_TEMPLATE="setup/docker-compose.neo4j.yml.template"
        echo "✅ Selected: Neo4j"
        ;;
    *)
        DB_TYPE="postgresql"
        ENV_TEMPLATE="setup/.env.postgres.template"
        COMPOSE_TEMPLATE="setup/docker-compose.postgres.yml.template"
        echo "⚠️  Invalid choice, defaulting to PostgreSQL"
        ;;
esac

echo ""

# =============================================================================
# DATABASE MODE SELECTION
# =============================================================================
echo "Choose database deployment mode:"
echo "1) Local database (deploy database alongside API in swarm)"
echo "2) External database (use existing database server)"
echo ""

read -p "Your choice (1-2) [1]: " DB_MODE_CHOICE
DB_MODE_CHOICE="${DB_MODE_CHOICE:-1}"

case $DB_MODE_CHOICE in
    1)
        DB_MODE="local"
        DEPLOY_DATABASE=true
        echo "✅ Selected: Local database (will deploy in swarm)"
        ;;
    2)
        DB_MODE="external"
        DEPLOY_DATABASE=false
        echo "✅ Selected: External database"
        ;;
    *)
        DB_MODE="local"
        DEPLOY_DATABASE=true
        echo "⚠️  Invalid choice, defaulting to local"
        ;;
esac

echo ""

# Copy templates
cp "$ENV_TEMPLATE" .env
cp "$COMPOSE_TEMPLATE" docker-compose.yml

# If external database, remove database service from docker-compose.yml
if [ "$DEPLOY_DATABASE" = false ]; then
    echo "⚙️  Configuring for external database..."
    # This is a simplified approach - in production you might want more sophisticated editing
    echo "⚠️  Note: You'll need to manually remove the database service from docker-compose.yml"
    echo "   or use a compose file without the database service."
fi

echo ""

# =============================================================================
# DOCKER IMAGE CONFIGURATION
# =============================================================================
echo "📦 Docker Image Configuration"
echo "------------------------------"
echo "This should match the image built from your main python-api-template."
echo ""

read -p "Enter Docker image name (e.g., username/api-name): " IMAGE_NAME
while [ -z "$IMAGE_NAME" ]; do
    echo "❌ Image name cannot be empty"
    read -p "Enter Docker image name (e.g., username/api-name): " IMAGE_NAME
done

read -p "Enter image version [0.0.1]: " IMAGE_VERSION
IMAGE_VERSION="${IMAGE_VERSION:-0.0.1}"

# Update .env with image configuration
sed -i "s|^IMAGE_NAME=.*|IMAGE_NAME=$IMAGE_NAME|" .env
sed -i "s|^IMAGE_VERSION=.*|IMAGE_VERSION=$IMAGE_VERSION|" .env

echo "✅ Image: $IMAGE_NAME:$IMAGE_VERSION"
echo ""

# =============================================================================
# DOMAIN CONFIGURATION
# =============================================================================
echo "🌐 Domain Configuration"
echo "----------------------"
echo "Enter the domain where your API will be accessible."
echo ""
echo "⚠️  IMPORTANT: Make sure your domain/subdomain is already created and"
echo "   points to your swarm manager's IP address before deploying."
echo ""
echo "   For domain setup instructions, see README.md (Domain Setup section)."
echo "   Providers covered: Strato, IONOS, and general DNS configuration."
echo ""

read -p "API domain (e.g., api.example.com): " API_URL
while [ -z "$API_URL" ]; do
    echo "❌ API domain cannot be empty"
    read -p "API domain (e.g., api.example.com): " API_URL
done

sed -i "s|^API_URL=.*|API_URL=$API_URL|" .env
echo "✅ API will be accessible at: https://$API_URL"
echo ""

# =============================================================================
# DATA ROOT CONFIGURATION
# =============================================================================
echo "💾 Data Storage Configuration"
echo "----------------------------"
echo "Enter the path where persistent data will be stored."
echo "For multi-node swarms, use a shared filesystem like GlusterFS."
echo ""

DEFAULT_DATA_ROOT="/gluster_storage/swarm/python-api-template/$API_URL"
read -p "Data root path [$DEFAULT_DATA_ROOT]: " DATA_ROOT
DATA_ROOT="${DATA_ROOT:-$DEFAULT_DATA_ROOT}"

sed -i "s|^DATA_ROOT=.*|DATA_ROOT=$DATA_ROOT|" .env
echo "✅ Data will be stored at: $DATA_ROOT"
echo ""

# =============================================================================
# STACK NAME CONFIGURATION
# =============================================================================
echo "🏷️  Stack Name Configuration"
echo "---------------------------"
echo "Choose a unique name for your Docker Swarm stack."
echo ""

DEFAULT_STACK_NAME="api_production"
read -p "Stack name [$DEFAULT_STACK_NAME]: " STACK_NAME
STACK_NAME="${STACK_NAME:-$DEFAULT_STACK_NAME}"

sed -i "s|^STACK_NAME=.*|STACK_NAME=$STACK_NAME|" .env
echo "✅ Stack name: $STACK_NAME"
echo ""

# =============================================================================
# DATABASE CREDENTIALS (for local mode)
# =============================================================================
if [ "$DEPLOY_DATABASE" = true ]; then
    echo "🔐 Database Credentials"
    echo "----------------------"
    echo "These will be used to create Docker secrets."
    echo ""
    
    if [ "$DB_TYPE" = "postgresql" ]; then
        read -p "Database name [apidb]: " DB_NAME
        DB_NAME="${DB_NAME:-apidb}"
        
        read -p "Database user [apiuser]: " DB_USER
        DB_USER="${DB_USER:-apiuser}"
        
        read -p "Database port [5432]: " DB_PORT
        DB_PORT="${DB_PORT:-5432}"
        
        sed -i "s|^DB_NAME=.*|DB_NAME=$DB_NAME|" .env
        sed -i "s|^DB_USER=.*|DB_USER=$DB_USER|" .env
        sed -i "s|^DB_PORT=.*|DB_PORT=$DB_PORT|" .env
        
        echo "✅ PostgreSQL configured"
    elif [ "$DB_TYPE" = "neo4j" ]; then
        read -p "Database user [neo4j]: " DB_USER
        DB_USER="${DB_USER:-neo4j}"
        
        sed -i "s|^DB_USER=.*|DB_USER=$DB_USER|" .env
        
        echo "✅ Neo4j configured"
    fi
    
    echo ""
    echo "⚠️  IMPORTANT: You'll need to create Docker secrets for:"
    echo "   - Database password"
    echo "   - Admin API key"
    echo ""
fi

# =============================================================================
# REPLICAS CONFIGURATION
# =============================================================================
echo "📊 Replica Configuration"
echo "-----------------------"
echo "Configure the number of replicas for each service."
echo ""

read -p "API replicas [1]: " API_REPLICAS
API_REPLICAS="${API_REPLICAS:-1}"
sed -i "s|^API_REPLICAS=.*|API_REPLICAS=$API_REPLICAS|" .env

if [ "$DEPLOY_DATABASE" = true ]; then
    if [ "$DB_TYPE" = "postgresql" ]; then
        read -p "PostgreSQL replicas [1]: " DB_REPLICAS
        DB_REPLICAS="${DB_REPLICAS:-1}"
        sed -i "s|^POSTGRES_REPLICAS=.*|POSTGRES_REPLICAS=$DB_REPLICAS|" .env
    elif [ "$DB_TYPE" = "neo4j" ]; then
        read -p "Neo4j replicas [1]: " DB_REPLICAS
        DB_REPLICAS="${DB_REPLICAS:-1}"
        sed -i "s|^NEO4J_REPLICAS=.*|NEO4J_REPLICAS=$DB_REPLICAS|" .env
    fi
fi

read -p "Redis replicas [1]: " REDIS_REPLICAS
REDIS_REPLICAS="${REDIS_REPLICAS:-1}"
sed -i "s|^REDIS_REPLICAS=.*|REDIS_REPLICAS=$REDIS_REPLICAS|" .env

echo "✅ Replicas configured"
echo ""

# =============================================================================
# SECRET NAMES CONFIGURATION
# =============================================================================
echo "🔑 Docker Secrets Configuration"
echo "------------------------------"
echo "Enter names for Docker secrets (you'll create these manually)."
echo ""

read -p "Database password secret name [DB_PASSWORD_${STACK_NAME}]: " DB_PASSWORD_SECRET
DB_PASSWORD_SECRET="${DB_PASSWORD_SECRET:-DB_PASSWORD_${STACK_NAME}}"

read -p "Admin API key secret name [ADMIN_API_KEY_${STACK_NAME}]: " ADMIN_API_KEY_SECRET
ADMIN_API_KEY_SECRET="${ADMIN_API_KEY_SECRET:-ADMIN_API_KEY_${STACK_NAME}}"

# Replace secret placeholders in docker-compose.yml
sed -i "s|XXX_CHANGE_ME_DB_PASSWORD_XXX|$DB_PASSWORD_SECRET|g" docker-compose.yml
sed -i "s|XXX_CHANGE_ME_ADMIN_API_KEY_XXX|$ADMIN_API_KEY_SECRET|g" docker-compose.yml

echo "✅ Secret names configured"
echo ""

# =============================================================================
# SUMMARY
# =============================================================================
echo "📋 Configuration Summary"
echo "========================"
echo "Database Type:      $DB_TYPE"
echo "Database Mode:      $DB_MODE"
echo "Docker Image:       $IMAGE_NAME:$IMAGE_VERSION"
echo "API Domain:         $API_URL"
echo "Stack Name:         $STACK_NAME"
echo "Data Root:          $DATA_ROOT"
echo "API Replicas:       $API_REPLICAS"
if [ "$DEPLOY_DATABASE" = true ]; then
    echo "DB Replicas:        $DB_REPLICAS"
fi
echo "Redis Replicas:     $REDIS_REPLICAS"
echo ""
echo "Docker Secrets:"
echo "  - $DB_PASSWORD_SECRET"
echo "  - $ADMIN_API_KEY_SECRET"
echo ""

read -p "Save this configuration? (Y/n): " CONFIRM
if [[ "$CONFIRM" =~ ^[Nn]$ ]]; then
    echo "❌ Setup cancelled."
    exit 1
fi

# Mark setup as complete
touch .setup-complete
echo "✅ Setup complete! Configuration saved."
echo ""

# =============================================================================
# NEXT STEPS
# =============================================================================
echo "🎉 Next Steps:"
echo "=============="
echo ""
echo "1. Create Docker secrets on your swarm manager:"
echo ""
echo "   # Database password secret"
echo "   echo 'your-db-password' | docker secret create $DB_PASSWORD_SECRET -"
echo ""
echo "   # Admin API key secret"
echo "   echo 'your-admin-api-key' | docker secret create $ADMIN_API_KEY_SECRET -"
echo ""
echo "2. Ensure your domain points to the swarm manager:"
echo "   - Domain: $API_URL"
echo "   - Should resolve to your swarm manager's IP"
echo "   - Test with: nslookup $API_URL"
echo "   - If not set up yet, see README.md (Domain Setup section)"
echo ""
echo "3. Create data directories:"
echo "   mkdir -p $DATA_ROOT"
if [ "$DB_TYPE" = "postgresql" ]; then
    echo "   mkdir -p $DATA_ROOT/postgres_data"
elif [ "$DB_TYPE" = "neo4j" ]; then
    echo "   mkdir -p $DATA_ROOT/neo4j_data"
    echo "   mkdir -p $DATA_ROOT/neo4j_logs"
fi
echo "   mkdir -p $DATA_ROOT/redis_data"
echo ""
echo "4. Deploy to swarm:"
echo "   docker stack deploy -c <(docker-compose config) $STACK_NAME"
echo ""
echo "5. Check deployment status:"
echo "   docker stack services $STACK_NAME"
echo ""
echo "For more information, see README.md"
echo ""
