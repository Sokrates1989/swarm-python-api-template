#!/bin/bash
# ==============================================================================
# setup-wizard.sh - Interactive deployment setup wizard
# ==============================================================================
#
# Configures this deployment instance by collecting user input and generating
# the root .env and root swarm-stack.yml.
#
# The wizard reads an app deployment manifest from site-configs/ to know what
# the backend app needs (database type, services, image). It then asks for
# deployment-time values (domain, proxy, secrets, image version) that are
# only known on the actual server.
#
# Flow:
#   1. Select which app config to use (from site-configs/).
#   2. Collect deployment-time values (domain, stack name, proxy, SSL, image
#      version, secret prefix, data root).
#   3. Generate root .env.
#   4. Build root swarm-stack.yml (from compose modules).
#   5. Offer final actions: save only / create data dirs / create secrets /
#      deploy.
#
# Dependencies:
#   - jq
#   - Docker (for secrets, deploy)
#   - Modules: site_helpers, user-prompts, config-builder, data-dirs,
#     secret-manager, stack-conflict-check, deploy-stack, health-check
# ==============================================================================

set -e

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# ===========================================================================
# Source modules
# ===========================================================================

source "$SCRIPT_DIR/modules/site_helpers.sh"
source "$SCRIPT_DIR/modules/user-prompts.sh"
source "$SCRIPT_DIR/modules/config-builder.sh"
source "$SCRIPT_DIR/modules/network-check.sh"
source "$SCRIPT_DIR/modules/data-dirs.sh"
source "$SCRIPT_DIR/modules/secret-manager.sh"
source "$SCRIPT_DIR/modules/stack-conflict-check.sh"
source "$SCRIPT_DIR/modules/deploy-stack.sh"
source "$SCRIPT_DIR/modules/health-check.sh"

# Source Cognito setup script if available
if [ -f "${SCRIPT_DIR}/modules/cognito_setup.sh" ]; then
    # shellcheck disable=SC1091
    source "${SCRIPT_DIR}/modules/cognito_setup.sh"
fi

# ===========================================================================
# jq check
# ===========================================================================

if ! command -v jq &>/dev/null; then
    echo "❌ jq is required but not installed."
    echo "   Install it with: sudo apt-get install jq"
    exit 1
fi

# =============================================================================
# WELCOME
# =============================================================================

echo ""
echo "🚀 Swarm Python API Template - Setup Wizard"
echo "============================================="
echo ""
echo "This wizard configures this deployment instance."
echo "Each clone of this repo IS one deployed API."
echo ""
echo "  • .env and swarm-stack.yml are generated at the project root."
echo "  • site-configs/ holds deployment profiles describing what this deployment needs."
echo ""

# =============================================================================
# STEP 1: Select Deployment Profile
# =============================================================================

echo "Step 1: Select the deployment profile for this instance."
echo ""

SELECTED_CONFIG=$(show_app_selector "$PROJECT_ROOT")

if [ "$SELECTED_CONFIG" = "EXIT" ] || [ -z "$SELECTED_CONFIG" ]; then
    echo "No deployment profile selected. Exiting."
    exit 0
fi

# Load app manifest for defaults
load_app_config "$PROJECT_ROOT" "$SELECTED_CONFIG"

echo ""
echo "✅ Selected deployment profile: ${APP_NAME} (${SELECTED_CONFIG})"
echo "   Database: ${APP_DB_TYPE}, Image: ${APP_IMAGE_NAME}:${APP_IMAGE_DEFAULT_VERSION}"
echo ""

# Load existing .env values as defaults (if re-running wizard)
EXISTING_STACK_NAME=""
EXISTING_DOMAIN=""
EXISTING_PROXY_TYPE=""
EXISTING_SSL_MODE=""
EXISTING_IMAGE_VERSION=""
EXISTING_SECRET_PREFIX=""
EXISTING_DATA_ROOT=""
EXISTING_DB_MODE=""

if [ -f "${PROJECT_ROOT}/.env" ]; then
    load_root_env "$PROJECT_ROOT"
    EXISTING_STACK_NAME="$STACK_NAME"
    EXISTING_DOMAIN="$DOMAIN"
    EXISTING_PROXY_TYPE="$PROXY_TYPE"
    EXISTING_IMAGE_VERSION="$IMAGE_VERSION"
    EXISTING_SECRET_PREFIX="$SECRET_PREFIX"
    EXISTING_DB_MODE="$DB_MODE"
    EXISTING_DATA_ROOT="$DATA_ROOT"
    echo "ℹ️  Existing .env found. Press Enter to keep current values."
    echo ""
fi

# =============================================================================
# STEP 2: Deployment-Time Configuration
# =============================================================================
#
# These are values only known at deployment time — the wizard asks for them
# and uses app manifest defaults where applicable.

echo ""
echo "📋 Step 2: Deployment Configuration"
echo "===================================="
echo ""
echo "These values are specific to THIS deployment instance."
echo ""

# Stack name - generate from app name if no existing value
if [ -n "$EXISTING_STACK_NAME" ]; then
    DEFAULT_STACK_NAME="$EXISTING_STACK_NAME"
else
    # Convert app name to stack-friendly format (lowercase, spaces to hyphens)
    DEFAULT_STACK_NAME=$(echo "$APP_NAME" | tr '[:upper:]' '[:lower:]' | tr ' ' '-' | tr '_' '-')
fi
read -p "Docker stack name [${DEFAULT_STACK_NAME}]: " STACK_NAME
STACK_NAME="${STACK_NAME:-$DEFAULT_STACK_NAME}"

# Domain
DEFAULT_DOMAIN="${EXISTING_DOMAIN:-}"
read -p "Domain (e.g. api.example.com) [${DEFAULT_DOMAIN}]: " DOMAIN
DOMAIN="${DOMAIN:-$DEFAULT_DOMAIN}"

# Secret prefix
DEFAULT_SECRET_PREFIX="${EXISTING_SECRET_PREFIX:-$(echo "$STACK_NAME" | tr '-' '_')}"
read -p "Secret prefix [${DEFAULT_SECRET_PREFIX}]: " SECRET_PREFIX
SECRET_PREFIX="${SECRET_PREFIX:-$DEFAULT_SECRET_PREFIX}"

# Database mode (app manifest knows the type, user picks mode)
DB_TYPE="$APP_DB_TYPE"
echo ""
echo "Database type (from deployment profile): ${DB_TYPE}"

DB_MODE="$APP_DB_DEFAULT_MODE"
if [ "$DB_TYPE" != "none" ]; then
    echo ""
    echo "Database mode:"
    echo "  1) Local (deploy in swarm)"
    echo "  2) External (existing server)"
    echo ""
    case "${EXISTING_DB_MODE:-$APP_DB_DEFAULT_MODE}" in
        external) dbm_default="2" ;;
        *)        dbm_default="1" ;;
    esac
    read -p "Your choice (1-2) [$dbm_default]: " DBM_CHOICE
    DBM_CHOICE="${DBM_CHOICE:-$dbm_default}"
    case "$DBM_CHOICE" in
        2) DB_MODE="external" ;;
        *) DB_MODE="local" ;;
    esac
    echo "✅ DB mode: $DB_MODE"
fi

# Proxy
echo ""
echo "Proxy type:"
echo "  1) Traefik (automatic HTTPS)"
echo "  2) None (direct port)"
echo ""
case "${EXISTING_PROXY_TYPE:-traefik}" in
    none) proxy_default="2" ;;
    *)    proxy_default="1" ;;
esac
read -p "Your choice (1-2) [$proxy_default]: " PROXY_CHOICE
PROXY_CHOICE="${PROXY_CHOICE:-$proxy_default}"
case "$PROXY_CHOICE" in
    2) PROXY_TYPE="none" ;;
    *) PROXY_TYPE="traefik" ;;
esac
echo "✅ Proxy: $PROXY_TYPE"

# SSL mode (Traefik only)
SSL_MODE="letsencrypt"
if [ "$PROXY_TYPE" = "traefik" ]; then
    echo ""
    echo "SSL mode:"
    echo "  1) letsencrypt (Traefik obtains certificate)"
    echo "  2) proxy (SSL terminated upstream, e.g. Cloudflare)"
    echo ""
    read -p "Your choice (1-2) [1]: " SSL_CHOICE
    SSL_CHOICE="${SSL_CHOICE:-1}"
    case "$SSL_CHOICE" in
        2) SSL_MODE="proxy" ;;
        *) SSL_MODE="letsencrypt" ;;
    esac
    echo "✅ SSL: $SSL_MODE"
fi

# Docker image
echo ""
echo "🐳 Docker Image"
DEFAULT_IMAGE_NAME="${APP_IMAGE_NAME}"
DEFAULT_IMAGE_VERSION="${EXISTING_IMAGE_VERSION:-$APP_IMAGE_DEFAULT_VERSION}"
read -p "Image name [$DEFAULT_IMAGE_NAME]: " IMAGE_NAME
IMAGE_NAME="${IMAGE_NAME:-$DEFAULT_IMAGE_NAME}"
read -p "Image version [$DEFAULT_IMAGE_VERSION]: " IMAGE_VERSION
IMAGE_VERSION="${IMAGE_VERSION:-$DEFAULT_IMAGE_VERSION}"
echo "✅ Image: $IMAGE_NAME:$IMAGE_VERSION"

# Resources
echo ""
DEFAULT_REPLICAS="${APP_DEFAULT_REPLICAS}"
DEFAULT_MEMORY="${APP_DEFAULT_MEMORY_LIMIT}"
read -p "API replicas [$DEFAULT_REPLICAS]: " API_REPLICAS
API_REPLICAS="${API_REPLICAS:-$DEFAULT_REPLICAS}"
read -p "Memory limit [$DEFAULT_MEMORY]: " MEMORY_LIMIT
MEMORY_LIMIT="${MEMORY_LIMIT:-$DEFAULT_MEMORY}"

# Data root
echo ""
DEFAULT_DATA_ROOT="${EXISTING_DATA_ROOT:-$PROJECT_ROOT}"
read -p "Data root path [$DEFAULT_DATA_ROOT]: " DATA_ROOT
DATA_ROOT="${DATA_ROOT:-$DEFAULT_DATA_ROOT}"

# =============================================================================
# STEP 3: Generate root .env
# =============================================================================

echo ""
echo "📝 Generating .env at project root..."

ENV_FILE="${PROJECT_ROOT}/.env"

{
    echo "# Generated by setup-wizard.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "# Deployment profile: ${SELECTED_CONFIG}"
    echo ""
    echo "# Deployment Identity"
    echo "STACK_NAME=${STACK_NAME}"
    echo "DOMAIN=${DOMAIN}"
    echo "DEPLOYMENT_PROFILE_ID=${SELECTED_CONFIG}"
    echo "BACKEND_APP_ID=${APP_ID}"
    echo ""
    echo "# Database"
    echo "DB_TYPE=${DB_TYPE}"
    echo "DB_MODE=${DB_MODE}"
} > "$ENV_FILE"

# Database-specific env vars
if [ "$DB_TYPE" = "postgresql" ] && [ "$DB_MODE" = "local" ]; then
    {
        echo "POSTGRES_HOST=postgres"
        echo "POSTGRES_PORT=5432"
        echo "POSTGRES_DB=${STACK_NAME//-/_}_db"
        echo "POSTGRES_USER=${STACK_NAME//-/_}_user"
        echo "POSTGRES_PASSWORD_FILE=/run/secrets/${SECRET_PREFIX}_DB_PASSWORD"
    } >> "$ENV_FILE"
elif [ "$DB_TYPE" = "mongodb" ] && [ "$DB_MODE" = "local" ]; then
    {
        echo "MONGODB_HOST=mongodb"
        echo "MONGODB_PORT=27017"
        echo "MONGODB_DB=${STACK_NAME//-/_}_db"
        echo "MONGODB_USER=${STACK_NAME//-/_}_user"
        echo "MONGODB_PASSWORD_FILE=/run/secrets/${SECRET_PREFIX}_DB_PASSWORD"
    } >> "$ENV_FILE"
elif [ "$DB_TYPE" = "neo4j" ] && [ "$DB_MODE" = "local" ]; then
    {
        echo "NEO4J_HOST=neo4j"
        echo "NEO4J_PORT=7687"
        echo "NEO4J_AUTH_FILE=/run/secrets/${SECRET_PREFIX}_DB_PASSWORD"
    } >> "$ENV_FILE"
fi

{
    echo ""
    echo "# Redis"
    echo "REDIS_HOST=redis"
    echo "REDIS_PORT=6379"
    echo ""
    echo "# Docker Image"
    echo "IMAGE_NAME=${IMAGE_NAME}"
    echo "IMAGE_VERSION=${IMAGE_VERSION}"
    echo ""
    echo "# Resources"
    echo "API_REPLICAS=${API_REPLICAS}"
    echo "MEMORY_LIMIT=${MEMORY_LIMIT}"
    echo ""
    echo "# Data"
    echo "DATA_ROOT=${DATA_ROOT}"
    echo ""
    echo "# Proxy"
    echo "PROXY_TYPE=${PROXY_TYPE}"
} >> "$ENV_FILE"

if [ "$PROXY_TYPE" = "traefik" ]; then
    {
        echo "TRAEFIK_ROUTER_NAME=${STACK_NAME}"
        echo "TRAEFIK_RULE=Host(\`${DOMAIN}\`)"
        echo "TRAEFIK_ENTRYPOINT=websecure"
        if [ "$SSL_MODE" = "letsencrypt" ]; then
            echo "TRAEFIK_TLS_CERTRESOLVER=letsencrypt"
        fi
    } >> "$ENV_FILE"
fi

{
    echo ""
    echo "# Secrets"
    echo "SECRETS_PREFIX=${SECRET_PREFIX}_"
} >> "$ENV_FILE"

echo "✅ .env written: $ENV_FILE"

# =============================================================================
# STEP 4: Build swarm-stack.yml
# =============================================================================

echo ""
echo "📝 Building swarm-stack.yml..."

STACK_FILE="${PROJECT_ROOT}/swarm-stack.yml"

if [ -x "${PROJECT_ROOT}/scripts/build-site-stack.sh" ]; then
    "${PROJECT_ROOT}/scripts/build-site-stack.sh" || true
else
    echo "⚠️  build-site-stack.sh not found. You can build manually later."
fi

# =============================================================================
# STEP 5: Final Actions Menu
# =============================================================================

echo ""
echo "============================================"
echo "  ✅ Configuration complete!"
echo "============================================"
echo ""
echo "  Stack Name:   $STACK_NAME"
echo "  Domain:       $DOMAIN"
echo "  App:          $APP_NAME ($APP_ID)"
echo "  Database:     $DB_TYPE ($DB_MODE)"
echo "  Image:        $IMAGE_NAME:$IMAGE_VERSION"
echo "  .env:         $ENV_FILE"
echo ""
echo "What would you like to do next?"
echo "  1) Done (save only)"
echo "  2) Create data directories"
echo "  3) Create Docker secrets"
echo "  4) Deploy to Docker Swarm"
echo "  5) Full deploy (data dirs + secrets + deploy)"
echo ""
read -p "Your choice (1-5) [1]: " FINAL_ACTION
FINAL_ACTION="${FINAL_ACTION:-1}"

# Derive secret names
PREFIX_UPPER=$(echo "$SECRET_PREFIX" | tr '[:lower:]' '[:upper:]' | sed 's/[^A-Z0-9]/_/g')
DB_PASSWORD_SECRET="${PREFIX_UPPER}_DB_PASSWORD"
ADMIN_API_KEY_SECRET="${PREFIX_UPPER}_ADMIN_API_KEY"
BACKUP_RESTORE_API_KEY_SECRET="${PREFIX_UPPER}_BACKUP_RESTORE_API_KEY"
BACKUP_DELETE_API_KEY_SECRET="${PREFIX_UPPER}_BACKUP_DELETE_API_KEY"

case "$FINAL_ACTION" in
    1)
        echo ""
        echo "✅ Configuration saved. No further actions taken."
        echo ""
        echo "Next steps you can do manually:"
        echo "  • Create data dirs:   mkdir -p ${DATA_ROOT}/{postgres_data,redis_data}"
        echo "  • Create secrets:     ./quick-start.sh → Manage Docker secrets"
        echo "  • Deploy:             docker stack deploy -c swarm-stack.yml $STACK_NAME"
        ;;
    2)
        echo ""
        create_data_directories "$DATA_ROOT" "$DB_TYPE"
        echo ""
        echo "✅ Data directories initialized."
        ;;
    3)
        echo ""
        echo "🔐 Creating secrets with prefix: ${PREFIX_UPPER}_*"
        create_docker_secrets "$DB_PASSWORD_SECRET" "$ADMIN_API_KEY_SECRET" "$BACKUP_RESTORE_API_KEY_SECRET" "$BACKUP_DELETE_API_KEY_SECRET"
        echo ""
        echo "✅ Secrets created."
        ;;
    4)
        echo ""
        echo "� Deploying..."
        if [ -f "$STACK_FILE" ]; then
            check_stack_conflict "$STACK_NAME"
            deploy_stack "$STACK_NAME" "$STACK_FILE"
            echo ""
            check_deployment_health "$STACK_NAME" "$DB_TYPE" "$PROXY_TYPE" "$DOMAIN" 20
        else
            echo "⚠️  swarm-stack.yml not found. Build it first."
        fi
        ;;
    5)
        echo ""
        echo "🚀 Full deploy sequence"
        echo ""

        echo "--- Step 1/3: Data directories ---"
        create_data_directories "$DATA_ROOT" "$DB_TYPE"
        echo ""

        echo "--- Step 2/3: Secrets ---"
        create_docker_secrets "$DB_PASSWORD_SECRET" "$ADMIN_API_KEY_SECRET" "$BACKUP_RESTORE_API_KEY_SECRET" "$BACKUP_DELETE_API_KEY_SECRET"
        echo ""

        echo "--- Step 3/3: Deploy ---"
        if [ -f "$STACK_FILE" ]; then
            check_stack_conflict "$STACK_NAME"
            deploy_stack "$STACK_NAME" "$STACK_FILE"
            echo ""
            check_deployment_health "$STACK_NAME" "$DB_TYPE" "$PROXY_TYPE" "$DOMAIN" 20
        else
            echo "⚠️  swarm-stack.yml not found at root. Build it first."
        fi
        ;;
    *)
        echo "Invalid choice. No action taken."
        ;;
esac

echo ""
echo "🎉 Setup wizard complete!"
echo ""
