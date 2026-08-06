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
# _append_keycloak_configuration_arguments
# ------------------------------------------------------------------------------
# Adds every editable public Keycloak field to the Python writer arguments.
#
# Arguments:
#   $1 - Bash array variable name owned by the caller.
#
# Returns:
#   0 after extending the array.
# ------------------------------------------------------------------------------
_append_keycloak_configuration_arguments() {
    local -n target="$1"
    local key=""
    local fields=(
        KEYCLOAK_BASE_URL KEYCLOAK_ISSUER_URL KEYCLOAK_REALM
        KEYCLOAK_REALM_DISPLAY_NAME KEYCLOAK_REALM_ENABLED
        KEYCLOAK_REGISTRATION_ALLOWED KEYCLOAK_RESET_PASSWORD_ALLOWED
        KEYCLOAK_REMEMBER_ME KEYCLOAK_VERIFY_EMAIL
        KEYCLOAK_LOGIN_WITH_EMAIL_ALLOWED KEYCLOAK_LOGIN_THEME
        KEYCLOAK_ACCOUNT_THEME KEYCLOAK_ADMIN_THEME KEYCLOAK_EMAIL_THEME
        KEYCLOAK_INTERNATIONALIZATION_ENABLED KEYCLOAK_SUPPORTED_LOCALES
        KEYCLOAK_DEFAULT_LOCALE KEYCLOAK_EMAIL_SENDER_ENABLED
        KEYCLOAK_SMTP_FROM KEYCLOAK_SMTP_FROM_DISPLAY_NAME
        KEYCLOAK_SMTP_REPLY_TO KEYCLOAK_SMTP_REPLY_TO_DISPLAY_NAME
        KEYCLOAK_SMTP_ENVELOPE_FROM KEYCLOAK_SMTP_HOST KEYCLOAK_SMTP_PORT
        KEYCLOAK_SMTP_STARTTLS KEYCLOAK_SMTP_SSL KEYCLOAK_SMTP_AUTH
        KEYCLOAK_SMTP_USERNAME KEYCLOAK_BOOTSTRAP_TEST_USERS_ENABLED
        KEYCLOAK_BOOTSTRAP_USERS_CLEANUP_PENDING
        KEYCLOAK_BOOTSTRAP_USERS_CLEANUP_NAMES
        KEYCLOAK_AUDIENCE KEYCLOAK_FRONTEND_CLIENT_ID
        KEYCLOAK_BACKEND_CLIENT_ID
    )

    for key in "${fields[@]}"; do
        target+=(--set "${key}=${!key:-}")
    done
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
    _append_keycloak_configuration_arguments "$1"
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
    arguments+=(--set "ADVANCED_LOGGING_ENABLED=${ADVANCED_LOGGING_ENABLED}")
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
