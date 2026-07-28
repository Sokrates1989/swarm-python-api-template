#!/bin/bash
# ==============================================================================
# validate-site.sh - Deployment validation for root-level model
# ==============================================================================
#
# Validates that the root public profile, swarm-stack.yml, secrets, and compose
# modules are consistent. Any site profile declaring renderer.type=executable
# validates its exact JSON contract and resolved Compose artifact before older
# schema checks.
#
# Usage:
#   ./scripts/validate-site.sh
#
# Checks performed:
#   1. Root .env exists and contains required keys.
#   2. swarm-stack.yml exists.
#   3. Compose module templates exist for the configured DB type.
#   4. Expected Docker secrets exist.
#   5. Deployment profile referenced by .env exists.
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
    echo "  [OK] $1"
    PASS_COUNT=$((PASS_COUNT + 1))
}

_warn() {
    echo "  [WARN] $1"
    WARN_COUNT=$((WARN_COUNT + 1))
}

_fail() {
    echo "  [ERROR] $1"
    FAIL_COUNT=$((FAIL_COUNT + 1))
}

# _env_val - Read a value from the root .env
_env_val() {
    grep "^${1}=" "${PROJECT_ROOT}/.env" 2>/dev/null | head -n 1 | cut -d'=' -f2- | tr -d '"' | tr -d '\r'
}

# _selected_renderer_type
# Resolves the renderer strategy from the root-selected site config.
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

# ===========================================================================
# Main validation
# ===========================================================================

echo ""
echo "========================================"
echo "  Deployment Validation"
echo "========================================"
echo ""

# --- Check 1: Root .env ---
echo "  [Environment]"
ENV_FILE="${PROJECT_ROOT}/.env"
if [ ! -f "$ENV_FILE" ]; then
    _fail "Root .env not found. Run setup-wizard.sh first."
    echo ""
    echo "========================================"
    echo "  [ERROR] Validation cannot continue without .env"
    echo "========================================"
    exit 1
fi
_pass "Root .env exists"

# Executable validation must not fall through to older schema checks or their
# prefixed secret assumptions.
if [ "$(_selected_renderer_type)" = "executable" ]; then
    if command -v python3 >/dev/null 2>&1; then
        PYTHON_COMMAND="python3"
    elif command -v python >/dev/null 2>&1; then
        PYTHON_COMMAND="python"
    else
        _fail "Python 3 is required for executable profile validation."
        exit 1
    fi
    exec "$PYTHON_COMMAND" "${PROJECT_ROOT}/scripts/site_profile.py" \
        --root "$PROJECT_ROOT" validate-stack --compose-check
fi

# Determine stack family before required-key validation.
STACK_FAMILY="$(_env_val STACK_FAMILY)"
STACK_FAMILY="${STACK_FAMILY:-api}"

# Check required keys
if [ "$STACK_FAMILY" = "nginx" ]; then
    REQUIRED_KEYS=("STACK_NAME" "IMAGE_NAME" "IMAGE_VERSION" "PROXY_TYPE" "PORT")
else
    REQUIRED_KEYS=("STACK_NAME" "IMAGE_NAME" "IMAGE_VERSION" "DB_TYPE" "DB_MODE" "PROXY_TYPE")
fi
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
DEPLOYMENT_PROFILE_ID="$(_env_val DEPLOYMENT_PROFILE_ID)"
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

if [ "$STACK_FAMILY" = "nginx" ]; then
    if [ -f "${MODULES_DIR}/nginx/nginx.template.yml" ]; then
        _pass "nginx.template.yml exists"
    else
        _fail "nginx.template.yml missing"
    fi
    if [ -f "${MODULES_DIR}/nginx/footer.yml" ]; then
        _pass "nginx/footer.yml exists"
    else
        _fail "nginx/footer.yml missing"
    fi
else
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
if [ "$STACK_FAMILY" = "nginx" ]; then
    _pass "No Docker secrets required for nginx-only stack"
elif [ -n "$SECRETS_PREFIX" ]; then
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

# --- Check 5: Deployment profile reference ---
echo ""
echo "  [Deployment Profile]"
if [ -n "$DEPLOYMENT_PROFILE_ID" ]; then
    profile_file="${PROJECT_ROOT}/site-configs/${DEPLOYMENT_PROFILE_ID}.json"
    if [ -f "$profile_file" ]; then
        _pass "Deployment profile found: ${DEPLOYMENT_PROFILE_ID}"
    else
        _warn "Deployment profile not found: ${profile_file}"
    fi
elif [ -n "$BACKEND_APP_ID" ]; then
    app_config_found=false
    for cfg in "${PROJECT_ROOT}/site-configs/"*.json; do
        [ -f "$cfg" ] || continue
        cfg_id=$(basename "$cfg" .json)
        [ "$cfg_id" = "_template" ] && continue
        if command -v jq &>/dev/null; then
            app_id=$(jq -r '.appId // empty' "$cfg" 2>/dev/null)
            if [ "$app_id" = "$BACKEND_APP_ID" ]; then
                app_config_found=true
                _pass "Deployment profile found for BACKEND_APP_ID='${BACKEND_APP_ID}': $(basename "$cfg")"
                break
            fi
        fi
    done
    if [ "$app_config_found" = false ]; then
        if command -v jq &>/dev/null; then
            _warn "No deployment profile found matching BACKEND_APP_ID='${BACKEND_APP_ID}'"
        else
            _warn "jq not installed; cannot verify deployment profile reference"
        fi
    fi
else
    _warn "Neither DEPLOYMENT_PROFILE_ID nor BACKEND_APP_ID is set in .env"
fi

# ===========================================================================
# Summary
# ===========================================================================

echo ""
echo "========================================"
echo "  Validation Summary"
echo "========================================"
echo ""
echo "  [OK] Passed:   ${PASS_COUNT}"
echo "  [WARN] Warnings: ${WARN_COUNT}"
echo "  [ERROR] Failed:   ${FAIL_COUNT}"
echo ""

if [ "$FAIL_COUNT" -gt 0 ]; then
    echo "[ERROR] Validation failed with ${FAIL_COUNT} error(s)."
    exit 1
else
    echo "[OK] All checks passed."
    exit 0
fi
