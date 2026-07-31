#!/bin/bash
# ==============================================================================
# executable-profile-wizard.sh - Executable profile persistence/render adapter
# ==============================================================================
#
# Persists and renders schema-5 executable profiles after the shared deployment
# dialogue has normalized operator answers. This adapter deliberately contains
# no terminal prompts or final-action menu; renderer type must never select a
# different operator experience.
#
# Dependencies:
#   - scripts/site_profile.py
#   - setup/modules/deployment-profile-inputs.sh
# ==============================================================================

# Guard against multiple sourcing.
if [ -n "${_EXECUTABLE_PROFILE_ADAPTER_LOADED:-}" ]; then
    return 0 2>/dev/null || true
fi
_EXECUTABLE_PROFILE_ADAPTER_LOADED=1

# ------------------------------------------------------------------------------
# _executable_profile_python
# ------------------------------------------------------------------------------
# Resolves an available Python 3 runtime.
#
# Output:
#   Python command name.
#
# Returns:
#   0 when Python 3 is available; otherwise 1.
# ------------------------------------------------------------------------------
_executable_profile_python() {
    if command -v python3 >/dev/null 2>&1; then
        echo "python3"
        return 0
    fi
    if command -v python >/dev/null 2>&1; then
        echo "python"
        return 0
    fi
    return 1
}

# ------------------------------------------------------------------------------
# _profile_configuration_arguments
# ------------------------------------------------------------------------------
# Converts normalized shared-wizard globals into explicit Python CLI overrides.
#
# Arguments:
#   $1 - Bash array variable name owned by the caller.
#
# Returns:
#   0 after extending the array.
# ------------------------------------------------------------------------------
_profile_configuration_arguments() {
    local -n arguments="$1"

    arguments+=(--set "STACK_NAME=${STACK_NAME}")
    arguments+=(--set "API_BASE_URL=${API_BASE_URL}")
    arguments+=(--set "DOMAIN=${DOMAIN}")
    arguments+=(--set "WEB_BASE_URL=${WEB_BASE_URL}")
    arguments+=(--set "WEB_DOMAIN=${WEB_DOMAIN}")
    arguments+=(--set "CORS_ORIGINS=${CORS_ORIGINS}")
    arguments+=(--set "KEYCLOAK_BASE_URL=${KEYCLOAK_BASE_URL}")
    arguments+=(--set "KEYCLOAK_ISSUER_URL=${KEYCLOAK_ISSUER_URL}")
    arguments+=(--set "KEYCLOAK_REALM=${KEYCLOAK_REALM}")
    arguments+=(--set "KEYCLOAK_REALM_DISPLAY_NAME=${KEYCLOAK_REALM_DISPLAY_NAME}")
    arguments+=(--set "KEYCLOAK_AUDIENCE=${KEYCLOAK_AUDIENCE}")
    arguments+=(--set "KEYCLOAK_FRONTEND_CLIENT_ID=${KEYCLOAK_FRONTEND_CLIENT_ID}")
    arguments+=(--set "KEYCLOAK_BACKEND_CLIENT_ID=${KEYCLOAK_BACKEND_CLIENT_ID}")
    arguments+=(--set "DB_MODE=${DB_MODE}")
    arguments+=(--set "DB_HOST=${DB_HOST}")
    arguments+=(--set "DB_PORT=${DB_PORT}")
    arguments+=(--set "DB_NAME=${DB_NAME}")
    arguments+=(--set "DB_USER=${DB_USER}")
    arguments+=(--set "PROXY_TYPE=${PROXY_TYPE}")
    arguments+=(--set "SSL_MODE=${SSL_MODE}")
    arguments+=(--set "TRAEFIK_NETWORK=${TRAEFIK_NETWORK}")
    arguments+=(--set "TRAEFIK_CONSTRAINT_LABEL=${TRAEFIK_CONSTRAINT_LABEL}")
    arguments+=(--set "TRAEFIK_CERT_RESOLVER=${TRAEFIK_CERT_RESOLVER}")
    arguments+=(--set "API_PUBLISHED_PORT=${API_PUBLISHED_PORT}")
    arguments+=(--set "WEB_PUBLISHED_PORT=${WEB_PUBLISHED_PORT}")
    arguments+=(--set "PGADMIN_PUBLISHED_PORT=${PGADMIN_PUBLISHED_PORT}")
    arguments+=(--set "IMAGE_NAME=${IMAGE_NAME}")
    arguments+=(--set "IMAGE_VERSION=${IMAGE_VERSION}")
    arguments+=(--set "API_REPLICAS=${API_REPLICAS}")
    arguments+=(--set "MEMORY_LIMIT=${MEMORY_LIMIT}")
    arguments+=(--set "DATA_ROOT=${DATA_ROOT}")
    arguments+=(--set "PGADMIN_ENABLED=${PGADMIN_ENABLED}")
    arguments+=(--set "PGADMIN_DOMAIN=${PGADMIN_DOMAIN}")
    arguments+=(--set "PGADMIN_EMAIL=${PGADMIN_EMAIL}")
    arguments+=(--set "PGADMIN_REPLICAS=${PGADMIN_REPLICAS}")
    arguments+=(--set "WEB_ENABLED=${WEB_ENABLED}")
    arguments+=(--set "WEB_IMAGE_NAME=${WEB_IMAGE_NAME}")
    arguments+=(--set "WEB_IMAGE_VERSION=${WEB_IMAGE_VERSION}")
    arguments+=(--set "WEB_REPLICAS=${WEB_REPLICAS}")
    arguments+=(--set "WEB_MEMORY_LIMIT=${WEB_MEMORY_LIMIT}")
}

# ------------------------------------------------------------------------------
# write_executable_profile_environment
# ------------------------------------------------------------------------------
# Validates and writes the executable root environment from shared answers.
#
# Returns:
#   Python adapter status.
#
# Side effects:
#   Replaces the ignored root .env file.
# ------------------------------------------------------------------------------
write_executable_profile_environment() {
    local python_command=""
    local configuration_arguments=()

    python_command="$(_executable_profile_python)" || {
        echo "[ERROR] Python 3 is required for executable site profiles."
        return 1
    }
    _profile_configuration_arguments configuration_arguments
    "$python_command" "${PROJECT_ROOT}/scripts/site_profile.py" \
        --root "$PROJECT_ROOT" \
        configure \
        --profile "$APP_CONFIG_ID" \
        --force \
        "${configuration_arguments[@]}"
}

# ------------------------------------------------------------------------------
# render_executable_profile_stack
# ------------------------------------------------------------------------------
# Validates the generated environment and renders a Compose-checked stack.
#
# Returns:
#   Python adapter status.
#
# Side effects:
#   Replaces root swarm-stack.yml after successful validation.
# ------------------------------------------------------------------------------
render_executable_profile_stack() {
    local python_command=""

    python_command="$(_executable_profile_python)" || {
        echo "[ERROR] Python 3 is required for executable site profiles."
        return 1
    }
    "$python_command" "${PROJECT_ROOT}/scripts/site_profile.py" \
        --root "$PROJECT_ROOT" \
        render \
        --compose-check
}
