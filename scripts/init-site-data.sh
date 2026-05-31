#!/bin/bash

# Initialize data directories for a site
# Creates the necessary directory structure for site data

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [ $# -ne 1 ]; then
    echo "Usage: $0 <site-id>"
    echo "Example: $0 api-demo"
    exit 1
fi

SITE_ID="$1"
DEPLOYMENT_DIR="${PROJECT_ROOT}/deployments/${SITE_ID}"
DATA_DIR="${DEPLOYMENT_DIR}/data"

# Check if site exists
if [ ! -f "${PROJECT_ROOT}/site-configs/${SITE_ID}.json" ]; then
    echo "Error: Site '${SITE_ID}' not found in site-configs/"
    exit 1
fi

# Load database type from config
DB_TYPE=$(jq -r '.database.type' "${PROJECT_ROOT}/site-configs/${SITE_ID}.json")

echo "Initializing data directories for site: ${SITE_ID}"
echo "  Database type: ${DB_TYPE}"
echo ""

# Create base directories
mkdir -p "${DATA_DIR}/logs"
mkdir -p "${DATA_DIR}/redis"

# Create database-specific directories
case "$DB_TYPE" in
    postgresql)
        mkdir -p "${DATA_DIR}/postgres"
        echo "  Created: ${DATA_DIR}/postgres"
        ;;
    mongodb)
        mkdir -p "${DATA_DIR}/mongodb"
        echo "  Created: ${DATA_DIR}/mongodb"
        ;;
    *)
        echo "Warning: Unknown database type '${DB_TYPE}'"
        ;;
esac

echo "  Created: ${DATA_DIR}/redis"
echo "  Created: ${DATA_DIR}/logs"

echo ""
echo "Data directories initialized for ${SITE_ID}"
