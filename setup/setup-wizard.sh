#!/bin/bash

# Interactive Setup Script for Swarm Python API Template
# This script helps users configure their Docker Swarm deployment

set -e

# Get the directory where this script is located (setup/)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# Get the project root directory (parent of setup/)
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

echo "🚀 Swarm Python API Template - Initial Setup"
echo "=============================================="
echo ""
echo "Working directory: $PROJECT_ROOT"
echo ""

# Check if setup is already complete (either via .setup-complete or manual setup)
SETUP_ALREADY_DONE=false

if [ -f .setup-complete ]; then
    SETUP_ALREADY_DONE=true
    echo "⚠️  Setup has already been completed (.setup-complete marker found)."
elif [ -f .env ] && [ -f swarm-stack.yml ]; then
    SETUP_ALREADY_DONE=true
    echo "⚠️  Setup appears to have been done manually (.env and swarm-stack.yml exist)."
fi

if [ "$SETUP_ALREADY_DONE" = true ]; then
    read -p "Do you want to run setup again? This will overwrite .env and swarm-stack.yml (y/N): " RERUN_SETUP
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

if [ -f swarm-stack.yml ]; then
    BACKUP_FILE="swarm-stack.yml.backup.$(date +%Y%m%d_%H%M%S)"
    cp swarm-stack.yml "$BACKUP_FILE"
    echo "📋 Backed up existing swarm-stack.yml to $BACKUP_FILE"
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
        echo "✅ Selected: PostgreSQL"
        ;;
    2)
        DB_TYPE="neo4j"
        echo "✅ Selected: Neo4j"
        ;;
    *)
        DB_TYPE="postgresql"
        echo "⚠️  Invalid choice, defaulting to PostgreSQL"
        ;;
esac

echo ""

# =============================================================================
# PROXY SELECTION
# =============================================================================
echo "🌐 Proxy Configuration"
echo "---------------------"
echo "Choose your proxy/ingress solution:"
echo "1) Traefik (recommended for automatic HTTPS with Let's Encrypt)"
echo "2) No proxy (direct port exposure - you manage your own proxy/load balancer)"
echo ""

read -p "Your choice (1-2) [1]: " PROXY_CHOICE
PROXY_CHOICE="${PROXY_CHOICE:-1}"

case $PROXY_CHOICE in
    1)
        PROXY_TYPE="traefik"
        echo "✅ Selected: Traefik"
        ;;
    2)
        PROXY_TYPE="no-proxy"
        echo "✅ Selected: No proxy (direct port exposure)"
        ;;
    *)
        PROXY_TYPE="traefik"
        echo "⚠️  Invalid choice, defaulting to Traefik"
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

# Build .env file from modular templates
echo "⚙️  Building configuration files..."

# Start with base configuration
cat setup/env-templates/.env.base.template > .env

# Add database-specific configuration
if [ "$DB_TYPE" = "postgresql" ]; then
    if [ "$DB_MODE" = "local" ]; then
        cat setup/env-templates/.env.postgres-local.template >> .env
        DATABASE_MODULE="postgres-local.yml"
    else
        cat setup/env-templates/.env.postgres-external.template >> .env
        DATABASE_MODULE="postgres-external.yml"
    fi
else
    if [ "$DB_MODE" = "local" ]; then
        cat setup/env-templates/.env.neo4j-local.template >> .env
        DATABASE_MODULE="neo4j-local.yml"
    else
        cat setup/env-templates/.env.neo4j-external.template >> .env
        DATABASE_MODULE="neo4j-external.yml"
    fi
fi

# Add proxy-specific configuration
if [ "$PROXY_TYPE" = "traefik" ]; then
    cat setup/env-templates/.env.proxy-traefik.template >> .env
    PROXY_MODULE="proxy-traefik.yml"
else
    cat setup/env-templates/.env.proxy-none.template >> .env
    PROXY_MODULE="proxy-none.yml"
fi

# Build swarm-stack.yml from modules with template injection
echo "Building swarm-stack.yml..."

# Start with base (services: and redis)
cat setup/compose-modules/base.yml > swarm-stack.yml

# Build API service from template with snippet injection
cp setup/compose-modules/api.template.yml swarm-stack.tmp.yml

# Inject database environment snippet
DB_SNIPPET="setup/compose-modules/snippets/db-${DB_TYPE}-${DB_MODE}.env.yml"
sed -i "/###DATABASE_ENV###/r $DB_SNIPPET" swarm-stack.tmp.yml
sed -i '/###DATABASE_ENV###/d' swarm-stack.tmp.yml

# Inject proxy network snippet (or remove placeholder)
if [ "$PROXY_TYPE" = "traefik" ]; then
    sed -i "/###PROXY_NETWORK###/r setup/compose-modules/snippets/proxy-traefik.network.yml" swarm-stack.tmp.yml
fi
sed -i '/###PROXY_NETWORK###/d' swarm-stack.tmp.yml

# Inject proxy ports or labels
if [ "$PROXY_TYPE" = "traefik" ]; then
    sed -i "/###PROXY_LABELS###/r setup/compose-modules/snippets/proxy-traefik.labels.yml" swarm-stack.tmp.yml
    sed -i '/###PROXY_PORTS###/d' swarm-stack.tmp.yml
else
    sed -i "/###PROXY_PORTS###/r setup/compose-modules/snippets/proxy-none.ports.yml" swarm-stack.tmp.yml
    sed -i '/###PROXY_LABELS###/d' swarm-stack.tmp.yml
fi
sed -i '/###PROXY_LABELS###/d' swarm-stack.tmp.yml

# Append API service to stack
cat swarm-stack.tmp.yml >> swarm-stack.yml
rm -f swarm-stack.tmp.yml

# Add database service if local
if [ "$DEPLOY_DATABASE" = true ]; then
    cat "setup/compose-modules/$DATABASE_MODULE" >> swarm-stack.yml
fi

# Add footer (networks and secrets)
cat setup/compose-modules/footer.yml >> swarm-stack.yml

echo "✅ swarm-stack.yml created"
echo ""

# =============================================================================
# DOCKER IMAGE CONFIGURATION
# =============================================================================
echo "📦 Docker Image Configuration"
echo "------------------------------"
echo "This should match the image built from your main python-api-template."
echo ""

IMAGE_VERIFIED=false
while [ "$IMAGE_VERIFIED" = false ]; do
    read -p "Enter Docker image name (e.g., sokrates1989/python-api-template): " IMAGE_NAME
    while [ -z "$IMAGE_NAME" ]; do
        echo "❌ Image name cannot be empty"
        read -p "Enter Docker image name (e.g., sokrates1989/python-api-template): " IMAGE_NAME
    done

    read -p "Enter Docker image version/tag [0.0.1]: " IMAGE_VERSION
    IMAGE_VERSION="${IMAGE_VERSION:-0.0.1}"

    echo ""
    echo "🔍 Verifying Docker image: $IMAGE_NAME:$IMAGE_VERSION"
    
    if docker pull "$IMAGE_NAME:$IMAGE_VERSION" > /dev/null 2>&1; then
        echo "✅ Image successfully pulled and verified"
        IMAGE_VERIFIED=true
    else
        echo "❌ Could not pull image $IMAGE_NAME:$IMAGE_VERSION"
        echo ""
        echo "This might be because:"
        echo "  1) The image doesn't exist yet (you need to build and push it)"
        echo "  2) You're not logged in to the registry"
        echo "  3) The image name or version is incorrect"
        echo ""
        echo "What would you like to do?"
        echo "1) Login to Docker registry"
        echo "2) Re-enter image name/version"
        echo "3) Skip verification and continue anyway"
        echo "4) Cancel setup"
        echo ""
        read -p "Your choice (1-4): " IMAGE_CHOICE
        
        case $IMAGE_CHOICE in
            1)
                echo ""
                echo "🔐 Docker Registry Login"
                echo "----------------------"
                echo "For Docker Hub: docker login"
                echo "For other registries: docker login <registry-url>"
                echo ""
                read -p "Enter registry URL (press Enter for Docker Hub): " REGISTRY_URL
                if [ -z "$REGISTRY_URL" ]; then
                    docker login
                else
                    docker login "$REGISTRY_URL"
                fi
                echo ""
                echo "Retrying image pull..."
                ;;
            2)
                echo ""
                echo "Re-entering image details..."
                echo ""
                ;;
            3)
                echo ""
                echo "⚠️  Skipping image verification"
                IMAGE_VERIFIED=true
                ;;
            4)
                echo "Setup cancelled."
                exit 1
                ;;
            *)
                echo "Invalid choice, please try again."
                echo ""
                ;;
        esac
    fi
done

sed -i "s|^IMAGE_NAME=.*|IMAGE_NAME=$IMAGE_NAME|" .env
sed -i "s|^IMAGE_VERSION=.*|IMAGE_VERSION=$IMAGE_VERSION|" .env

echo "✅ Image configured: $IMAGE_NAME:$IMAGE_VERSION"
echo ""

# =============================================================================
# DOMAIN/PORT CONFIGURATION
# =============================================================================
if [ "$PROXY_TYPE" = "traefik" ]; then
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
else
    echo "🔌 Port Configuration"
    echo "--------------------"
    echo "Configure the port where your API will be accessible."
    echo ""
    
    read -p "Published port on host [8000]: " PUBLISHED_PORT
    PUBLISHED_PORT="${PUBLISHED_PORT:-8000}"
    
    sed -i "s|^PUBLISHED_PORT=.*|PUBLISHED_PORT=$PUBLISHED_PORT|" .env
    echo "✅ API will be accessible at: http://<your-server-ip>:$PUBLISHED_PORT"
    echo ""
fi

# =============================================================================
# DATA ROOT CONFIGURATION
# =============================================================================
echo "💾 Data Storage Configuration"
echo "----------------------------"
echo "Enter the path where persistent data will be stored."
echo "For multi-node swarms, use a shared filesystem like GlusterFS."
echo ""

# Use project root as default data root
DEFAULT_DATA_ROOT="$PROJECT_ROOT"
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
# DATABASE CREDENTIALS
# =============================================================================
if [ "$DEPLOY_DATABASE" = true ]; then
    echo "🔐 Database Credentials (Local Database)"
    echo "---------------------------------------"
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
else
    echo "🔐 External Database Configuration"
    echo "---------------------------------"
    echo "Configure connection to your existing database."
    echo ""
    
    if [ "$DB_TYPE" = "postgresql" ]; then
        read -p "Database host: " DB_HOST
        while [ -z "$DB_HOST" ]; do
            echo "❌ Database host cannot be empty"
            read -p "Database host: " DB_HOST
        done
        
        read -p "Database port [5432]: " DB_PORT
        DB_PORT="${DB_PORT:-5432}"
        
        read -p "Database name [apidb]: " DB_NAME
        DB_NAME="${DB_NAME:-apidb}"
        
        read -p "Database user [apiuser]: " DB_USER
        DB_USER="${DB_USER:-apiuser}"
        
        read -s -p "Database password: " DB_PASSWORD
        echo ""
        while [ -z "$DB_PASSWORD" ]; do
            echo "❌ Database password cannot be empty"
            read -s -p "Database password: " DB_PASSWORD
            echo ""
        done
        
        sed -i "s|^DB_HOST=.*|DB_HOST=$DB_HOST|" .env
        sed -i "s|^DB_PORT=.*|DB_PORT=$DB_PORT|" .env
        sed -i "s|^DB_NAME=.*|DB_NAME=$DB_NAME|" .env
        sed -i "s|^DB_USER=.*|DB_USER=$DB_USER|" .env
        sed -i "s|^DB_PASSWORD=.*|DB_PASSWORD=$DB_PASSWORD|" .env
        
        echo "✅ PostgreSQL external connection configured"
    elif [ "$DB_TYPE" = "neo4j" ]; then
        read -p "Neo4j URL (e.g., bolt://host:7687): " NEO4J_URL
        while [ -z "$NEO4J_URL" ]; do
            echo "❌ Neo4j URL cannot be empty"
            read -p "Neo4j URL (e.g., bolt://host:7687): " NEO4J_URL
        done
        
        read -p "Database user [neo4j]: " DB_USER
        DB_USER="${DB_USER:-neo4j}"
        
        read -s -p "Database password: " DB_PASSWORD
        echo ""
        while [ -z "$DB_PASSWORD" ]; do
            echo "❌ Database password cannot be empty"
            read -s -p "Database password: " DB_PASSWORD
            echo ""
        done
        
        sed -i "s|^NEO4J_URL=.*|NEO4J_URL=$NEO4J_URL|" .env
        sed -i "s|^DB_USER=.*|DB_USER=$DB_USER|" .env
        sed -i "s|^DB_PASSWORD=.*|DB_PASSWORD=$DB_PASSWORD|" .env
        
        echo "✅ Neo4j external connection configured"
    fi
    
    echo ""
    echo "⚠️  IMPORTANT: You'll still need to create Docker secret for:"
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

# Convert stack name to uppercase and replace non-alphanumeric chars with underscore
STACK_NAME_UPPER=$(echo "$STACK_NAME" | tr '[:lower:]' '[:upper:]' | sed 's/[^A-Z0-9]/_/g')

read -p "Database password secret name [${STACK_NAME_UPPER}_DB_PASSWORD]: " DB_PASSWORD_SECRET
DB_PASSWORD_SECRET="${DB_PASSWORD_SECRET:-${STACK_NAME_UPPER}_DB_PASSWORD}"

read -p "Admin API key secret name [${STACK_NAME_UPPER}_ADMIN_API_KEY]: " ADMIN_API_KEY_SECRET
ADMIN_API_KEY_SECRET="${ADMIN_API_KEY_SECRET:-${STACK_NAME_UPPER}_ADMIN_API_KEY}"

# Replace secret placeholders in swarm-stack.yml
sed -i "s|XXX_CHANGE_ME_DB_PASSWORD_XXX|$DB_PASSWORD_SECRET|g" swarm-stack.yml
sed -i "s|XXX_CHANGE_ME_ADMIN_API_KEY_XXX|$ADMIN_API_KEY_SECRET|g" swarm-stack.yml

echo "✅ Secret names configured"
echo ""

# =============================================================================
# SUMMARY
# =============================================================================
echo "📋 Configuration Summary"
echo "========================"
echo "Database Type:      $DB_TYPE"
echo "Database Mode:      $DB_MODE"
echo "Proxy Type:         $PROXY_TYPE"
echo "Docker Image:       $IMAGE_NAME:$IMAGE_VERSION"
if [ "$PROXY_TYPE" = "traefik" ]; then
    echo "API Domain:         $API_URL"
else
    echo "Published Port:     $PUBLISHED_PORT"
fi
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
# CREATE DOCKER SECRETS
# =============================================================================
echo "🔑 Create Docker Secrets"
echo "======================="
echo ""
echo "Let's create the required Docker secrets now."
echo ""

read -p "Create secrets now? (Y/n): " CREATE_SECRETS
if [[ ! "$CREATE_SECRETS" =~ ^[Nn]$ ]]; then
    echo ""
    echo "Creating Database Password Secret..."
    echo "-----------------------------------"
    echo "Opening editor for database password..."
    echo "Please enter the password, save, and close the editor."
    echo ""
    
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
    
    read -p "Press any key to enter secret for $DB_PASSWORD_SECRET..." -n 1 -r
    echo ""
    
    $EDITOR secret.txt
    docker secret create "$DB_PASSWORD_SECRET" secret.txt 2>/dev/null
    if [ $? -eq 0 ]; then
        echo "✅ Secret $DB_PASSWORD_SECRET created successfully"
    else
        echo "⚠️  Secret $DB_PASSWORD_SECRET may already exist"
    fi
    rm -f secret.txt
    echo ""
    
    echo "Creating Admin API Key Secret..."
    echo "--------------------------------"
    echo "Opening editor for admin API key..."
    echo "Please enter the API key, save, and close the editor."
    echo ""
    
    read -p "Press any key to enter secret for $ADMIN_API_KEY_SECRET..." -n 1 -r
    echo ""
    
    $EDITOR secret.txt
    docker secret create "$ADMIN_API_KEY_SECRET" secret.txt 2>/dev/null
    if [ $? -eq 0 ]; then
        echo "✅ Secret $ADMIN_API_KEY_SECRET created successfully"
    else
        echo "⚠️  Secret $ADMIN_API_KEY_SECRET may already exist"
    fi
    rm -f secret.txt
    echo ""
    
    echo "✅ Secrets created!"
    echo ""
    echo "List secrets with: docker secret ls"
    echo ""
else
    echo ""
    echo "⚠️  Skipped secret creation. You can create them manually:"
    echo ""
    echo "   # Database password secret"
    echo "   vi secret.txt  # Insert password (avoid backslashes) and save"
    echo "   docker secret create $DB_PASSWORD_SECRET secret.txt"
    echo "   rm secret.txt"
    echo ""
    echo "   # Admin API key secret"
    echo "   vi secret.txt  # Insert API key (avoid backslashes) and save"
    echo "   docker secret create $ADMIN_API_KEY_SECRET secret.txt"
    echo "   rm secret.txt"
    echo ""
fi

# =============================================================================
# NEXT STEPS
# =============================================================================
echo "🎉 Next Steps:"
echo "=============="
echo ""
if [ "$PROXY_TYPE" = "traefik" ]; then
    echo "1. Ensure your domain points to the swarm manager:"
    echo "   - Domain: $API_URL"
    echo "   - Should resolve to your swarm manager's IP"
    echo "   - Test with: nslookup $API_URL"
    echo "   - If not set up yet, see README.md (Domain Setup section)"
    echo ""
else
    echo "1. Ensure port $PUBLISHED_PORT is accessible:"
    echo "   - Port $PUBLISHED_PORT should be open in your firewall"
    echo "   - API will be accessible at: http://<your-server-ip>:$PUBLISHED_PORT"
    echo ""
fi
echo "2. Create data directories:"
echo "   mkdir -p $DATA_ROOT"
if [ "$DB_TYPE" = "postgresql" ]; then
    echo "   mkdir -p $DATA_ROOT/postgres_data"
elif [ "$DB_TYPE" = "neo4j" ]; then
    echo "   mkdir -p $DATA_ROOT/neo4j_data"
    echo "   mkdir -p $DATA_ROOT/neo4j_logs"
fi
echo "   mkdir -p $DATA_ROOT/redis_data"
echo ""
echo "3. Deploy to swarm:"
echo "   docker stack deploy -c <(docker-compose -f swarm-stack.yml config) $STACK_NAME"
echo ""
echo "   Or if using docker compose plugin:"
echo "   docker stack deploy -c <(docker compose -f swarm-stack.yml config) $STACK_NAME"
echo ""
echo "4. Check deployment status:"
echo "   docker stack services $STACK_NAME"
echo ""
echo "For more information, see README.md"
echo ""
