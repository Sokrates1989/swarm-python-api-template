#!/bin/bash
# ==============================================================================
# felix-setup-wizard.sh - Guided Felix full-stack deployment configuration
# ==============================================================================
#
# Collects only public deployment-instance settings, writes the ignored root
# .env through the strict Python validator, and renders the deterministic stack.
# Passwords and client secrets remain owned by Docker secret workflows.
# ==============================================================================

# _felix_python_command
# Selects an available Python 3 command for strict profile operations.
#
# Arguments:
#   None.
#
# Outputs:
#   The selected executable name.
#
# Returns:
#   0 when Python is available; 1 otherwise.
_felix_python_command() {
    if command -v python3 >/dev/null 2>&1; then
        printf '%s\n' "python3"
        return 0
    fi
    if command -v python >/dev/null 2>&1; then
        printf '%s\n' "python"
        return 0
    fi
    return 1
}

# _felix_existing_value
# Reads one exact public value from the generated root .env without sourcing it.
#
# Arguments:
#   $1 - Exact public field name.
#   $2 - Fallback used when the field or file is absent.
#
# Outputs:
#   Existing value or fallback.
#
# Returns:
#   0 always.
_felix_existing_value() {
    local key="$1"
    local fallback="$2"
    local line=""

    if [ -f "${PROJECT_ROOT}/.env" ]; then
        line="$(grep -m 1 "^${key}=" "${PROJECT_ROOT}/.env" 2>/dev/null || true)"
    fi
    if [ -n "$line" ]; then
        printf '%s\n' "${line#*=}"
        return 0
    fi
    printf '%s\n' "$fallback"
}

# _felix_prompt_value
# Prompts for one public value while making Enter preserve the shown default.
#
# Arguments:
#   $1 - User-facing label.
#   $2 - Default value.
#
# Outputs:
#   Selected value.
#
# Returns:
#   0 always.
_felix_prompt_value() {
    local label="$1"
    local default_value="$2"
    local selected=""

    read -r -p "${label} [${default_value}]: " selected
    printf '%s\n' "${selected:-$default_value}"
}

# _felix_prompt_choice
# Prompts until the operator selects one member of a small allowlist.
#
# Arguments:
#   $1 - User-facing label.
#   $2 - Default value.
#   Remaining arguments - Accepted literal values.
#
# Outputs:
#   Selected allowlisted value.
#
# Returns:
#   0 after a valid selection.
_felix_prompt_choice() {
    local label="$1"
    local default_value="$2"
    shift 2
    local selected=""
    local allowed=""

    while true; do
        selected="$(_felix_prompt_value "$label" "$default_value")"
        for allowed in "$@"; do
            if [ "$selected" = "$allowed" ]; then
                printf '%s\n' "$selected"
                return 0
            fi
        done
        echo "[WARN] Choose one of: $*" >&2
    done
}

# _felix_prompt_boolean
# Prompts for an enable/disable decision using familiar yes/no input.
#
# Arguments:
#   $1 - User-facing question.
#   $2 - Default literal (`true` or `false`).
#
# Outputs:
#   `true` or `false`.
#
# Returns:
#   0 after valid input.
_felix_prompt_boolean() {
    local question="$1"
    local default_value="$2"
    local hint="y/N"
    local selected=""

    if [ "$default_value" = "true" ]; then
        hint="Y/n"
    fi
    while true; do
        read -r -p "${question} (${hint}): " selected
        if [ -z "$selected" ]; then
            printf '%s\n' "$default_value"
            return 0
        fi
        case "$selected" in
            [Yy]) printf '%s\n' "true"; return 0 ;;
            [Nn]) printf '%s\n' "false"; return 0 ;;
            *) echo "[WARN] Enter y, n, or press Enter." >&2 ;;
        esac
    done
}

# _felix_show_fixed_identity
# Displays candidate identities that are intentionally not editable here.
#
# Arguments:
#   None.
#
# Returns:
#   0 after printing the public identity boundary.
_felix_show_fixed_identity() {
    echo ""
    echo "Felix Backend and WebApp identity"
    echo "--------------------------------"
    echo "  Stack:             felix-new"
    echo "  Web URL:           https://felix-app.fe-wi.com"
    echo "  API URL:           https://api.felix-app.fe-wi.com"
    echo "  Keycloak realm:    felix-new"
    echo "  Frontend client:   felix-new-frontend"
    echo "  Backend client:    felix-new-backend"
    echo ""
    echo "These candidate values stay isolated from felix.app.fe-wi.com and realm felix."
}

# _felix_collect_database
# Collects public PostgreSQL placement and connection metadata.
#
# Arguments:
#   None.
#
# Returns:
#   0 after setting DB_MODE, DB_HOST, DB_PORT, DB_NAME, and DB_USER.
#
# Side effects:
#   Updates guided-wizard globals.
_felix_collect_database() {
    local default_mode

    echo ""
    echo "Step 1: PostgreSQL"
    echo "  local    - deploy PostgreSQL in the felix-new stack"
    echo "  external - use an existing PostgreSQL server"
    default_mode="$(_felix_existing_value DB_MODE local)"
    DB_MODE="$(_felix_prompt_choice "Database mode" "$default_mode" local external)"
    if [ "$DB_MODE" = "local" ]; then
        DB_HOST="postgres"
        DB_PORT="5432"
    else
        DB_HOST="$(_felix_prompt_value \
            "External PostgreSQL host" \
            "$(_felix_existing_value DB_HOST database.fe-wi.com)")"
        DB_PORT="$(_felix_prompt_value \
            "External PostgreSQL port" \
            "$(_felix_existing_value DB_PORT 5432)")"
    fi
    DB_NAME="$(_felix_prompt_value \
        "PostgreSQL database" \
        "$(_felix_existing_value DB_NAME felix)")"
    DB_USER="$(_felix_prompt_value \
        "PostgreSQL user" \
        "$(_felix_existing_value DB_USER felix)")"
}

# _felix_collect_routing
# Collects reverse-proxy, TLS-termination, network, and direct-port settings.
#
# Arguments:
#   None.
#
# Returns:
#   0 after setting PROXY_TYPE, SSL_MODE, TRAEFIK_NETWORK, and
#   API_PUBLISHED_PORT.
#
# Side effects:
#   Updates guided-wizard globals.
_felix_collect_routing() {
    local default_proxy
    local default_ssl

    echo ""
    echo "Step 2: Public routing and TLS"
    echo "  traefik - route the fixed API/Web domains through the Swarm proxy"
    echo "  none    - publish the API port for an external SSL terminator"
    default_proxy="$(_felix_existing_value PROXY_TYPE traefik)"
    PROXY_TYPE="$(_felix_prompt_choice \
        "Proxy type" "$default_proxy" traefik none)"
    API_PUBLISHED_PORT="$(_felix_existing_value API_PUBLISHED_PORT 8083)"
    if [ "$PROXY_TYPE" = "traefik" ]; then
        echo "  letsencrypt - Traefik obtains and terminates certificates"
        echo "  proxy       - an upstream proxy terminates public TLS"
        default_ssl="$(_felix_existing_value SSL_MODE proxy)"
        SSL_MODE="$(_felix_prompt_choice \
            "TLS mode" "$default_ssl" letsencrypt proxy)"
        TRAEFIK_NETWORK="$(_felix_prompt_value \
            "Traefik overlay network" \
            "$(_felix_existing_value TRAEFIK_NETWORK traefik-public)")"
    else
        SSL_MODE="proxy"
        TRAEFIK_NETWORK="none"
        API_PUBLISHED_PORT="$(_felix_prompt_value \
            "Published API port" "$API_PUBLISHED_PORT")"
    fi
}

# _felix_collect_api_resources
# Collects immutable API image and bounded Swarm resource settings.
#
# Arguments:
#   None.
#
# Returns:
#   0 after setting IMAGE_VERSION, API_REPLICAS, MEMORY_LIMIT, and DATA_ROOT.
#
# Side effects:
#   Updates guided-wizard globals.
_felix_collect_api_resources() {
    echo ""
    echo "Step 3: Felix Backend image and resources"
    echo "  Image repository: sokrates1989/python-api-felix"
    IMAGE_VERSION="$(_felix_prompt_value \
        "Backend image version" \
        "$(_felix_existing_value IMAGE_VERSION 0.1.1)")"
    API_REPLICAS="$(_felix_prompt_value \
        "Backend replicas" \
        "$(_felix_existing_value API_REPLICAS 1)")"
    MEMORY_LIMIT="$(_felix_prompt_value \
        "Backend memory limit" \
        "$(_felix_existing_value MEMORY_LIMIT 512M)")"
    DATA_ROOT="$(_felix_prompt_value \
        "Host data root" \
        "$(_felix_existing_value DATA_ROOT /swarm/volumes/felix-new)")"
}

# _felix_collect_pgadmin
# Collects optional local PostgreSQL administration metadata.
#
# Arguments:
#   None.
#
# Returns:
#   0 after setting PGADMIN_ENABLED, PGADMIN_DOMAIN, PGADMIN_EMAIL, and
#   PGADMIN_REPLICAS.
#
# Side effects:
#   Updates guided-wizard globals.
_felix_collect_pgadmin() {
    local default_enabled

    PGADMIN_ENABLED="false"
    PGADMIN_DOMAIN="disabled"
    PGADMIN_EMAIL="disabled"
    PGADMIN_REPLICAS="0"
    if [ "$DB_MODE" != "local" ]; then
        return 0
    fi

    echo ""
    echo "Step 4: Optional PostgreSQL management"
    default_enabled="$(_felix_existing_value PGADMIN_ENABLED false)"
    PGADMIN_ENABLED="$(_felix_prompt_boolean \
        "Include pgAdmin in this stack?" "$default_enabled")"
    if [ "$PGADMIN_ENABLED" = "true" ]; then
        PGADMIN_DOMAIN="$(_felix_prompt_value \
            "pgAdmin domain" \
            "$(_felix_existing_value PGADMIN_DOMAIN pgadmin.felix-app.fe-wi.com)")"
        PGADMIN_EMAIL="$(_felix_prompt_value \
            "pgAdmin login email" \
            "$(_felix_existing_value PGADMIN_EMAIL admin@fe-wi.com)")"
        PGADMIN_REPLICAS="1"
    fi
}

# _felix_collect_web
# Records deliberate WebApp deferral until its immutable image flow is ready.
#
# Arguments:
#   None.
#
# Returns:
#   0 after setting the four WebApp fields to their explicit disabled state.
#
# Side effects:
#   Updates guided-wizard globals.
_felix_collect_web() {
    echo ""
    echo "Step 5: Felix WebApp"
    echo "  Deferred until the production WebApp image has been built and published."
    echo "  The same wizard will expose its image fields in the WebApp slice."
    WEB_ENABLED="false"
    WEB_IMAGE_NAME="disabled"
    WEB_IMAGE_VERSION="disabled"
    WEB_REPLICAS="0"
}

# _felix_append_fixed_env_arguments
# Adds the non-editable Felix candidate identities to a CLI argument array.
#
# Arguments:
#   $1 - Name of the caller-owned Bash array to extend.
#
# Returns:
#   0 after every fixed public assignment is appended.
#
# Side effects:
#   Mutates only the named argument array.
_felix_append_fixed_env_arguments() {
    local -n target_arguments="$1"

    target_arguments+=(--set "PROFILE_SCHEMA_VERSION=1")
    target_arguments+=(--set "DEPLOYMENT_PROFILE_ID=felix")
    target_arguments+=(--set "APP_ID=felix")
    target_arguments+=(--set "APP_ENVIRONMENT=production")
    target_arguments+=(--set "APP_PROFILE=felix")
    target_arguments+=(--set "BACKEND_APP_ID=felix")
    target_arguments+=(--set "BACKEND_DATA_PROFILE=postgresql")
    target_arguments+=(--set "AUTH_PROVIDER=keycloak")
    target_arguments+=(--set "API_BASE_URL=https://api.felix-app.fe-wi.com")
    target_arguments+=(--set "DOMAIN=api.felix-app.fe-wi.com")
    target_arguments+=(--set "WEB_BASE_URL=https://felix-app.fe-wi.com")
    target_arguments+=(--set "WEB_DOMAIN=felix-app.fe-wi.com")
    target_arguments+=(--set "CORS_ORIGINS=https://felix-app.fe-wi.com")
    target_arguments+=(--set "KEYCLOAK_BASE_URL=https://keycloak.fe-wi.com")
    target_arguments+=(--set "KEYCLOAK_ISSUER_URL=https://keycloak.fe-wi.com/realms/felix-new")
    target_arguments+=(--set "KEYCLOAK_REALM=felix-new")
    target_arguments+=(--set "KEYCLOAK_AUDIENCE=felix-new-backend")
    target_arguments+=(--set "KEYCLOAK_FRONTEND_CLIENT_ID=felix-new-frontend")
    target_arguments+=(--set "STACK_NAME=felix-new")
    target_arguments+=(--set "STACK_FAMILY=api")
    target_arguments+=(--set "STACK_ROLE=full-stack")
    target_arguments+=(--set "PRIMARY_SERVICE=api")
    target_arguments+=(--set "DB_TYPE=postgresql")
    target_arguments+=(--set "IMAGE_NAME=sokrates1989/python-api-felix")
}

# _felix_append_guided_env_arguments
# Adds operator-selected public deployment settings to a CLI argument array.
#
# Arguments:
#   $1 - Name of the caller-owned Bash array to extend.
#
# Returns:
#   0 after every guided public assignment is appended.
#
# Side effects:
#   Mutates only the named argument array.
_felix_append_guided_env_arguments() {
    local -n target_arguments="$1"

    target_arguments+=(--set "DB_MODE=${DB_MODE}")
    target_arguments+=(--set "DB_HOST=${DB_HOST}")
    target_arguments+=(--set "DB_PORT=${DB_PORT}")
    target_arguments+=(--set "DB_NAME=${DB_NAME}")
    target_arguments+=(--set "DB_USER=${DB_USER}")
    target_arguments+=(--set "PROXY_TYPE=${PROXY_TYPE}")
    target_arguments+=(--set "SSL_MODE=${SSL_MODE}")
    target_arguments+=(--set "TRAEFIK_NETWORK=${TRAEFIK_NETWORK}")
    target_arguments+=(--set "API_PUBLISHED_PORT=${API_PUBLISHED_PORT}")
    target_arguments+=(--set "IMAGE_VERSION=${IMAGE_VERSION}")
    target_arguments+=(--set "API_REPLICAS=${API_REPLICAS}")
    target_arguments+=(--set "MEMORY_LIMIT=${MEMORY_LIMIT}")
    target_arguments+=(--set "DATA_ROOT=${DATA_ROOT}")
    target_arguments+=(--set "PGADMIN_ENABLED=${PGADMIN_ENABLED}")
    target_arguments+=(--set "PGADMIN_DOMAIN=${PGADMIN_DOMAIN}")
    target_arguments+=(--set "PGADMIN_EMAIL=${PGADMIN_EMAIL}")
    target_arguments+=(--set "PGADMIN_REPLICAS=${PGADMIN_REPLICAS}")
    target_arguments+=(--set "WEB_ENABLED=${WEB_ENABLED}")
    target_arguments+=(--set "WEB_IMAGE_NAME=${WEB_IMAGE_NAME}")
    target_arguments+=(--set "WEB_IMAGE_VERSION=${WEB_IMAGE_VERSION}")
    target_arguments+=(--set "WEB_REPLICAS=${WEB_REPLICAS}")
}

# _felix_write_guided_env
# Sends the complete public schema to the atomic Python writer.
#
# Arguments:
#   $1 - Python executable selected by `_felix_python_command`.
#
# Returns:
#   The strict writer exit status.
#
# Side effects:
#   Creates or replaces only the ignored root .env.
_felix_write_guided_env() {
    local python_command="$1"
    local arguments=()

    _felix_append_fixed_env_arguments arguments
    _felix_append_guided_env_arguments arguments
    "$python_command" "${PROJECT_ROOT}/scripts/release_profile.py" \
        --root "$PROJECT_ROOT" --force "${arguments[@]}"
}

# _felix_render_stack
# Validates root .env and renders the exact root Swarm stack.
#
# Arguments:
#   $1 - Python executable selected by `_felix_python_command`.
#
# Returns:
#   The strict renderer exit status.
#
# Side effects:
#   Atomically creates or replaces root swarm-stack.yml.
_felix_render_stack() {
    local python_command="$1"

    "$python_command" "${PROJECT_ROOT}/scripts/release_profile.py" \
        --root "$PROJECT_ROOT" || return 1
    "$python_command" "${PROJECT_ROOT}/scripts/felix_site_profile.py" \
        --root "$PROJECT_ROOT" render --compose-check
}

# _felix_setup_final_actions
# Offers non-deploying preparation actions after configuration succeeds.
#
# Arguments:
#   None.
#
# Returns:
#   0 after the selected action finishes or returns.
#
# Side effects:
#   May create data directories or open profile-aware Docker secret menus.
_felix_setup_final_actions() {
    local choice=""

    echo ""
    echo "Configuration complete"
    echo "----------------------"
    echo "  1) Done (save and render only)"
    echo "  2) Create data directories"
    echo "  3) Manage Felix Docker secrets"
    echo "  4) Show production Keycloak owner"
    echo ""
    read -r -p "Next action (1-4) [1]: " choice
    case "${choice:-1}" in
        1) echo "Configuration saved; no runtime state was changed." ;;
        2) create_data_directories "$DATA_ROOT" "postgresql" ;;
        3) manage_docker_secrets_menu ;;
        4) show_felix_production_keycloak_handoff ;;
        *) echo "[WARN] Unknown action; configuration remains saved." ;;
    esac
}

# run_guided_felix_setup
# Runs the complete public Felix configuration flow or validates an existing
# .env selected by the setup wizard's fast re-setup mode.
#
# Arguments:
#   None. Reads PROJECT_ROOT and SETUP_MODE.
#
# Returns:
#   0 after valid .env and stack rendering; 1 on validation/render failure.
#
# Side effects:
#   May replace ignored root .env, render swarm-stack.yml, create data
#   directories, or invoke an explicitly selected secret-management action.
run_guided_felix_setup() {
    local python_command=""

    python_command="$(_felix_python_command)" || {
        echo "[ERROR] Python 3.10 or newer is required."
        return 1
    }
    _felix_show_fixed_identity
    if [ "${SETUP_MODE:-interactive}" != "from_env" ]; then
        _felix_collect_database
        _felix_collect_routing
        _felix_collect_api_resources
        _felix_collect_pgadmin
        _felix_collect_web
        echo ""
        echo "Validating and writing public deployment configuration..."
        _felix_write_guided_env "$python_command" || return 1
    else
        echo ""
        echo "Validating existing root .env without changing it..."
    fi
    _felix_render_stack "$python_command" || return 1
    load_root_env "$PROJECT_ROOT" || return 1
    echo ""
    echo "[OK] Felix Backend and WebApp stack configuration is ready."
    _felix_setup_final_actions
}
