#!/bin/bash

# Build Docker Swarm stack for a specific site
# Reads site configuration from site-configs/{SiteId}.json
# Generates deployments/{SiteId}/swarm-stack.yml

set -e

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Check arguments
if [ $# -ne 1 ]; then
    echo "Usage: $0 <site-id>"
    echo "Example: $0 api-demo"
    exit 1
fi

SITE_ID="$1"
CONFIG_PATH="${PROJECT_ROOT}/site-configs/${SITE_ID}.json"
DEPLOYMENT_DIR="${PROJECT_ROOT}/deployments/${SITE_ID}"
ENV_FILE="${DEPLOYMENT_DIR}/.env"
OUTPUT_FILE="${DEPLOYMENT_DIR}/swarm-stack.yml"

# Verify site config exists
if [ ! -f "$CONFIG_PATH" ]; then
    echo "Error: Site configuration not found: $CONFIG_PATH"
    exit 1
fi

# Load site config
SITE_NAME=$(jq -r '.name' "$CONFIG_PATH")
DOMAIN=$(jq -r '.domain' "$CONFIG_PATH")
DB_TYPE=$(jq -r '.database.type' "$CONFIG_PATH")
DB_MODE=$(jq -r '.database.mode' "$CONFIG_PATH")

echo "Building stack for site: ${SITE_ID}"
echo "  Name: ${SITE_NAME}"
echo "  Domain: ${DOMAIN}"
echo "  Database: ${DB_TYPE} (${DB_MODE})"

# Build compose file list
COMPOSE_FILES=()

# 1. Base (networks, secrets)
BASE_FILE="${PROJECT_ROOT}/deployments/_base/base.yml"
if [ -f "$BASE_FILE" ]; then
    COMPOSE_FILES+=("$BASE_FILE")
fi

# 2. Site-specific files (in order)
SITE_FILES=(
    "${DEPLOYMENT_DIR}/api.yml"
)

# 3. Database module (type-specific)
case "$DB_TYPE" in
    postgresql)
        if [ "$DB_MODE" = "local" ]; then
            POSTGRES_FILE="${DEPLOYMENT_DIR}/postgres.yml"
            if [ -f "$POSTGRES_FILE" ]; then
                SITE_FILES+=("$POSTGRES_FILE")
            fi
        fi
        ;;
    *)
        echo "Warning: Unsupported database type: $DB_TYPE"
        ;;
esac

# Add all site files
for file in "${SITE_FILES[@]}"; do
    if [ -f "$file" ]; then
        COMPOSE_FILES+=("$file")
    else
        echo "Warning: Missing compose file: $file"
    fi
done

echo ""
echo "Compose files to merge:"
for file in "${COMPOSE_FILES[@]}"; do
    echo "  - $(basename "$file")"
done

# Build docker compose arguments
DOCKER_ARGS=()
for file in "${COMPOSE_FILES[@]}"; do
    DOCKER_ARGS+=("-f" "$file")
done
DOCKER_ARGS+=("--env-file" "$ENV_FILE")
DOCKER_ARGS+=("config")

echo ""
echo "Generating swarm-stack.yml..."

# Generate stack using docker compose config
docker compose "${DOCKER_ARGS[@]}" > "$OUTPUT_FILE"

if [ $? -eq 0 ]; then
    echo "Stack generated: $OUTPUT_FILE"
    echo ""
    echo "To deploy this site, run:"
    echo "  docker stack deploy -c ${OUTPUT_FILE} ${SITE_ID}"
else
    echo "Error: Failed to generate stack"
    exit 1
fi
