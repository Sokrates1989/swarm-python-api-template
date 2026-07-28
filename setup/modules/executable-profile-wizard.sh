#!/bin/bash
# ==============================================================================
# executable-profile-wizard.sh - Shared executable site-profile setup
# ==============================================================================
#
# Collects only operator-owned deployment values. Application identity,
# services, images, routes, authentication, secret mounts, and defaults are
# read from the selected site-config. The same flow supports every schema-5
# executable profile without app-name branches.
# ==============================================================================

# _executable_profile_python
# Resolves an available Python 3 runtime.
#
# Returns:
#   Prints the command and returns 0, or returns 1 when unavailable.
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

# _profile_config_value
# Reads one selected-profile JSON value with a fallback.
#
# Arguments:
#   $1 - jq expression.
#   $2 - fallback value.
#
# Returns:
#   Prints the selected value.
_profile_config_value() {
    _jq_or_default "$APP_CONFIG_FILE" "$1" "$2"
}

# _profile_existing_value
# Reads one current root environment value with a fallback.
#
# Arguments:
#   $1 - environment key.
#   $2 - fallback value.
#
# Returns:
#   Prints the current or fallback value.
_profile_existing_value() {
    local key="$1"
    local fallback="$2"
    local value=""

    if [ -f "${PROJECT_ROOT}/.env" ]; then
        value="$(_root_env_value "${PROJECT_ROOT}/.env" "$key")"
    fi
    printf '%s' "${value:-$fallback}"
}

# _profile_prompt_value
# Prompts for one non-empty public deployment value.
#
# Arguments:
#   $1 - prompt label.
#   $2 - default value.
#
# Returns:
#   Prints the selected value.
_profile_prompt_value() {
    local label="$1"
    local default_value="$2"
    local selected=""

    while true; do
        read -r -p "${label} [${default_value}]: " selected
        selected="${selected:-$default_value}"
        if [ -n "$selected" ]; then
            printf '%s' "$selected"
            return 0
        fi
        echo "${label} is required." >&2
    done
}

# _profile_prompt_choice
# Prompts until one allowlisted public value is selected.
#
# Arguments:
#   $1 - prompt label.
#   $2 - default value.
#   Remaining arguments - allowed values.
#
# Returns:
#   Prints the selected value.
_profile_prompt_choice() {
    local label="$1"
    local default_value="$2"
    shift 2
    local selected=""
    local candidate=""

    while true; do
        selected="$(_profile_prompt_value "$label" "$default_value")"
        for candidate in "$@"; do
            if [ "$selected" = "$candidate" ]; then
                printf '%s' "$selected"
                return 0
            fi
        done
        echo "Choose one of: $*." >&2
    done
}

# _profile_prompt_boolean
# Prompts for one true/false deployment switch.
#
# Arguments:
#   $1 - prompt label.
#   $2 - default boolean.
#
# Returns:
#   Prints true or false.
_profile_prompt_boolean() {
    local label="$1"
    local default_value="$2"
    local hint="y/N"
    local answer=""

    if [ "$default_value" = "true" ]; then
        hint="Y/n"
    fi
    read -r -p "${label} (${hint}): " answer
    if [ -z "$answer" ]; then
        printf '%s' "$default_value"
    elif [[ "$answer" =~ ^[Yy]$ ]]; then
        printf '%s' "true"
    else
        printf '%s' "false"
    fi
}

# _profile_show_identity
# Displays immutable identity and service declarations from the site config.
#
# Returns:
#   0 after printing the profile.
_profile_show_identity() {
    local stack_name
    local api_url
    local web_url
    local auth_provider
    local realm

    stack_name="$(_profile_config_value '.stack.name' "$APP_ID")"
    api_url="$(_profile_config_value '.routing.apiBaseUrl' "")"
    web_url="$(_profile_config_value '.routing.webBaseUrl' "")"
    auth_provider="$(_profile_config_value '.auth.provider' "none")"
    realm="$(_profile_config_value '.auth.realm' "")"

    echo ""
    echo "${APP_NAME} deployment identity"
    echo "--------------------------------"
    echo "  Profile:           ${APP_CONFIG_ID}"
    echo "  Stack:             ${stack_name}"
    echo "  API URL:           ${api_url}"
    if [ "${APP_REQUIRES_WEB:-false}" = "true" ]; then
        echo "  Web URL:           ${web_url}"
    fi
    echo "  Auth provider:     ${auth_provider}"
    if [ "$auth_provider" = "keycloak" ]; then
        echo "  Keycloak realm:    ${realm}"
        echo "  Frontend client:   $(_profile_config_value '.auth.frontendClientId' "")"
        echo "  Backend client:    $(_profile_config_value '.auth.adminClientId' "")"
    fi
    echo ""
    echo "Identity and service differences come only from ${APP_CONFIG_FILE}."
}

# _profile_collect_database
# Collects database mode and public connection identity.
#
# Returns:
#   0 after updating DB_* globals.
_profile_collect_database() {
    local default_mode
    local allowed_modes=()

    while IFS= read -r mode; do
        [ -n "$mode" ] && allowed_modes+=("$mode")
    done < <(jq -r '.database.allowedModes[]' "$APP_CONFIG_FILE")
    default_mode="$(_profile_existing_value \
        DB_MODE \
        "$(_profile_config_value '.database.defaultMode' "local")")"
    echo ""
    echo "Step 1: Database"
    printf '  Allowed modes: %s\n' "${allowed_modes[*]}"
    DB_MODE="$(_profile_prompt_choice \
        "Database mode" "$default_mode" "${allowed_modes[@]}")"
    DB_HOST="$(_profile_config_value '.environment.DB_HOST' "postgres")"
    DB_PORT="$(_profile_config_value '.environment.DB_PORT' "5432")"
    if [ "$DB_MODE" = "external" ]; then
        DB_HOST="$(_profile_prompt_value \
            "External database host" \
            "$(_profile_existing_value DB_HOST "$DB_HOST")")"
        DB_PORT="$(_profile_prompt_value \
            "External database port" \
            "$(_profile_existing_value DB_PORT "$DB_PORT")")"
    fi
    DB_NAME="$(_profile_prompt_value \
        "Database name" \
        "$(_profile_existing_value \
            DB_NAME \
            "$(_profile_config_value '.environment.DB_NAME' "$APP_ID")")")"
    DB_USER="$(_profile_prompt_value \
        "Database user" \
        "$(_profile_existing_value \
            DB_USER \
            "$(_profile_config_value '.environment.DB_USER' "$APP_ID")")")"
}

# _profile_collect_routing
# Collects proxy, TLS, network, and direct-port values.
#
# Returns:
#   0 after updating routing globals.
_profile_collect_routing() {
    local default_proxy="none"
    local default_ssl=""

    if [ "$(_profile_config_value '.exposure.traefik' "false")" = "true" ]; then
        default_proxy="traefik"
    fi
    default_proxy="$(_profile_existing_value PROXY_TYPE "$default_proxy")"
    echo ""
    echo "Step 2: Proxy and TLS"
    PROXY_TYPE="$(_profile_prompt_choice \
        "Proxy type" "$default_proxy" traefik none)"
    API_PUBLISHED_PORT="$(_profile_existing_value \
        API_PUBLISHED_PORT \
        "$(_profile_config_value '.routing.publishedPort' "8083")")"
    WEB_PUBLISHED_PORT="$(_profile_existing_value \
        WEB_PUBLISHED_PORT \
        "$(_profile_config_value '.routing.webPublishedPort' "8084")")"
    PGADMIN_PUBLISHED_PORT="$(_profile_existing_value \
        PGADMIN_PUBLISHED_PORT \
        "$(_profile_config_value '.routing.pgadminPublishedPort' "5054")")"
    TRAEFIK_CERT_RESOLVER="$(_profile_existing_value \
        TRAEFIK_CERT_RESOLVER \
        "$(_profile_config_value '.routing.traefikCertResolver' "le")")"
    if [ "$PROXY_TYPE" = "traefik" ]; then
        default_ssl="$(_profile_existing_value \
            SSL_MODE \
            "$(_profile_config_value '.routing.sslMode' "letsencrypt")")"
        SSL_MODE="$(_profile_prompt_choice \
            "TLS mode" "$default_ssl" letsencrypt proxy)"
        TRAEFIK_NETWORK="$(_profile_prompt_value \
            "Traefik overlay network" \
            "$(_profile_existing_value \
                TRAEFIK_NETWORK \
                "$(_profile_config_value '.routing.traefikNetwork' "traefik-public")")")"
        if [ "$SSL_MODE" = "letsencrypt" ]; then
            TRAEFIK_CERT_RESOLVER="$(_profile_prompt_value \
                "Traefik certificate resolver" \
                "$TRAEFIK_CERT_RESOLVER")"
        fi
    else
        SSL_MODE=""
        TRAEFIK_NETWORK=""
        API_PUBLISHED_PORT="$(_profile_prompt_value \
            "Published API port" "$API_PUBLISHED_PORT")"
        if [ "${APP_REQUIRES_WEB:-false}" = "true" ]; then
            WEB_PUBLISHED_PORT="$(_profile_prompt_value \
                "Published WebApp port" "$WEB_PUBLISHED_PORT")"
        fi
    fi
}

# _profile_collect_services
# Collects release versions, replicas, memory, and storage for declared services.
#
# Returns:
#   0 after updating API/Web/service globals.
_profile_collect_services() {
    IMAGE_VERSION="$(_profile_prompt_value \
        "Backend image version" \
        "$(_profile_existing_value \
            IMAGE_VERSION \
            "$(_profile_config_value '.image.defaultVersion' "")")")"
    API_REPLICAS="$(_profile_prompt_value \
        "Backend replicas" \
        "$(_profile_existing_value \
            API_REPLICAS \
            "$(_profile_config_value '.resources.defaultReplicas' "1")")")"
    MEMORY_LIMIT="$(_profile_prompt_value \
        "Backend memory limit" \
        "$(_profile_existing_value \
            MEMORY_LIMIT \
            "$(_profile_config_value '.resources.defaultMemoryLimit' "512M")")")"
    DATA_ROOT="$(_profile_prompt_value \
        "Host data root" \
        "$(_profile_existing_value \
            DATA_ROOT \
            "$(_profile_config_value '.storage.dataRoot' "$PROJECT_ROOT")")")"

    WEB_ENABLED="${APP_REQUIRES_WEB:-false}"
    WEB_IMAGE_NAME="$(_profile_config_value '.web.image.name' "")"
    WEB_IMAGE_VERSION="$(_profile_config_value '.web.image.defaultVersion' "")"
    WEB_REPLICAS="$(_profile_config_value '.web.resources.defaultReplicas' "1")"
    WEB_MEMORY_LIMIT="$(_profile_config_value \
        '.web.resources.defaultMemoryLimit' \
        "$(_profile_config_value '.resources.defaultWebMemoryLimit' "128M")")"
    if [ "$WEB_ENABLED" = "true" ]; then
        echo ""
        echo "Step 4: WebApp service"
        echo "  Image repository: ${WEB_IMAGE_NAME}"
        WEB_IMAGE_VERSION="$(_profile_prompt_value \
            "WebApp image version" \
            "$(_profile_existing_value WEB_IMAGE_VERSION "$WEB_IMAGE_VERSION")")"
        WEB_REPLICAS="$(_profile_prompt_value \
            "WebApp replicas" \
            "$(_profile_existing_value WEB_REPLICAS "$WEB_REPLICAS")")"
        WEB_MEMORY_LIMIT="$(_profile_prompt_value \
            "WebApp memory limit" \
            "$(_profile_existing_value WEB_MEMORY_LIMIT "$WEB_MEMORY_LIMIT")")"
    fi
}

# _profile_collect_pgadmin
# Collects optional pgAdmin values for local PostgreSQL.
#
# Returns:
#   0 after updating pgAdmin globals.
_profile_collect_pgadmin() {
    PGADMIN_ENABLED="false"
    PGADMIN_DOMAIN="$(_profile_config_value '.pgadmin.domain' "")"
    PGADMIN_EMAIL="$(_profile_config_value '.pgadmin.email' "")"
    PGADMIN_REPLICAS="0"
    if [ "$DB_MODE" != "local" ] || [ "${APP_DB_TYPE:-}" != "postgresql" ]; then
        return 0
    fi
    echo ""
    echo "Step 5: Optional PostgreSQL management"
    PGADMIN_ENABLED="$(_profile_prompt_boolean \
        "Include pgAdmin in this stack?" \
        "$(_profile_existing_value \
            PGADMIN_ENABLED \
            "$(_profile_config_value '.pgadmin.enabled' "false")")")"
    if [ "$PGADMIN_ENABLED" = "true" ]; then
        PGADMIN_DOMAIN="$(_profile_prompt_value \
            "pgAdmin domain" \
            "$(_profile_existing_value PGADMIN_DOMAIN "$PGADMIN_DOMAIN")")"
        PGADMIN_EMAIL="$(_profile_prompt_value \
            "pgAdmin login email" \
            "$(_profile_existing_value PGADMIN_EMAIL "$PGADMIN_EMAIL")")"
        if [ "$PROXY_TYPE" = "none" ]; then
            PGADMIN_PUBLISHED_PORT="$(_profile_prompt_value \
                "Published pgAdmin port" \
                "$PGADMIN_PUBLISHED_PORT")"
        fi
        PGADMIN_REPLICAS="1"
    fi
}

# _profile_configuration_arguments
# Appends operator-owned dynamic values to a caller-owned argument array.
#
# Arguments:
#   $1 - Bash array variable name.
#
# Returns:
#   0 after extending the array.
_profile_configuration_arguments() {
    local -n arguments="$1"

    arguments+=(--set "DB_MODE=${DB_MODE}")
    arguments+=(--set "DB_HOST=${DB_HOST}")
    arguments+=(--set "DB_PORT=${DB_PORT}")
    arguments+=(--set "DB_NAME=${DB_NAME}")
    arguments+=(--set "DB_USER=${DB_USER}")
    arguments+=(--set "PROXY_TYPE=${PROXY_TYPE}")
    arguments+=(--set "SSL_MODE=${SSL_MODE}")
    arguments+=(--set "TRAEFIK_NETWORK=${TRAEFIK_NETWORK}")
    arguments+=(--set "TRAEFIK_CERT_RESOLVER=${TRAEFIK_CERT_RESOLVER}")
    arguments+=(--set "API_PUBLISHED_PORT=${API_PUBLISHED_PORT}")
    arguments+=(--set "WEB_PUBLISHED_PORT=${WEB_PUBLISHED_PORT}")
    arguments+=(--set "PGADMIN_PUBLISHED_PORT=${PGADMIN_PUBLISHED_PORT}")
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

# _profile_write_environment
# Writes the shared generated root environment through the Python contract.
#
# Arguments:
#   $1 - Python command.
#
# Returns:
#   Exact writer status.
_profile_write_environment() {
    local python_command="$1"
    local arguments=()

    _profile_configuration_arguments arguments
    "$python_command" "${PROJECT_ROOT}/scripts/site_profile.py" \
        --root "$PROJECT_ROOT" \
        configure \
        --profile "$APP_CONFIG_ID" \
        --force \
        "${arguments[@]}"
}

# _profile_render_stack
# Validates the root environment and renders one Compose-checked stack.
#
# Arguments:
#   $1 - Python command.
#
# Returns:
#   Exact renderer status.
_profile_render_stack() {
    local python_command="$1"

    "$python_command" "${PROJECT_ROOT}/scripts/site_profile.py" \
        --root "$PROJECT_ROOT" \
        render \
        --compose-check
}

# _profile_setup_final_actions
# Offers shared non-automatic post-configuration actions.
#
# Returns:
#   0 after the operator returns.
_profile_setup_final_actions() {
    local choice=""
    local has_keycloak="false"

    if profile_uses_keycloak; then
        has_keycloak="true"
    fi
    echo ""
    echo "Configuration complete"
    echo "----------------------"
    echo "  1) Done (save and render only)"
    echo "  2) Create data directories"
    echo "  3) Manage profile Docker secrets"
    if [ "$has_keycloak" = "true" ]; then
        echo "  4) Bootstrap / update Keycloak realm"
    fi
    echo ""
    read -r -p "Next action [1]: " choice
    case "${choice:-1}" in
        1) echo "Configuration saved; no runtime state was changed." ;;
        2) create_data_directories "$DATA_ROOT" "$APP_DB_TYPE" ;;
        3) manage_docker_secrets_menu ;;
        4)
            if [ "$has_keycloak" = "true" ]; then
                run_profile_keycloak_bootstrap
            else
                echo "[WARN] This profile does not use Keycloak."
            fi
            ;;
        *) echo "[WARN] Unknown action; configuration remains saved." ;;
    esac
}

# _profile_validate_existing_selection
# Prevents a fast re-setup from rendering a different profile than the one
# selected in the wizard.
#
# Returns:
#   0 when interactive setup is active or the selected and persisted profiles
#   match; otherwise 1 with recovery guidance.
_profile_validate_existing_selection() {
    local existing_profile=""

    if [ "${SETUP_MODE:-interactive}" != "from_env" ]; then
        return 0
    fi
    existing_profile="$(_root_env_value \
        "${PROJECT_ROOT}/.env" DEPLOYMENT_PROFILE_ID)"
    if [ -z "$existing_profile" ]; then
        echo "[ERROR] Existing .env has no DEPLOYMENT_PROFILE_ID."
        echo "        Re-run setup interactively to generate it."
        return 1
    fi
    if [ "$existing_profile" != "$APP_CONFIG_ID" ]; then
        echo "[ERROR] Existing .env belongs to profile '${existing_profile}',"
        echo "        but '${APP_CONFIG_ID}' was selected."
        echo "        Select '${existing_profile}' or re-run setup interactively."
        return 1
    fi
    return 0
}

# run_executable_profile_setup
# Runs the common schema-5 setup flow for the selected site config.
#
# Returns:
#   0 after successful configuration/rendering; otherwise nonzero.
#
# Side effects:
#   May replace ignored root .env, render swarm-stack.yml, or run one explicitly
#   selected post-configuration action.
run_executable_profile_setup() {
    local python_command=""

    python_command="$(_executable_profile_python)" || {
        echo "[ERROR] Python 3 is required for executable site profiles."
        return 1
    }
    _profile_validate_existing_selection || return 1
    _profile_show_identity
    if [ "${SETUP_MODE:-interactive}" != "from_env" ]; then
        _profile_collect_database
        _profile_collect_routing
        echo ""
        echo "Step 3: Backend image, resources, and storage"
        echo "  Image repository: ${APP_IMAGE_NAME}"
        _profile_collect_services
        _profile_collect_pgadmin
        echo ""
        echo "Validating and writing public deployment configuration..."
        _profile_write_environment "$python_command" || return 1
    else
        echo ""
        echo "Validating existing root .env without changing it..."
    fi
    _profile_render_stack "$python_command" || return 1
    load_root_env "$PROJECT_ROOT" || return 1
    echo ""
    echo "[OK] ${APP_NAME} stack configuration is ready."
    _profile_setup_final_actions
}
