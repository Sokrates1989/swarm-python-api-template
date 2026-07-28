#!/bin/bash
# ==============================================================================
# build-site-stack.sh - Build root swarm-stack.yml from compose modules
# ==============================================================================
#
# Reads the root .env to determine the selected profile. Any profile declaring
# renderer.type=executable uses the shared deterministic Python renderer.
# Profiles on older schemas continue through compose-module templates while
# they are migrated.
#
# Output: PROJECT_ROOT/swarm-stack.yml
#
# Usage:
#   ./scripts/build-site-stack.sh
#
# Dependencies:
#   - Root .env file with DB_TYPE, DB_MODE, PROXY_TYPE
#   - setup/modules/config-builder.sh
#   - setup/compose-modules/ templates and snippets
# ==============================================================================

set -e

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

ENV_FILE="${PROJECT_ROOT}/.env"

# Source config-builder module
source "${PROJECT_ROOT}/setup/modules/config-builder.sh"

# Verify .env exists
if [ ! -f "$ENV_FILE" ]; then
    echo "Error: Root .env not found. Run setup-wizard.sh first."
    exit 1
fi

# Read key values from .env
_env_val() {
    grep "^${1}=" "$ENV_FILE" 2>/dev/null | head -n 1 | cut -d'=' -f2- | tr -d '"' | tr -d '\r'
}

# _selected_renderer_type
# Resolves the renderer strategy from the root-selected site profile.
#
# Arguments:
#   None.
#
# Outputs:
#   Renderer type, defaulting to generic.
#
# Returns:
#   0 always.
_selected_renderer_type() {
    local profile_id=""
    local profile_file=""

    profile_id="$(_env_val DEPLOYMENT_PROFILE_ID)"
    profile_id="${profile_id:-$(_env_val BACKEND_APP_ID)}"
    profile_file="${PROJECT_ROOT}/site-configs/${profile_id}.json"
    if [ -n "$profile_id" ] &&
        [ -f "$profile_file" ] &&
        command -v jq >/dev/null 2>&1; then
        jq -r '.renderer.type // "generic"' "$profile_file"
        return 0
    fi
    echo "generic"
}

# Executable rendering owns the complete environment and Docker secret
# declarations. Do not feed these profiles through placeholder rewriting.
if [ "$(_selected_renderer_type)" = "executable" ]; then
    if command -v python3 >/dev/null 2>&1; then
        PYTHON_COMMAND="python3"
    elif command -v python >/dev/null 2>&1; then
        PYTHON_COMMAND="python"
    else
        echo "Error: Python 3 is required for executable profile rendering."
        exit 1
    fi
    exec "$PYTHON_COMMAND" "${PROJECT_ROOT}/scripts/site_profile.py" \
        --root "$PROJECT_ROOT" render --compose-check
fi

STACK_FAMILY="$(_env_val STACK_FAMILY)"
STACK_FAMILY="${STACK_FAMILY:-api}"
export STACK_FAMILY
DB_TYPE="$(_env_val DB_TYPE)"
DB_MODE="$(_env_val DB_MODE)"
PROXY_TYPE="$(_env_val PROXY_TYPE)"
STACK_NAME="$(_env_val STACK_NAME)"
STACK_ROLE="$(_env_val STACK_ROLE)"
export STACK_ROLE
REDIRECT_TARGET_BASE_URL="$(_env_val REDIRECT_TARGET_BASE_URL)"
export REDIRECT_TARGET_BASE_URL
REDIRECT_STATUS_CODE="$(_env_val REDIRECT_STATUS_CODE)"
export REDIRECT_STATUS_CODE

# Determine SSL mode from .env (check for TRAEFIK_TLS_CERTRESOLVER)
SSL_MODE="direct"
if grep -q "^TRAEFIK_TLS_CERTRESOLVER=letsencrypt" "$ENV_FILE" 2>/dev/null; then
    SSL_MODE="direct"
fi
# If the .env has proxy SSL mode stored explicitly
if grep -q "^SSL_MODE=proxy" "$ENV_FILE" 2>/dev/null; then
    SSL_MODE="proxy"
fi

echo "[BUILD] Building swarm-stack.yml"
echo "  Stack:    ${STACK_NAME}"
echo "  Family:   ${STACK_FAMILY}"
echo "  Role:     ${STACK_ROLE:-api}"
echo "  Database: ${DB_TYPE} (${DB_MODE})"
echo "  Proxy:    ${PROXY_TYPE} (SSL: ${SSL_MODE})"
echo ""

# Call config-builder's build_stack_file to assemble the stack
build_stack_file "$DB_TYPE" "$DB_MODE" "$PROXY_TYPE" "$PROJECT_ROOT" "$SSL_MODE"

# Post-process the generated stack to replace placeholders
STACK_FILE="${PROJECT_ROOT}/swarm-stack.yml"

# Derive secret names using the same pattern as the wizard
PREFIX_UPPER=$(echo "$(_env_val SECRETS_PREFIX)" | tr -d '_' | tr '[:lower:]' '[:upper:]' | sed 's/[^A-Z0-9]/_/g')
if [ -z "$PREFIX_UPPER" ]; then
    PREFIX_UPPER=$(echo "$STACK_NAME" | tr '-' '_' | tr '[:lower:]' '[:upper:]' | sed 's/[^A-Z0-9]/_/g')
fi

DB_PASSWORD_SECRET="${PREFIX_UPPER}_DB_PASSWORD"
ADMIN_API_KEY_SECRET="${PREFIX_UPPER}_ADMIN_API_KEY"
BACKUP_RESTORE_API_KEY_SECRET="${PREFIX_UPPER}_BACKUP_RESTORE_API_KEY"
BACKUP_DELETE_API_KEY_SECRET="${PREFIX_UPPER}_BACKUP_DELETE_API_KEY"
# Unified admin UI password secret (used for pgAdmin or Mongo Express)
DB_UI_ADMIN_PASSWORD_SECRET="${PREFIX_UPPER}_DB_UI_ADMIN_PASSWORD"

if [ "$STACK_FAMILY" = "nginx" ] || [ "$STACK_ROLE" = "internal-api" ]; then
    echo "[SECRETS] Skipping API secret placeholders for nginx-only / internal-api stack."
else
# Replace secret placeholders
echo "[SECRETS] Updating secret name placeholders..."
echo "  - DB: $DB_PASSWORD_SECRET"
echo "  - Admin API: $ADMIN_API_KEY_SECRET"
echo "  - Backup Restore: $BACKUP_RESTORE_API_KEY_SECRET"
echo "  - Backup Delete: $BACKUP_DELETE_API_KEY_SECRET"
echo "  - Admin UI (pgAdmin/Mongo Express): $DB_UI_ADMIN_PASSWORD_SECRET"
update_stack_secrets "$STACK_FILE" "$DB_PASSWORD_SECRET" "$ADMIN_API_KEY_SECRET" "$BACKUP_RESTORE_API_KEY_SECRET" "$BACKUP_DELETE_API_KEY_SECRET" "$DB_UI_ADMIN_PASSWORD_SECRET"
fi

# Handle Traefik network placeholder
if [ "$PROXY_TYPE" = "traefik" ]; then
    # Get Traefik network name from .env or default to "traefik"
    TRAEFIK_NETWORK="$(_env_val TRAEFIK_NETWORK)"
    if [ -z "$TRAEFIK_NETWORK" ]; then
        TRAEFIK_NETWORK="traefik"
    fi
    echo "[NETWORK] Updating Traefik network placeholder: $TRAEFIK_NETWORK"
    update_stack_network "$STACK_FILE" "$TRAEFIK_NETWORK"
elif [ "$PROXY_TYPE" = "none" ]; then
    # Remove the Traefik network placeholder when not using Traefik
    echo "[NETWORK] Removing Traefik network placeholder (PROXY_TYPE=none)"
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        sed -i '' '/XXX_CHANGE_ME_TRAEFIK_NETWORK_NAME_XXX:/d' "$STACK_FILE"
    else
        # Linux
        sed -i '/XXX_CHANGE_ME_TRAEFIK_NETWORK_NAME_XXX:/d' "$STACK_FILE"
    fi
fi

# Replace stack name placeholder
echo "[STACK] Updating stack name placeholder: $STACK_NAME"
if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i '' "s|XXX_CHANGE_ME_STACK_NAME_XXX|$STACK_NAME|g" "$STACK_FILE"
else
    sed -i "s|XXX_CHANGE_ME_STACK_NAME_XXX|$STACK_NAME|g" "$STACK_FILE"
fi

echo ""
echo "[OK] Stack build complete. All placeholders resolved."
echo ""
echo "To deploy with .env interpolation, use the quick-start deploy option:"
echo "  ./quick-start.sh"
echo ""
echo "Manual Bash equivalent:"
echo "  set -a; source .env; set +a"
echo "  docker stack deploy -c <(docker compose -f swarm-stack.yml config) ${STACK_NAME}"
