#!/bin/bash
# ==============================================================================
# deployment-profile-inputs.sh - Capability-driven deployment input coordinator
# ==============================================================================
#
# Normalizes one selected site profile into operator-owned deployment values.
# Every profile uses this coordinator regardless of schema or renderer. Routing
# and service collectors are shared capability modules; renderer selection
# happens only after all applicable questions have been answered.
#
# Dependencies:
#   - setup/modules/site_helpers.sh
#   - setup/modules/deployment-profile-prompts.sh
#   - setup/modules/deployment-profile-routing.sh
#   - setup/modules/deployment-profile-services.sh
# ==============================================================================

# Guard against multiple sourcing.
if [ -n "${_DEPLOYMENT_PROFILE_INPUTS_LOADED:-}" ]; then
    return 0 2>/dev/null || true
fi
_DEPLOYMENT_PROFILE_INPUTS_LOADED=1

# ------------------------------------------------------------------------------
# _deployment_existing_value
# ------------------------------------------------------------------------------
# Reads one persisted deployment value and otherwise returns a profile default.
#
# Arguments:
#   $1 - Environment key.
#   $2 - Default value.
#
# Output:
#   Persisted or default value.
# ------------------------------------------------------------------------------
_deployment_existing_value() {
    local key="$1"
    local fallback="$2"
    local value=""

    if [ -f "${PROJECT_ROOT}/.env" ]; then
        value="$(_root_env_value "${PROJECT_ROOT}/.env" "$key")"
    fi
    printf '%s' "${value:-$fallback}"
}

# ------------------------------------------------------------------------------
# _deployment_default_stack_name
# ------------------------------------------------------------------------------
# Resolves the selected profile's stack-name default.
#
# Output:
#   Existing value, declared stack name, or a slug of the profile name.
# ------------------------------------------------------------------------------
_deployment_default_stack_name() {
    local fallback="${APP_STACK_NAME:-}"

    if [ -z "$fallback" ]; then
        fallback="$(printf '%s' "$APP_NAME" |
            tr '[:upper:]' '[:lower:]' |
            tr ' _' '--' |
            sed 's/[^a-z0-9._-]//g')"
    fi
    _deployment_existing_value STACK_NAME "$fallback"
}

# ------------------------------------------------------------------------------
# _deployment_profile_matches_existing_env
# ------------------------------------------------------------------------------
# Prevents reconfiguring an existing clone with a different selected profile.
#
# Returns:
#   0 when no environment exists or its profile matches; otherwise 1.
# ------------------------------------------------------------------------------
_deployment_profile_matches_existing_env() {
    local existing_profile=""

    if [ ! -f "${PROJECT_ROOT}/.env" ]; then
        return 0
    fi
    existing_profile="$(_root_env_value \
        "${PROJECT_ROOT}/.env" DEPLOYMENT_PROFILE_ID)"
    if [ -z "$existing_profile" ] || [ "$existing_profile" = "$APP_CONFIG_ID" ]; then
        return 0
    fi
    echo "[ERROR] Existing .env belongs to profile '${existing_profile}',"
    echo "        but '${APP_CONFIG_ID}' was selected."
    echo "        Select '${existing_profile}' or remove the generated .env first."
    return 1
}

# ------------------------------------------------------------------------------
# initialize_deployment_profile_context
# ------------------------------------------------------------------------------
# Derives common capability and secret-handling flags from the loaded profile.
#
# Returns:
#   0 after setting shared setup globals.
# ------------------------------------------------------------------------------
initialize_deployment_profile_context() {
    APP_IS_INTERNAL="false"
    if [ "${APP_EXPOSURE_TYPE:-public}" = "internal" ] ||
        [ "${APP_STACK_ROLE:-}" = "internal-api" ]; then
        APP_IS_INTERNAL="true"
    fi

    APP_IS_EXECUTABLE="false"
    if [ "${APP_RENDERER_TYPE:-generic}" = "executable" ]; then
        APP_IS_EXECUTABLE="true"
    fi

    APP_SECRET_COUNT="${APP_SECRET_COUNT:-0}"
    SECRETS_REQUIRED="false"
    if [ "$APP_SECRET_COUNT" -gt 0 ] 2>/dev/null; then
        SECRETS_REQUIRED="true"
    fi

    SECRETS_TEMPLATE_PATH="${SCRIPT_DIR}/templates/secrets.env.template"
    if [ -n "${APP_SECRETS_TEMPLATE:-}" ]; then
        SECRETS_TEMPLATE_PATH="${PROJECT_ROOT}/${APP_SECRETS_TEMPLATE}"
    fi
}

# ------------------------------------------------------------------------------
# show_selected_deployment_profile
# ------------------------------------------------------------------------------
# Displays profile data before asking deployment-instance questions.
#
# Returns:
#   0 after printing the summary.
# ------------------------------------------------------------------------------
show_selected_deployment_profile() {
    echo ""
    echo "Selected deployment profile: ${APP_NAME} (${APP_CONFIG_ID})"
    echo "Stack: ${APP_STACK_FAMILY}/${APP_STACK_ROLE}, Database: ${APP_DB_TYPE}, Image: ${APP_IMAGE_NAME}:${APP_IMAGE_DEFAULT_VERSION}"
    if [ "${APP_REQUIRES_WEB:-false}" = "true" ]; then
        echo "Additional service: WebApp (${APP_WEB_IMAGE_NAME}:${APP_WEB_IMAGE_DEFAULT_VERSION})"
    fi
    echo ""
}

# ------------------------------------------------------------------------------
# _collect_public_domains
# ------------------------------------------------------------------------------
# Collects WebApp and API public identities in their dependency order. A
# persisted or profile-declared API domain remains authoritative. When no API
# default exists for a WebApp stack, the entered WebApp domain supplies the
# conventional `api.<web-domain>` default.
#
# Returns:
#   0 after setting public API and optional WebApp domains and base URLs.
# ------------------------------------------------------------------------------
_collect_public_domains() {
    local default_domain=""
    local default_web_domain=""

    WEB_DOMAIN=""
    WEB_BASE_URL=""
    if [ "${APP_REQUIRES_WEB:-false}" = "true" ]; then
        default_web_domain="$(_deployment_existing_value \
            WEB_DOMAIN \
            "${APP_ROUTING_WEB_DOMAIN:-}")"
        prompt_deployment_value \
            WEB_DOMAIN \
            "WebApp domain (e.g. app.example.com)" \
            "$default_web_domain" \
            "domain"
        WEB_BASE_URL="https://${WEB_DOMAIN}"
    fi

    default_domain="$(_deployment_existing_value \
        DOMAIN \
        "${APP_ROUTING_DOMAIN:-}")"
    if [ -z "$default_domain" ] && [ -n "$WEB_DOMAIN" ]; then
        default_domain="api.${WEB_DOMAIN}"
    fi
    prompt_deployment_value \
        DOMAIN \
        "API domain (e.g. api.example.com)" \
        "$default_domain" \
        "domain"
    API_BASE_URL="https://${DOMAIN}"
}

# ------------------------------------------------------------------------------
# _collect_stack_and_domains
# ------------------------------------------------------------------------------
# Collects deployment stack and applicable public/internal routing identity.
#
# Returns:
#   0 after setting stack, API/Web routing, and optional internal network.
# ------------------------------------------------------------------------------
_collect_stack_and_domains() {
    local default_internal_network=""

    prompt_deployment_value \
        STACK_NAME \
        "Docker stack name" \
        "$(_deployment_default_stack_name)" \
        "name"

    if [ "$APP_IS_INTERNAL" = "true" ]; then
        DOMAIN="$(_deployment_existing_value \
            DOMAIN \
            "${APP_INTERNAL_URL:-http://${APP_INTERNAL_SERVICE}:${APP_ROUTING_CONTAINER_PORT}}")"
        API_BASE_URL="$DOMAIN"
        WEB_DOMAIN=""
        WEB_BASE_URL=""
        echo "Domain: ${DOMAIN} (internal service URL)"
        default_internal_network="$(_deployment_existing_value \
            INTERNAL_NETWORK \
            "${APP_INTERNAL_NETWORK:-${STACK_NAME}_internal}")"
        if [ "${APP_INTERNAL_NETWORK_EXTERNAL:-false}" = "true" ]; then
            prompt_external_overlay_network_name \
                INTERNAL_NETWORK \
                "$default_internal_network"
        else
            prompt_deployment_value \
                INTERNAL_NETWORK \
                "Internal overlay network" \
                "$default_internal_network" \
                "name"
        fi
        return 0
    fi

    _collect_public_domains
}

# ------------------------------------------------------------------------------
# _database_choice_pairs
# ------------------------------------------------------------------------------
# Converts profile-allowed database modes into stable numbered menu entries.
#
# Output:
#   One "value|label" pair per line.
# ------------------------------------------------------------------------------
_database_choice_pairs() {
    local mode=""

    for mode in ${APP_DB_ALLOWED_MODES}; do
        case "$mode" in
            local) echo "local|Local (deploy in swarm)" ;;
            external) echo "external|External (existing server)" ;;
            none) echo "none|None (no database service)" ;;
            *) echo "${mode}|${mode}" ;;
        esac
    done
}

# ------------------------------------------------------------------------------
# _collect_database
# ------------------------------------------------------------------------------
# Collects only database questions enabled by the profile.
#
# Returns:
#   0 after setting database type, mode, host, port, name, and user.
# ------------------------------------------------------------------------------
_collect_database() {
    local choices=()
    local default_mode=""
    local existing_mode=""
    local existing_host=""
    local existing_port=""

    DB_TYPE="$APP_DB_TYPE"
    echo ""
    echo "Database type (from deployment profile): ${DB_TYPE}"
    while IFS= read -r choice; do
        [ -n "$choice" ] && choices+=("$choice")
    done < <(_database_choice_pairs)

    default_mode="$(_deployment_existing_value \
        DB_MODE \
        "$APP_DB_DEFAULT_MODE")"
    if [ "${#choices[@]}" -eq 1 ]; then
        DB_MODE="${choices[0]%%|*}"
        echo "Database mode: ${DB_MODE} (fixed by profile)"
    else
        prompt_deployment_choice \
            DB_MODE \
            "Database mode" \
            "$default_mode" \
            "${choices[@]}"
        echo "DB mode: ${DB_MODE}"
    fi

    DB_NAME="$(_deployment_existing_value DB_NAME "$APP_DB_DEFAULT_NAME")"
    DB_USER="$(_deployment_existing_value DB_USER "$APP_DB_DEFAULT_USER")"
    if [ "$DB_TYPE" = "none" ]; then
        DB_HOST=""
        DB_PORT=""
        return 0
    fi
    if [ "$DB_MODE" = "external" ]; then
        if [ -f "${PROJECT_ROOT}/.env" ]; then
            existing_mode="$(_root_env_value "${PROJECT_ROOT}/.env" DB_MODE)"
        fi
        if [ "$existing_mode" = "external" ]; then
            existing_host="$(_root_env_value "${PROJECT_ROOT}/.env" DB_HOST)"
            existing_port="$(_root_env_value "${PROJECT_ROOT}/.env" DB_PORT)"
        fi
        DB_HOST="${existing_host:-${APP_DB_EXTERNAL_HOST_DEFAULT:-}}"
        DB_PORT="${existing_port:-${APP_DB_EXTERNAL_PORT_DEFAULT:-$APP_DB_DEFAULT_PORT}}"
        prompt_deployment_value \
            DB_HOST "External database host" "$DB_HOST" "host"
        prompt_deployment_value \
            DB_PORT "External database port" "$DB_PORT" "port"
    else
        DB_HOST="$(_deployment_existing_value DB_HOST "$APP_DB_DEFAULT_HOST")"
        DB_PORT="$(_deployment_existing_value DB_PORT "$APP_DB_DEFAULT_PORT")"
    fi
    if [ "${APP_DB_PROMPT_IDENTITY:-false}" = "true" ]; then
        prompt_deployment_value \
            DB_NAME "Database name" "$DB_NAME" "identifier"
        prompt_deployment_value \
            DB_USER "Database user" "$DB_USER" "identifier"
    fi
}

# ------------------------------------------------------------------------------
# _derive_keycloak_deployment_values
# ------------------------------------------------------------------------------
# Retains every persisted Keycloak choice across shared wizard reruns.
#
# Returns:
#   0 after exporting the active Keycloak deployment selections.
# ------------------------------------------------------------------------------
_derive_keycloak_deployment_values() {
    KEYCLOAK_BASE_URL="$(_deployment_existing_value KEYCLOAK_BASE_URL "${APP_KEYCLOAK_BASE_URL:-}")"
    KEYCLOAK_ISSUER_URL="$(_deployment_existing_value KEYCLOAK_ISSUER_URL "${APP_KEYCLOAK_ISSUER_URL:-}")"
    KEYCLOAK_REALM="$(_deployment_existing_value KEYCLOAK_REALM "${APP_KEYCLOAK_REALM:-}")"
    KEYCLOAK_REALM_DISPLAY_NAME="$(_deployment_existing_value KEYCLOAK_REALM_DISPLAY_NAME "${APP_KEYCLOAK_REALM_DISPLAY_NAME:-}")"
    KEYCLOAK_REALM_ENABLED="$(_deployment_existing_value KEYCLOAK_REALM_ENABLED "${APP_KEYCLOAK_REALM_ENABLED:-true}")"
    KEYCLOAK_REGISTRATION_ALLOWED="$(_deployment_existing_value KEYCLOAK_REGISTRATION_ALLOWED "${APP_KEYCLOAK_REGISTRATION_ALLOWED:-false}")"
    KEYCLOAK_RESET_PASSWORD_ALLOWED="$(_deployment_existing_value KEYCLOAK_RESET_PASSWORD_ALLOWED "${APP_KEYCLOAK_RESET_PASSWORD_ALLOWED:-true}")"
    KEYCLOAK_REMEMBER_ME="$(_deployment_existing_value KEYCLOAK_REMEMBER_ME "${APP_KEYCLOAK_REMEMBER_ME:-true}")"
    KEYCLOAK_VERIFY_EMAIL="$(_deployment_existing_value KEYCLOAK_VERIFY_EMAIL "${APP_KEYCLOAK_VERIFY_EMAIL:-true}")"
    KEYCLOAK_LOGIN_WITH_EMAIL_ALLOWED="$(_deployment_existing_value KEYCLOAK_LOGIN_WITH_EMAIL_ALLOWED "${APP_KEYCLOAK_LOGIN_WITH_EMAIL_ALLOWED:-true}")"
    KEYCLOAK_BOOTSTRAP_TEST_USERS_ENABLED="$(_deployment_existing_value KEYCLOAK_BOOTSTRAP_TEST_USERS_ENABLED "${APP_KEYCLOAK_BOOTSTRAP_TEST_USERS_ENABLED:-false}")"
    KEYCLOAK_AUDIENCE="$(_deployment_existing_value KEYCLOAK_AUDIENCE "${APP_KEYCLOAK_AUDIENCE:-}")"
    KEYCLOAK_FRONTEND_CLIENT_ID="$(_deployment_existing_value KEYCLOAK_FRONTEND_CLIENT_ID "${APP_KEYCLOAK_FRONTEND_CLIENT_ID:-}")"
    KEYCLOAK_BACKEND_CLIENT_ID="$(_deployment_existing_value KEYCLOAK_BACKEND_CLIENT_ID "${APP_KEYCLOAK_BACKEND_CLIENT_ID:-}")"
    export KEYCLOAK_BASE_URL KEYCLOAK_ISSUER_URL KEYCLOAK_REALM
    export KEYCLOAK_REALM_DISPLAY_NAME KEYCLOAK_REALM_ENABLED
    export KEYCLOAK_REGISTRATION_ALLOWED KEYCLOAK_RESET_PASSWORD_ALLOWED
    export KEYCLOAK_REMEMBER_ME KEYCLOAK_VERIFY_EMAIL
    export KEYCLOAK_LOGIN_WITH_EMAIL_ALLOWED
    export KEYCLOAK_BOOTSTRAP_TEST_USERS_ENABLED KEYCLOAK_AUDIENCE
    export KEYCLOAK_FRONTEND_CLIENT_ID KEYCLOAK_BACKEND_CLIENT_ID
}

# ------------------------------------------------------------------------------
# _derive_shared_deployment_values
# ------------------------------------------------------------------------------
# Derives common stack values after every capability-specific prompt section.
#
# Returns:
#   0 after exporting shared and optional Keycloak deployment selections.
# ------------------------------------------------------------------------------
_derive_shared_deployment_values() {
    local profile_origin="${APP_ROUTING_WEB_BASE_URL:-${APP_ROUTING_API_BASE_URL:-}}"
    local active_origin="${WEB_BASE_URL:-${API_BASE_URL:-}}"
    local configured_cors=""

    SECRET_PREFIX="$(printf '%s' "$STACK_NAME" |
        tr '[:upper:]-' '[:lower:]_')"
    if [ "${APP_SECRETS_PREFIXED:-true}" = "false" ]; then
        SECRET_PREFIX=""
    fi

    configured_cors="$(jq -r '.cors.origins // [] | join(",")' \
        "$APP_CONFIG_FILE" 2>/dev/null)"
    if [ -n "$configured_cors" ] && [ -n "$profile_origin" ]; then
        CORS_ORIGINS="${configured_cors//$profile_origin/$active_origin}"
    else
        CORS_ORIGINS="$active_origin"
    fi

    STACK_FAMILY="${APP_STACK_FAMILY:-api}"
    STACK_ROLE="${APP_STACK_ROLE:-api}"
    PRIMARY_SERVICE="${APP_PRIMARY_SERVICE:-api}"
    export STACK_FAMILY STACK_ROLE PRIMARY_SERVICE
    if [ "${APP_IS_EXECUTABLE:-false}" = "true" ]; then
        AUTH_PROVIDER="${APP_AUTH_PROVIDER:-none}"
        export AUTH_PROVIDER
        _derive_keycloak_deployment_values
    fi
}

# ------------------------------------------------------------------------------
# _initialize_default_routing_values
# ------------------------------------------------------------------------------
# Derives non-interactive routing defaults from the selected site profile for
# the editable-file setup path.
#
# Returns:
#   0 after setting stack, public/internal routing, proxy, TLS, and port values.
# ------------------------------------------------------------------------------
_initialize_default_routing_values() {
    STACK_NAME="$(_deployment_default_stack_name)"
    API_PUBLISHED_PORT="${APP_ROUTING_API_PUBLISHED_PORT:-8083}"
    WEB_PUBLISHED_PORT="${APP_ROUTING_WEB_PUBLISHED_PORT:-8084}"
    PGADMIN_PUBLISHED_PORT="${APP_ROUTING_PGADMIN_PUBLISHED_PORT:-5054}"
    TRAEFIK_CERT_RESOLVER="${APP_ROUTING_TRAEFIK_CERT_RESOLVER:-le}"
    TRAEFIK_CONSTRAINT_LABEL="${APP_ROUTING_TRAEFIK_CONSTRAINT_LABEL:-traefik-public}"
    if [ "$APP_IS_INTERNAL" = "true" ]; then
        DOMAIN="${APP_INTERNAL_URL:-http://${APP_INTERNAL_SERVICE}:${APP_ROUTING_CONTAINER_PORT}}"
        API_BASE_URL="$DOMAIN"
        WEB_DOMAIN=""
        WEB_BASE_URL=""
        INTERNAL_NETWORK="${APP_INTERNAL_NETWORK:-${STACK_NAME}_internal}"
        PROXY_TYPE="none"
        SSL_MODE=""
        TRAEFIK_NETWORK=""
        TRAEFIK_CONSTRAINT_LABEL=""
        API_PUBLISHED_PORT=""
        WEB_PUBLISHED_PORT=""
        return 0
    fi
    WEB_DOMAIN="${APP_ROUTING_WEB_DOMAIN:-}"
    WEB_BASE_URL="${APP_ROUTING_WEB_BASE_URL:-}"
    if [ -n "$WEB_DOMAIN" ] && [ -z "$WEB_BASE_URL" ]; then
        WEB_BASE_URL="https://${WEB_DOMAIN}"
    fi
    DOMAIN="${APP_ROUTING_DOMAIN:-}"
    if [ -z "$DOMAIN" ] && [ -n "$WEB_DOMAIN" ]; then
        DOMAIN="api.${WEB_DOMAIN}"
    fi
    API_BASE_URL="${APP_ROUTING_API_BASE_URL:-}"
    if [ -n "$DOMAIN" ] && [ -z "$API_BASE_URL" ]; then
        API_BASE_URL="https://${DOMAIN}"
    fi
    if [ "${APP_EXPOSURE_TRAEFIK:-true}" = "true" ]; then
        PROXY_TYPE="traefik"
        SSL_MODE="${APP_ROUTING_DEFAULT_SSL_MODE:-letsencrypt}"
        TRAEFIK_NETWORK="${APP_ROUTING_TRAEFIK_NETWORK:-traefik-public}"
    else
        PROXY_TYPE="none"
        SSL_MODE=""
        TRAEFIK_NETWORK=""
        TRAEFIK_CONSTRAINT_LABEL=""
    fi
}

# ------------------------------------------------------------------------------
# _initialize_default_database_values
# ------------------------------------------------------------------------------
# Derives non-secret database identity and connectivity defaults for file mode.
#
# Returns:
#   0 after setting database type, mode, host, port, name, and user.
# ------------------------------------------------------------------------------
_initialize_default_database_values() {
    DB_TYPE="$APP_DB_TYPE"
    DB_MODE="$APP_DB_DEFAULT_MODE"
    DB_NAME="$APP_DB_DEFAULT_NAME"
    DB_USER="$APP_DB_DEFAULT_USER"
    if [ "$DB_TYPE" = "none" ]; then
        DB_HOST=""
        DB_PORT=""
    elif [ "$DB_MODE" = "external" ]; then
        DB_HOST="${APP_DB_EXTERNAL_HOST_DEFAULT:-$APP_DB_DEFAULT_HOST}"
        DB_PORT="${APP_DB_EXTERNAL_PORT_DEFAULT:-$APP_DB_DEFAULT_PORT}"
    else
        DB_HOST="$APP_DB_DEFAULT_HOST"
        DB_PORT="$APP_DB_DEFAULT_PORT"
    fi
}

# ------------------------------------------------------------------------------
# _initialize_default_service_values
# ------------------------------------------------------------------------------
# Derives service, resource, storage, optional admin UI, and redirect defaults.
#
# Returns:
#   0 after setting every renderer-neutral service value used by both writers.
# ------------------------------------------------------------------------------
_initialize_default_service_values() {
    IMAGE_NAME="$APP_IMAGE_NAME"
    IMAGE_VERSION="$APP_IMAGE_DEFAULT_VERSION"
    API_REPLICAS="$APP_DEFAULT_REPLICAS"
    NGINX_REPLICAS="$API_REPLICAS"
    MEMORY_LIMIT="$APP_DEFAULT_MEMORY_LIMIT"
    DATA_ROOT="$APP_DATA_ROOT"
    WEB_ENABLED="${APP_REQUIRES_WEB:-false}"
    WEB_IMAGE_NAME="${APP_WEB_IMAGE_NAME:-}"
    WEB_IMAGE_VERSION="${APP_WEB_IMAGE_DEFAULT_VERSION:-}"
    WEB_REPLICAS="${APP_WEB_DEFAULT_REPLICAS:-1}"
    WEB_MEMORY_LIMIT="${APP_WEB_DEFAULT_MEMORY_LIMIT:-unlimited}"
    PGADMIN_ENABLED="${APP_ADMIN_UI_DEFAULT_ENABLED:-false}"
    PGADMIN_DOMAIN="${APP_ADMIN_UI_DEFAULT_DOMAIN:-}"
    PGADMIN_EMAIL="${APP_ADMIN_UI_DEFAULT_EMAIL:-}"
    PGADMIN_REPLICAS="0"
    if [ "$PGADMIN_ENABLED" = "true" ]; then
        PGADMIN_REPLICAS="${APP_ADMIN_UI_DEFAULT_REPLICAS:-1}"
        [ "$PGADMIN_REPLICAS" -gt 0 ] 2>/dev/null || PGADMIN_REPLICAS="1"
    fi
    MONGO_EXPRESS_URL="$PGADMIN_DOMAIN"
    MONGO_EXPRESS_USERNAME="dbadmin"
    MONGO_EXPRESS_REPLICAS="$PGADMIN_REPLICAS"
    REDIRECT_TARGET_BASE_URL="${APP_REDIRECT_TARGET_BASE_URL:-}"
    REDIRECT_STATUS_CODE="${APP_REDIRECT_STATUS_CODE:-302}"
}

# ------------------------------------------------------------------------------
# initialize_deployment_configuration_defaults
# ------------------------------------------------------------------------------
# Builds the same profile-owned defaults used by guided prompts without reading
# the terminal. Existing environments are rehydrated instead of overwritten.
#
# Returns:
#   0 after setting the complete writer input contract; otherwise nonzero.
# ------------------------------------------------------------------------------
initialize_deployment_configuration_defaults() {
    if [ -f "${PROJECT_ROOT}/.env" ]; then
        load_deployment_configuration_from_env
        return $?
    fi
    _initialize_default_routing_values
    _initialize_default_database_values
    _initialize_default_service_values
    _derive_shared_deployment_values
}

# ------------------------------------------------------------------------------
# load_deployment_configuration_from_env
# ------------------------------------------------------------------------------
# Loads an existing environment through the shared profile-independent path.
#
# Returns:
#   0 after normalizing missing compatibility fields.
# ------------------------------------------------------------------------------
load_deployment_configuration_from_env() {
    load_root_env "$PROJECT_ROOT" || return 1
    STACK_NAME="${STACK_NAME:-$(_deployment_default_stack_name)}"
    DB_TYPE="${DB_TYPE:-$APP_DB_TYPE}"
    DB_MODE="${DB_MODE:-$APP_DB_DEFAULT_MODE}"
    IMAGE_NAME="${IMAGE_NAME:-$APP_IMAGE_NAME}"
    IMAGE_VERSION="${IMAGE_VERSION:-$APP_IMAGE_DEFAULT_VERSION}"
    API_REPLICAS="${API_REPLICAS:-$APP_DEFAULT_REPLICAS}"
    MEMORY_LIMIT="${MEMORY_LIMIT:-$APP_DEFAULT_MEMORY_LIMIT}"
    DATA_ROOT="${DATA_ROOT:-$APP_DATA_ROOT}"
    DOMAIN="${DOMAIN:-$APP_ROUTING_DOMAIN}"
    API_BASE_URL="${API_BASE_URL:-${APP_ROUTING_API_BASE_URL:-https://${DOMAIN}}}"
    WEB_ENABLED="${WEB_ENABLED:-$APP_REQUIRES_WEB}"
    WEB_DOMAIN="${WEB_DOMAIN:-$APP_ROUTING_WEB_DOMAIN}"
    WEB_BASE_URL="${WEB_BASE_URL:-$APP_ROUTING_WEB_BASE_URL}"
    WEB_IMAGE_NAME="${WEB_IMAGE_NAME:-$APP_WEB_IMAGE_NAME}"
    WEB_IMAGE_VERSION="${WEB_IMAGE_VERSION:-$APP_WEB_IMAGE_DEFAULT_VERSION}"
    WEB_REPLICAS="${WEB_REPLICAS:-$APP_WEB_DEFAULT_REPLICAS}"
    WEB_MEMORY_LIMIT="${WEB_MEMORY_LIMIT:-$APP_WEB_DEFAULT_MEMORY_LIMIT}"
    if [ "${PROXY_TYPE:-none}" = "traefik" ]; then
        if [ -z "${TRAEFIK_CONSTRAINT_LABEL:-}" ]; then
            TRAEFIK_CONSTRAINT_LABEL="${APP_ROUTING_TRAEFIK_CONSTRAINT_LABEL:-traefik-public}"
        fi
    else
        TRAEFIK_CONSTRAINT_LABEL=""
    fi
    _derive_shared_deployment_values
}

# ------------------------------------------------------------------------------
# collect_deployment_configuration
# ------------------------------------------------------------------------------
# Runs the single setup dialogue for every selected profile.
#
# Returns:
#   0 after loading or collecting and normalizing all deployment values.
# ------------------------------------------------------------------------------
collect_deployment_configuration() {
    _deployment_profile_matches_existing_env || return 1
    if [ "${SETUP_MODE:-interactive}" = "from_env" ]; then
        echo "Fast setup mode: loading all values from existing .env"
        load_deployment_configuration_from_env
        return $?
    fi
    if [ "${SETUP_MODE:-interactive}" = "file" ]; then
        echo "Step 2: File-based Deployment Configuration"
        echo "============================================"
        echo "Profile defaults and existing public values will be written with"
        echo "shared comments, then opened in your selected terminal editor."
        initialize_deployment_configuration_defaults
        return $?
    fi

    echo "Step 2: Deployment Configuration"
    echo "===================================="
    echo ""
    echo "These values are specific to THIS deployment instance."
    _collect_stack_and_domains || return 1
    _collect_database || return 1
    collect_deployment_proxy_and_ports || return 1
    collect_deployment_services_and_storage || return 1
    collect_deployment_database_management || return 1
    collect_deployment_redirector || return 1
    _derive_shared_deployment_values
}
