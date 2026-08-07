#!/bin/bash
# ==============================================================================
# init-site-data.sh - Initialize data directories for deployment
# ==============================================================================
#
# Reads DATA_ROOT and DB_TYPE from the root .env and creates the necessary
# persistent volume directories.
#
# Usage:
#   ./scripts/init-site-data.sh
#
# Dependencies:
#   - Root .env with DATA_ROOT and DB_TYPE
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Keep direct initialization output consistent with the operator menu.
source "${PROJECT_ROOT}/setup/modules/menu_formatting.sh"

ENV_FILE="${PROJECT_ROOT}/.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "Error: Root .env not found. Run setup-wizard.sh first."
    exit 1
fi

# Read values from .env
_env_val() {
    grep "^${1}=" "$ENV_FILE" 2>/dev/null | head -n 1 | cut -d'=' -f2- | tr -d '"' | tr -d '\r'
}

DATA_ROOT="$(_env_val DATA_ROOT)"
DB_TYPE="$(_env_val DB_TYPE)"
DB_MODE="$(_env_val DB_MODE)"

if [ -z "$DATA_ROOT" ]; then
    DATA_ROOT="$PROJECT_ROOT"
fi

echo "📁 Initializing data directories"
echo "  Data root: ${DATA_ROOT}"
echo "  Database:  ${DB_TYPE} (${DB_MODE})"
echo ""

# Always create redis data
mkdir -p "${DATA_ROOT}/redis_data"
echo "  ✅ ${DATA_ROOT}/redis_data"

# Always create backups
mkdir -p "${DATA_ROOT}/backups"
echo "  ✅ ${DATA_ROOT}/backups"

# Create database-specific directories (only for local mode)
if [ "$DB_MODE" = "local" ]; then
    case "$DB_TYPE" in
        postgresql)
            mkdir -p "${DATA_ROOT}/postgres_data"
            echo "  ✅ ${DATA_ROOT}/postgres_data"
            ;;
        mongodb)
            mkdir -p "${DATA_ROOT}/mongodb_data"
            echo "  ✅ ${DATA_ROOT}/mongodb_data"
            ;;
        neo4j)
            mkdir -p "${DATA_ROOT}/neo4j_data"
            mkdir -p "${DATA_ROOT}/neo4j_logs"
            echo "  ✅ ${DATA_ROOT}/neo4j_data"
            echo "  ✅ ${DATA_ROOT}/neo4j_logs"
            ;;
        none)
            echo "  ℹ️  No database directories needed (DB_TYPE=none)"
            ;;
        *)
            echo "  ⚠️  Unknown DB_TYPE '${DB_TYPE}'; skipping database dirs"
            ;;
    esac
fi

echo ""
echo "✅ Data directories initialized."
