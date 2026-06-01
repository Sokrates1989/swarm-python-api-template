#!/bin/bash
# ==============================================================================
# validate-site.sh - Deployment validation for root-level model
# ==============================================================================
#
# Validates that the root .env, swarm-stack.yml, secrets, and compose modules
# are consistent and ready for deployment.
#
# Usage:
#   ./scripts/validate-site.sh
#
# Checks performed:
#   1. Root .env exists and contains required keys.
#   2. swarm-stack.yml exists.
#   3. Compose module templates exist for the configured DB type.
#   4. Expected Docker secrets exist.
#   5. App config referenced by BACKEND_APP_ID exists.
#
# Exit codes:
#   0 - All checks passed.
#   1 - One or more checks failed.
#
# Dependencies:
#   - jq (optional, for app config checks)
#   - Docker (for secret checks)
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ===========================================================================
# Helpers
# ===========================================================================

PASS_COUNT=0
WARN_COUNT=0
FAIL_COUNT=0

_pass() {
    echo "  ✅ $1"
    PASS_COUNT=$((PASS_COUNT + 1))
}

_warn() {
    echo "  ⚠️  $1"
    WARN_COUNT=$((WARN_COUNT + 1))
}

_fail() {
    echo "  ❌ $1"
    FAIL_COUNT=$((FAIL_COUNT + 1))
}

# _env_val - Read a value from the root .env
_env_val() {
    grep "^${1}=" "${PROJECT_ROOT}/.env" 2>/dev/null | head -n 1 | cut -d'=' -f2- | tr -d '"' | tr -d '\r'
}

# ===========================================================================
# Main validation
# ===========================================================================

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Deployment Validation"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# --- Check 1: Root .env ---
echo "  [Environment]"
ENV_FILE="${PROJECT_ROOT}/.env"
if [ ! -f "$ENV_FILE" ]; then
    _fail "Root .env not found. Run setup-wizard.sh first."
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  ❌ Validation cannot continue without .env"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    exit 1
fi
_pass "Root .env exists"

# Check required keys
REQUIRED_KEYS=("STACK_NAME" "IMAGE_NAME" "IMAGE_VERSION" "DB_TYPE" "DB_MODE" "PROXY_TYPE")
for key in "${REQUIRED_KEYS[@]}"; do
    if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
        _pass ".env contains ${key}"
    else
        _fail ".env missing required key: ${key}"
    fi
done

# Read key values
STACK_NAME="$(_env_val STACK_NAME)"
DB_TYPE="$(_env_val DB_TYPE)"
DB_MODE="$(_env_val DB_MODE)"
PROXY_TYPE="$(_env_val PROXY_TYPE)"
BACKEND_APP_ID="$(_env_val BACKEND_APP_ID)"
SECRETS_PREFIX="$(_env_val SECRETS_PREFIX)"

# --- Check 2: swarm-stack.yml ---
echo ""
echo "  [Stack File]"
STACK_FILE="${PROJECT_ROOT}/swarm-stack.yml"
if [ -f "$STACK_FILE" ]; then
    _pass "swarm-stack.yml exists"
else
    _warn "swarm-stack.yml not found (run: ./scripts/build-site-stack.sh)"
fi

# --- Check 3: Compose modules ---
echo ""
echo "  [Compose Modules]"
MODULES_DIR="${PROJECT_ROOT}/setup/compose-modules"

if [ -f "${MODULES_DIR}/api.template.yml" ]; then
    _pass "api.template.yml exists"
else
    _fail "api.template.yml missing"
fi

if [ -f "${MODULES_DIR}/base.yml" ]; then
    _pass "base.yml exists"
else
    _fail "base.yml missing"
fi

if [ -f "${MODULES_DIR}/footer.yml" ]; then
    _pass "footer.yml exists"
else
    _fail "footer.yml missing"
fi

# Database module check
if [ "$DB_TYPE" != "none" ] && [ "$DB_MODE" = "local" ]; then
    db_file_name="$DB_TYPE"
    if [ "$DB_TYPE" = "postgresql" ]; then
        db_file_name="postgres"
    fi
    db_module="${MODULES_DIR}/${db_file_name}-local.yml"
    if [ -f "$db_module" ]; then
        _pass "${db_file_name}-local.yml exists"
    else
        _warn "${db_file_name}-local.yml not found (needed for local ${DB_TYPE})"
    fi
fi

# --- Check 4: Secrets ---
echo ""
echo "  [Secrets]"
if [ -n "$SECRETS_PREFIX" ]; then
    EXPECTED_SECRETS=(
        "${SECRETS_PREFIX}DB_PASSWORD"
        "${SECRETS_PREFIX}ADMIN_API_KEY"
        "${SECRETS_PREFIX}BACKUP_RESTORE_API_KEY"
        "${SECRETS_PREFIX}BACKUP_DELETE_API_KEY"
    )

    for secret_name in "${EXPECTED_SECRETS[@]}"; do
        if docker secret inspect "$secret_name" &>/dev/null; then
            _pass "Secret exists: ${secret_name}"
        else
            _warn "Secret missing: ${secret_name}"
        fi
    done
else
    _warn "No SECRETS_PREFIX in .env; skipping secret validation"
fi

# --- Check 5: App config reference ---
echo ""
echo "  [App Config]"
if [ -n "$BACKEND_APP_ID" ]; then
    # Look for a matching app config
    app_config_found=false
    for cfg in "${PROJECT_ROOT}/site-configs/"*.json; do
        [ -f "$cfg" ] || continue
        cfg_id=$(basename "$cfg" .json)
        [ "$cfg_id" = "_template" ] && continue
        if command -v jq &>/dev/null; then
            app_id=$(jq -r '.appId // empty' "$cfg" 2>/dev/null)
            if [ "$app_id" = "$BACKEND_APP_ID" ]; then
                app_config_found=true
                _pass "App config found for BACKEND_APP_ID='${BACKEND_APP_ID}': $(basename "$cfg")"
                break
            fi
        fi
    done
    if [ "$app_config_found" = false ]; then
        if command -v jq &>/dev/null; then
            _warn "No app config found matching BACKEND_APP_ID='${BACKEND_APP_ID}'"
        else
            _warn "jq not installed; cannot verify app config reference"
        fi
    fi
else
    _warn "BACKEND_APP_ID not set in .env"
fi

# ===========================================================================
# Summary
# ===========================================================================

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Validation Summary"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  ✅ Passed:   ${PASS_COUNT}"
echo "  ⚠️  Warnings: ${WARN_COUNT}"
echo "  ❌ Failed:   ${FAIL_COUNT}"
echo ""

if [ "$FAIL_COUNT" -gt 0 ]; then
    echo "❌ Validation failed with ${FAIL_COUNT} error(s)."
    exit 1
else
    echo "✅ All checks passed."
    exit 0
fi
