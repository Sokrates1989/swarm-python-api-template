#!/bin/bash
# ==============================================================================
# site_helpers.sh - App config discovery, loading, and selection helpers
# ==============================================================================
#
# This module provides functions to discover app deployment manifests from
# site-configs/, load app metadata into shell variables, display an app
# selection menu, and resolve the root .env context.
#
# In this deployment model, each git clone of this repo IS one deployment.
# The .env, swarm-stack.yml, and data directories all live at PROJECT ROOT.
# site-configs/ holds app manifests that describe what a backend app needs
# (database type, required services, image name, etc.) -- info known at
# development time.
#
# Functions:
#   discover_app_configs    - Scan site-configs/ for available app config IDs
#   load_app_config         - Parse a site-configs/<appId>.json into globals
#   show_app_selector       - Interactive numbered menu for app selection
#   load_root_env           - Load root .env into convenience globals
#
# Dependencies:
#   - jq (for JSON parsing)
#   - site-configs/<appId>.json files following supported profile schemas
#   - Root .env file (optional, for running context)
#
# Exported Globals (set by load_app_config):
#   APP_CONFIG_FILE, APP_ID, APP_NAME, APP_DESCRIPTION,
#   APP_KIND, APP_STACK_NAME, APP_STACK_FAMILY, APP_STACK_ROLE,
#   APP_PRIMARY_SERVICE,
#   APP_ROUTING_CONTAINER_PORT, APP_ROUTING_DOMAIN,
#   APP_ROUTING_API_BASE_URL, APP_ROUTING_WEB_DOMAIN,
#   APP_ROUTING_WEB_BASE_URL, APP_ROUTING_DEFAULT_SSL_MODE,
#   APP_ROUTING_HEALTH_PATH, APP_ROUTING_WEB_HEALTH_PATH,
#   APP_ROUTING_TRAEFIK_NETWORK, APP_ROUTING_TRAEFIK_CONSTRAINT_LABEL,
#   APP_ROUTING_TRAEFIK_CERT_RESOLVER,
#   APP_ROUTING_API_PUBLISHED_PORT, APP_ROUTING_WEB_PUBLISHED_PORT,
#   APP_ROUTING_PGADMIN_PUBLISHED_PORT, APP_DB_TYPE, APP_DB_DEFAULT_MODE,
#   APP_DB_ALLOWED_MODES, APP_DB_DEFAULT_HOST, APP_DB_DEFAULT_PORT,
#   APP_DB_EXTERNAL_HOST_DEFAULT, APP_DB_EXTERNAL_PORT_DEFAULT,
#   APP_REQUIRES_REDIS, APP_REQUIRES_DATABASE, APP_SECRET_COUNT,
#   APP_IMAGE_NAME, APP_IMAGE_DEFAULT_VERSION,
#   APP_WEB_IMAGE_NAME, APP_WEB_IMAGE_DEFAULT_VERSION,
#   APP_DEFAULT_REPLICAS, APP_DEFAULT_MEMORY_LIMIT,
#   APP_WEB_DEFAULT_REPLICAS, APP_WEB_DEFAULT_MEMORY_LIMIT,
#   APP_EXPOSURE_TYPE, APP_INTERNAL_URL, APP_INTERNAL_SERVICE,
#   APP_INTERNAL_NETWORK, APP_INTERNAL_NETWORK_EXTERNAL,
#   APP_INTERNAL_NETWORK_ATTACHABLE, APP_DATA_ROOT, APP_ADMIN_UI_TYPE,
#   APP_ADMIN_UI_DEFAULT_DOMAIN, APP_ADMIN_UI_DEFAULT_EMAIL,
#   APP_ADMIN_UI_DEFAULT_DOMAIN_PREFIX, APP_ADMIN_UI_DEFAULT_ENABLED,
#   APP_ADMIN_UI_DEFAULT_REPLICAS, APP_ADMIN_UI_CONFIGURABLE_REPLICAS,
#   APP_ADMIN_UI_SECRET,
#   APP_SECRETS_TEMPLATE, APP_SECRETS_PREFIXED,
#   APP_SECRET_NAMES, APP_OPTIONAL_SECRET_NAMES, APP_ENV_KEYS,
#   APP_RENDERER_TYPE, APP_RENDERER_STRICT, APP_RENDERER_API_TEMPLATE,
#   APP_RENDERER_FOOTER_TEMPLATE, APP_REQUIRES_WEB,
#   APP_RELEASE_STACK_ID, APP_RELEASE_VERSION_POLICY,
#   APP_RELEASE_VERSION_FLOOR
#
# Exported Globals (set by load_root_env):
#   STACK_NAME, DB_TYPE, DB_MODE, PROXY_TYPE, IMAGE_NAME, IMAGE_VERSION,
#   DOMAIN, API_REPLICAS, NGINX_REPLICAS, MEMORY_LIMIT, SECRET_PREFIX,
#   APP_PROFILE, AUTH_PROVIDER, KEYCLOAK_REALM, and related public identity
# ==============================================================================

# Guard against multiple sourcing.
if [ -n "$_SITE_HELPERS_LOADED" ]; then
    return 0 2>/dev/null || true
fi
_SITE_HELPERS_LOADED=1

# ==============================================================================
# Internal helpers
# ==============================================================================

# _jq_or_default
# Reads a jq path from a JSON file, returning a default when the field is
# null, empty, or jq is unavailable.
#
# Arguments:
#   $1 - json_file: path to the JSON file
#   $2 - jq_path: jq expression (e.g. '.appId')
#   $3 - default_value: fallback value
#
# Output:
#   Prints the resolved value to stdout.
_jq_or_default() {
    local json_file="$1"
    local jq_path="$2"
    local default_value="$3"

    if ! command -v jq &>/dev/null; then
        echo "$default_value"
        return 0
    fi

    local val
    # Read the raw value first without the // alternative so that boolean
    # false is not treated as absent and silently replaced by the default.
    local raw_type
    raw_type=$(jq -r "$jq_path | type" "$json_file" 2>/dev/null)
    if [ "$raw_type" = "null" ] || [ -z "$raw_type" ]; then
        echo "$default_value"
        return 0
    fi
    val=$(jq -r "$jq_path | tostring" "$json_file" 2>/dev/null)
    if [ -z "$val" ]; then
        echo "$default_value"
    else
        echo "$val"
    fi
}

# ==============================================================================
# site_profile_declares_secrets
# ==============================================================================
# Checks whether a site profile declares any base, optional, enabled-capability,
# or database-management Docker secret.
#
# Arguments:
#   $1 - json_file: path to the selected site-profile JSON.
#
# Returns:
#   0 when at least one secret identifier is declared; otherwise 1.
# ==============================================================================
site_profile_declares_secrets() {
    local json_file="$1"

    [ -f "$json_file" ] || return 1
    command -v jq >/dev/null 2>&1 || return 1
    jq -e '
      (
        [
          .secrets[]?,
          .optionalSecrets[]?,
          (
            (.capabilities // {})
            | to_entries[]
            | select(.value.enabled == true)
            | .value.secretMounts[]?.name
          ),
          .database.pgadminSecret?
        ]
        | map(select(type == "string" and length > 0))
        | unique
        | length
      ) > 0
    ' "$json_file" >/dev/null
}

# ==============================================================================
# discover_app_configs
# ==============================================================================
# Scans site-configs/ for JSON files (excluding _template.json) and prints
# one app config ID per line. IDs are derived from the filename without the
# .json extension.
#
# Arguments:
#   $1 - project_root: absolute path to the repository root
#
# Output:
#   Prints app config IDs to stdout, one per line. Empty if none found.
#
# Returns:
#   0 always
# ==============================================================================
discover_app_configs() {
    local project_root="$1"
    local config_dir="${project_root}/site-configs"

    if [ ! -d "$config_dir" ]; then
        return 0
    fi

    local f
    for f in "${config_dir}"/*.json; do
        [ -f "$f" ] || continue
        local base
        base="$(basename "$f" .json)"
        # Skip template file
        if [ "$base" = "_template" ]; then
            continue
        fi
        echo "$base"
    done
}

# ------------------------------------------------------------------------------
# _load_keycloak_profile_defaults
# ------------------------------------------------------------------------------
# Loads the public Keycloak defaults used by every authentication-capable app.
#
# Arguments:
#   $1 - Selected site-profile JSON path.
#
# Returns:
#   0 after populating APP_KEYCLOAK_* globals.
# ------------------------------------------------------------------------------
_load_keycloak_profile_defaults() {
    local config_file="$1"

    APP_KEYCLOAK_BASE_URL="$(_jq_or_default "$config_file" '.auth.serverUrl' "")"
    APP_KEYCLOAK_ISSUER_URL="$(_jq_or_default "$config_file" '.auth.issuerUrl' "")"
    APP_KEYCLOAK_REALM="$(_jq_or_default "$config_file" '.auth.realm' "")"
    APP_KEYCLOAK_REALM_DISPLAY_NAME="$(_jq_or_default "$config_file" '.auth.realmDisplayName' "")"
    APP_KEYCLOAK_REALM_ENABLED="$(_jq_or_default "$config_file" '.auth.realmSettings.enabled' "true")"
    APP_KEYCLOAK_REGISTRATION_ALLOWED="$(_jq_or_default "$config_file" '.auth.realmSettings.registrationAllowed' "false")"
    APP_KEYCLOAK_RESET_PASSWORD_ALLOWED="$(_jq_or_default "$config_file" '.auth.realmSettings.resetPasswordAllowed' "true")"
    APP_KEYCLOAK_REMEMBER_ME="$(_jq_or_default "$config_file" '.auth.realmSettings.rememberMe' "true")"
    APP_KEYCLOAK_VERIFY_EMAIL="$(_jq_or_default "$config_file" '.auth.realmSettings.verifyEmail' "true")"
    APP_KEYCLOAK_LOGIN_WITH_EMAIL_ALLOWED="$(_jq_or_default "$config_file" '.auth.realmSettings.loginWithEmailAllowed' "true")"
    APP_KEYCLOAK_BOOTSTRAP_TEST_USERS_ENABLED="$(_jq_or_default "$config_file" '.auth.bootstrapTestUsersEnabled' "false")"
    APP_KEYCLOAK_AUDIENCE="$(_jq_or_default "$config_file" '.auth.audience' "")"
    APP_KEYCLOAK_FRONTEND_CLIENT_ID="$(_jq_or_default "$config_file" '.auth.frontendClientId' "")"
    APP_KEYCLOAK_BACKEND_CLIENT_ID="$(_jq_or_default "$config_file" '.auth.adminClientId' "")"
}

# ==============================================================================
# load_app_config
# ==============================================================================
# Parses site-configs/<configId>.json and populates APP_* globals with the
# app's requirements (database type, services, image, resources).
# These are development-time facts about the app.
#
# Arguments:
#   $1 - project_root: absolute path to the repository root
#   $2 - config_id: the config ID (filename stem in site-configs/)
#
# Returns:
#   0 on success, 1 if the config file is missing or jq unavailable
# ==============================================================================
load_app_config() {
    local project_root="$1"
    local config_id="$2"
    local config_file="${project_root}/site-configs/${config_id}.json"

    if [ ! -f "$config_file" ]; then
        echo "App config not found: $config_file" >&2
        return 1
    fi

    if ! command -v jq &>/dev/null; then
        echo "jq is required but not installed." >&2
        echo "Install it with: sudo apt-get install jq" >&2
        return 1
    fi

    APP_CONFIG_FILE="$config_file"
    APP_CONFIG_ID="$config_id"
    APP_ID="$(_jq_or_default "$config_file" '.appId' "$config_id")"
    APP_NAME="$(_jq_or_default "$config_file" '.name' "$config_id")"
    APP_DESCRIPTION="$(_jq_or_default "$config_file" '.description' "")"
    APP_KIND="$(_jq_or_default "$config_file" '.kind' "api")"
    APP_STACK_NAME="$(_jq_or_default "$config_file" '.stack.name' "")"
    APP_STACK_FAMILY="$(_jq_or_default "$config_file" '.stack.family' "$APP_KIND")"
    APP_STACK_ROLE="$(_jq_or_default "$config_file" '.stack.role' "api")"
    APP_PRIMARY_SERVICE="$(_jq_or_default "$config_file" '.stack.primaryService' "api")"
    APP_ROUTING_CONTAINER_PORT="$(_jq_or_default "$config_file" '.routing.containerPort' "8080")"
    APP_ROUTING_DOMAIN="$(_jq_or_default "$config_file" '.routing.domain // .routing.defaultDomain' "")"
    APP_ROUTING_API_BASE_URL="$(_jq_or_default "$config_file" '.routing.apiBaseUrl' "")"
    APP_ROUTING_HEALTH_PATH="$(_jq_or_default "$config_file" '.routing.healthPath' "/health")"
    APP_ROUTING_WEB_DOMAIN="$(_jq_or_default "$config_file" '.routing.webDomain' "")"
    APP_ROUTING_WEB_BASE_URL="$(_jq_or_default "$config_file" '.routing.webBaseUrl' "")"
    APP_ROUTING_WEB_HEALTH_PATH="$(_jq_or_default "$config_file" '.routing.webHealthPath' "/health")"
    APP_ROUTING_DEFAULT_SSL_MODE="$(_jq_or_default "$config_file" '.routing.sslMode' "letsencrypt")"
    APP_ROUTING_TRAEFIK_NETWORK="$(_jq_or_default "$config_file" '.routing.traefikNetwork' "traefik-public")"
    APP_ROUTING_TRAEFIK_CONSTRAINT_LABEL="$(_jq_or_default "$config_file" '.routing.traefikConstraintLabel' "traefik-public")"
    APP_ROUTING_TRAEFIK_CERT_RESOLVER="$(_jq_or_default "$config_file" '.routing.traefikCertResolver' "le")"
    APP_ROUTING_API_PUBLISHED_PORT="$(_jq_or_default "$config_file" '.routing.publishedPort' "8083")"
    APP_ROUTING_WEB_PUBLISHED_PORT="$(_jq_or_default "$config_file" '.routing.webPublishedPort' "8084")"
    APP_ROUTING_PGADMIN_PUBLISHED_PORT="$(_jq_or_default "$config_file" '.routing.pgadminPublishedPort' "5054")"
    APP_REDIRECTOR_ENABLED="$(_jq_or_default "$config_file" '.redirector.enabled' "false")"
    APP_REDIRECT_TARGET_BASE_URL="$(_jq_or_default "$config_file" '.redirector.defaultTargetBaseUrl' "")"
    APP_REDIRECT_STATUS_CODE="$(_jq_or_default "$config_file" '.redirector.statusCode' "302")"

    # Exposure metadata. Internal-only profiles (exposure.type == "internal")
    # are never given a public domain, Traefik labels, or published ports.
    APP_EXPOSURE_TYPE="$(_jq_or_default "$config_file" '.exposure.type' "public")"
    APP_EXPOSURE_TRAEFIK="$(_jq_or_default "$config_file" '.exposure.traefik' "true")"
    APP_EXPOSURE_PUBLISHED_PORTS="$(_jq_or_default "$config_file" '.exposure.publishedPorts' "true")"
    APP_INTERNAL_URL="$(_jq_or_default "$config_file" '.routing.internalUrl' "")"
    APP_INTERNAL_SERVICE="$(_jq_or_default "$config_file" '.routing.internalServiceName' "$APP_PRIMARY_SERVICE")"
    APP_INTERNAL_NETWORK="$(_jq_or_default "$config_file" '.networking.internalNetwork' "")"
    APP_INTERNAL_NETWORK_EXTERNAL="$(_jq_or_default "$config_file" '.networking.externalNetwork' "false")"
    APP_INTERNAL_NETWORK_ATTACHABLE="$(_jq_or_default "$config_file" '.networking.attachable' "false")"

    # Authentication defaults. The server URL remains the tracked credential
    # destination; executable profiles may persist validated realm/client
    # deployment selections in the ignored root environment.
    APP_AUTH_PROVIDER="$(_jq_or_default "$config_file" '.auth.provider' "none")"
    _load_keycloak_profile_defaults "$config_file"

    # Secret-handling metadata (optional). Profiles whose Docker secrets use
    # Profiles with literal, unprefixed secret names declare their own secrets
    # template and set secretsConfig.prefixed = false.
    APP_SECRETS_TEMPLATE="$(_jq_or_default "$config_file" '.secretsConfig.template' "")"
    APP_SECRETS_PREFIXED="$(_jq_or_default "$config_file" '.secretsConfig.prefixed' "true")"
    APP_SECRET_NAMES="$(jq -r '.secrets[]?' "$config_file" 2>/dev/null | tr '\n' ' ')"
    APP_OPTIONAL_SECRET_NAMES="$(jq -r '.optionalSecrets[]?' "$config_file" 2>/dev/null | tr '\n' ' ')"

    # Executable renderer metadata. Schema 5 profiles use envKeys as the exact
    # rendered environment allowlist instead of informational documentation.
    APP_RENDERER_TYPE="$(_jq_or_default "$config_file" '.renderer.type' "generic")"
    APP_RENDERER_STRICT="$(_jq_or_default "$config_file" '.renderer.strict' "false")"
    APP_RENDERER_API_TEMPLATE="$(_jq_or_default "$config_file" '.renderer.apiTemplate' "")"
    APP_RENDERER_FOOTER_TEMPLATE="$(_jq_or_default "$config_file" '.renderer.footerTemplate' "")"
    APP_ENV_KEYS="$(jq -r '.envKeys[]?' "$config_file" 2>/dev/null | tr '\n' ' ')"

    # Database requirements
    APP_DB_TYPE="$(_jq_or_default "$config_file" '.database.type' "postgresql")"
    APP_DB_DEFAULT_MODE="$(_jq_or_default "$config_file" '.database.defaultMode' "local")"
    APP_DB_ALLOWED_MODES="$(jq -r '.database.allowedModes[]?' "$config_file" 2>/dev/null | tr '\n' ' ')"
    if [ -z "$APP_DB_ALLOWED_MODES" ]; then
        if [ "$APP_DB_TYPE" = "none" ]; then
            APP_DB_ALLOWED_MODES="none"
        else
            APP_DB_ALLOWED_MODES="local external"
        fi
    fi
    local default_db_host="postgres"
    local default_db_port="5432"
    case "$APP_DB_TYPE" in
        mongodb)
            default_db_host="mongodb"
            default_db_port="27017"
            ;;
        neo4j)
            default_db_host="neo4j"
            default_db_port="7687"
            ;;
    esac
    APP_DB_DEFAULT_HOST="$(_jq_or_default "$config_file" '.environment.DB_HOST' "$default_db_host")"
    APP_DB_DEFAULT_PORT="$(_jq_or_default "$config_file" '.environment.DB_PORT // .database.port' "$default_db_port")"
    APP_DB_EXTERNAL_HOST_DEFAULT="$(_jq_or_default "$config_file" '.database.externalHostDefault' "")"
    APP_DB_EXTERNAL_PORT_DEFAULT="$(_jq_or_default "$config_file" '.database.externalPortDefault // .database.port' "$default_db_port")"
    APP_DB_DEFAULT_NAME="$(_jq_or_default "$config_file" '.environment.DB_NAME' "$APP_ID")"
    APP_DB_DEFAULT_USER="$(_jq_or_default "$config_file" '.environment.DB_USER' "$APP_ID")"
    APP_DB_PROMPT_IDENTITY="$(_jq_or_default "$config_file" '((.environment.DB_NAME? != null) or (.environment.DB_USER? != null))' "false")"

    # Service requirements
    APP_REQUIRES_REDIS="$(_jq_or_default "$config_file" '.services.redis' "true")"
    APP_REQUIRES_DATABASE="$(_jq_or_default "$config_file" '.services.database' "true")"
    APP_REQUIRES_WEB="$(_jq_or_default "$config_file" '.services.web' "false")"
    APP_SECRET_COUNT=0
    if site_profile_declares_secrets "$config_file"; then
        APP_SECRET_COUNT=1
    fi

    # Image defaults
    APP_IMAGE_NAME="$(_jq_or_default "$config_file" '.image.name' "")"
    APP_IMAGE_DEFAULT_VERSION="$(_jq_or_default "$config_file" '.image.defaultVersion' "latest")"
    APP_WEB_IMAGE_NAME="$(_jq_or_default "$config_file" '.web.image.name' "")"
    APP_WEB_IMAGE_DEFAULT_VERSION="$(_jq_or_default "$config_file" '.web.image.defaultVersion' "")"

    # Optional cross-component release coordination. Profiles without this
    # block use the highest currently configured application-image version.
    APP_RELEASE_STACK_ID="$(_jq_or_default "$config_file" '.release.stackId' "")"
    APP_RELEASE_VERSION_POLICY="$(_jq_or_default "$config_file" '.release.versionPolicy' "")"
    APP_RELEASE_VERSION_FLOOR="$(_jq_or_default "$config_file" '.release.versionFloor' "")"

    # Resource defaults
    APP_DEFAULT_REPLICAS="$(_jq_or_default "$config_file" '.resources.defaultReplicas' "1")"
    APP_DEFAULT_MEMORY_LIMIT="$(_jq_or_default "$config_file" '.resources.defaultMemoryLimit' "unlimited")"
    APP_WEB_DEFAULT_REPLICAS="$(_jq_or_default "$config_file" '.web.resources.defaultReplicas' "1")"
    APP_WEB_DEFAULT_MEMORY_LIMIT="$(_jq_or_default "$config_file" '.web.resources.defaultMemoryLimit // .resources.defaultWebMemoryLimit' "unlimited")"
    # A profile may recommend a production host path. Missing or empty storage
    # defaults remain relocatable by resolving to this deployment checkout.
    APP_DATA_ROOT="$(_jq_or_default "$config_file" '.storage.dataRoot' "$project_root")"

    # Optional database-management service metadata. New profiles declare the
    # full pgadmin object; compatibility profiles may use adminUI.
    APP_ADMIN_UI_TYPE="$(_jq_or_default "$config_file" '.adminUI.type // (if .pgadmin then "pgadmin" else "" end)' "")"
    APP_ADMIN_UI_SECRET="$(_jq_or_default "$config_file" '.adminUI.secret' "")"
    APP_ADMIN_UI_DEFAULT_DOMAIN="$(_jq_or_default "$config_file" '.pgadmin.domain' "")"
    APP_ADMIN_UI_DEFAULT_DOMAIN_PREFIX="$(_jq_or_default "$config_file" '.adminUI.defaultDomainPrefix' "admin")"
    APP_ADMIN_UI_DEFAULT_EMAIL="$(_jq_or_default "$config_file" '.pgadmin.email' "")"
    APP_ADMIN_UI_DEFAULT_ENABLED="$(_jq_or_default "$config_file" '.pgadmin.enabled' "false")"
    APP_ADMIN_UI_DEFAULT_REPLICAS="$(_jq_or_default "$config_file" '.adminUI.defaultReplicas' "0")"
    APP_ADMIN_UI_CONFIGURABLE_REPLICAS="$(_jq_or_default "$config_file" '.adminUI.configurableReplicas' "false")"

    return 0
}

# ==============================================================================
# show_app_selector
# ==============================================================================
# Displays an interactive numbered menu listing discovered app configs.
# The user selects one by number, or chooses to exit.
#
# Arguments:
#   $1 - project_root: absolute path to the repository root
#
# Output:
#   Prints the selected config ID to stdout. Prints "EXIT" to quit.
#
# Returns:
#   0 always
# ==============================================================================
show_app_selector() {
    local project_root="$1"

    local configs=()
    while IFS= read -r cid; do
        configs+=("$cid")
    done < <(discover_app_configs "$project_root")

    echo "" >&2
    echo "============================================" >&2
    echo "Select Deployment Profile" >&2
    echo "============================================" >&2
    echo "" >&2

    if [ ${#configs[@]} -eq 0 ]; then
        echo "No deployment profiles found in site-configs/." >&2
        echo "Create a JSON manifest first (see site-configs/_template.json)." >&2
        echo "" >&2
        echo "EXIT"
        return 0
    fi

    # Display available profiles once
    echo "Available deployment profiles:" >&2
    echo "" >&2

    local i
    for i in "${!configs[@]}"; do
        local cid="${configs[$i]}"
        local num=$((i + 1))
        local config_file="${project_root}/site-configs/${cid}.json"
        local display_name="$cid"
        local db_type=""

        # Read display metadata from config
        if command -v jq &>/dev/null && [ -f "$config_file" ]; then
            display_name="$(_jq_or_default "$config_file" '.name' "$cid")"
            db_type="$(_jq_or_default "$config_file" '.database.type' "")"
        fi

        local info=""
        [ -n "$db_type" ] && info=" (${db_type})"

        echo "  ${num}) ${display_name}${info}" >&2
    done

    echo "" >&2
    echo "q) Exit" >&2
    echo "" >&2

    # Loop until valid choice or explicit exit
    while true; do
        local choice
        if [[ -r /dev/tty && -t 0 ]]; then
            read -r -p "Select [1-${#configs[@]}, q]: " choice < /dev/tty
        else
            read -r -p "Select [1-${#configs[@]}, q]: " choice
        fi

        case "$choice" in
            q|Q)
                echo "EXIT"
                return 0
                ;;
            "")
                echo "Selection is required. Please enter a number (1-${#configs[@]}) or 'q' to exit." >&2
                ;;
            *)
                # Numeric selection
                if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "${#configs[@]}" ]; then
                    echo "${configs[$((choice - 1))]}"
                    return 0
                else
                    echo "Invalid choice: $choice" >&2
                    echo "Please enter a number between 1 and ${#configs[@]}, or 'q' to exit." >&2
                fi
                ;;
        esac
    done
}

# _root_env_value
# Reads one root dotenv value without evaluating shell expressions.
#
# Arguments:
#   $1 - Root `.env` file path.
#   $2 - Exact variable name.
#
# Returns:
#   0 after printing the first matching value; grep may print an empty value.
_root_env_value() {
    local env_file="$1"
    local key="$2"

    grep "^${key}=" "$env_file" 2>/dev/null |
        head -n 1 |
        cut -d'=' -f2- |
        tr -d '"' |
        tr -d '\r'
}

# _load_stack_env_fields
# Exports stack, routing, image, resource, and generic service settings.
#
# Arguments:
#   $1 - Existing root `.env` file path.
#
# Returns:
#   0 after exporting every stack-level convenience variable.
#
# Side effects:
#   Replaces process environment variables with parsed public values.
_load_stack_env_fields() {
    local env_file="$1"

    export STACK_NAME="$(_root_env_value "$env_file" STACK_NAME)"
    export STACK_FAMILY="$(_root_env_value "$env_file" STACK_FAMILY)"
    export STACK_ROLE="$(_root_env_value "$env_file" STACK_ROLE)"
    export PRIMARY_SERVICE="$(_root_env_value "$env_file" PRIMARY_SERVICE)"
    export DOMAIN="$(_root_env_value "$env_file" DOMAIN)"
    export API_URL="$DOMAIN"
    export DB_TYPE="$(_root_env_value "$env_file" DB_TYPE)"
    export DB_MODE="$(_root_env_value "$env_file" DB_MODE)"
    export PROXY_TYPE="$(_root_env_value "$env_file" PROXY_TYPE)"
    export SSL_MODE="$(_root_env_value "$env_file" SSL_MODE)"
    export TRAEFIK_NETWORK="$(_root_env_value "$env_file" TRAEFIK_NETWORK)"
    export TRAEFIK_CONSTRAINT_LABEL="$(_root_env_value "$env_file" TRAEFIK_CONSTRAINT_LABEL)"
    export TRAEFIK_CERT_RESOLVER="$(_root_env_value "$env_file" TRAEFIK_CERT_RESOLVER)"
    export IMAGE_NAME="$(_root_env_value "$env_file" IMAGE_NAME)"
    export IMAGE_VERSION="$(_root_env_value "$env_file" IMAGE_VERSION)"
    export API_REPLICAS="$(_root_env_value "$env_file" API_REPLICAS)"
    export MEMORY_LIMIT="$(_root_env_value "$env_file" MEMORY_LIMIT)"
    export DATA_ROOT="$(_root_env_value "$env_file" DATA_ROOT)"
    export API_PUBLISHED_PORT="$(_root_env_value "$env_file" API_PUBLISHED_PORT)"
    export WEB_PUBLISHED_PORT="$(_root_env_value "$env_file" WEB_PUBLISHED_PORT)"
    export PGADMIN_PUBLISHED_PORT="$(_root_env_value "$env_file" PGADMIN_PUBLISHED_PORT)"
    export INTERNAL_NETWORK="$(_root_env_value "$env_file" INTERNAL_NETWORK)"
    export SECRET_PREFIX="$(_root_env_value "$env_file" SECRETS_PREFIX)"
}

# ------------------------------------------------------------------------------
# _load_executable_keycloak_env_fields
# ------------------------------------------------------------------------------
# Reloads public Keycloak deployment selections from a generated root `.env`.
#
# Arguments:
#   $1 - Existing root `.env` file path.
#
# Returns:
#   0 after exporting all editable Keycloak deployment fields.
# ------------------------------------------------------------------------------
_load_executable_keycloak_env_fields() {
    local env_file="$1"

    export KEYCLOAK_BASE_URL="$(_root_env_value "$env_file" KEYCLOAK_BASE_URL)"
    export KEYCLOAK_ISSUER_URL="$(_root_env_value "$env_file" KEYCLOAK_ISSUER_URL)"
    export KEYCLOAK_REALM="$(_root_env_value "$env_file" KEYCLOAK_REALM)"
    export KEYCLOAK_REALM_DISPLAY_NAME="$(_root_env_value "$env_file" KEYCLOAK_REALM_DISPLAY_NAME)"
    export KEYCLOAK_REALM_ENABLED="$(_root_env_value "$env_file" KEYCLOAK_REALM_ENABLED)"
    export KEYCLOAK_REGISTRATION_ALLOWED="$(_root_env_value "$env_file" KEYCLOAK_REGISTRATION_ALLOWED)"
    export KEYCLOAK_RESET_PASSWORD_ALLOWED="$(_root_env_value "$env_file" KEYCLOAK_RESET_PASSWORD_ALLOWED)"
    export KEYCLOAK_REMEMBER_ME="$(_root_env_value "$env_file" KEYCLOAK_REMEMBER_ME)"
    export KEYCLOAK_VERIFY_EMAIL="$(_root_env_value "$env_file" KEYCLOAK_VERIFY_EMAIL)"
    export KEYCLOAK_LOGIN_WITH_EMAIL_ALLOWED="$(_root_env_value "$env_file" KEYCLOAK_LOGIN_WITH_EMAIL_ALLOWED)"
    export KEYCLOAK_BOOTSTRAP_TEST_USERS_ENABLED="$(_root_env_value "$env_file" KEYCLOAK_BOOTSTRAP_TEST_USERS_ENABLED)"
    export KEYCLOAK_AUDIENCE="$(_root_env_value "$env_file" KEYCLOAK_AUDIENCE)"
    export KEYCLOAK_FRONTEND_CLIENT_ID="$(_root_env_value "$env_file" KEYCLOAK_FRONTEND_CLIENT_ID)"
    export KEYCLOAK_BACKEND_CLIENT_ID="$(_root_env_value "$env_file" KEYCLOAK_BACKEND_CLIENT_ID)"
}

# _load_executable_env_fields
# Exports shared public app, database, Keycloak, WebApp, and pgAdmin settings.
#
# Arguments:
#   $1 - Existing root `.env` file path.
#
# Returns:
#   0 after exporting every executable-profile convenience variable.
#
# Side effects:
#   Replaces process environment variables with parsed public values.
_load_executable_env_fields() {
    local env_file="$1"

    export DEPLOYMENT_PROFILE_ID="$(_root_env_value "$env_file" DEPLOYMENT_PROFILE_ID)"
    export APP_ID="$(_root_env_value "$env_file" APP_ID)"
    export APP_ENVIRONMENT="$(_root_env_value "$env_file" APP_ENVIRONMENT)"
    export APP_PROFILE="$(_root_env_value "$env_file" APP_PROFILE)"
    export BACKEND_APP_ID="$(_root_env_value "$env_file" BACKEND_APP_ID)"
    export BACKEND_DATA_PROFILE="$(_root_env_value "$env_file" BACKEND_DATA_PROFILE)"
    export AUTH_PROVIDER="$(_root_env_value "$env_file" AUTH_PROVIDER)"
    export API_BASE_URL="$(_root_env_value "$env_file" API_BASE_URL)"
    export WEB_BASE_URL="$(_root_env_value "$env_file" WEB_BASE_URL)"
    export WEB_DOMAIN="$(_root_env_value "$env_file" WEB_DOMAIN)"
    export CORS_ORIGINS="$(_root_env_value "$env_file" CORS_ORIGINS)"
    _load_executable_keycloak_env_fields "$env_file"
    export DB_HOST="$(_root_env_value "$env_file" DB_HOST)"
    export DB_PORT="$(_root_env_value "$env_file" DB_PORT)"
    export DB_NAME="$(_root_env_value "$env_file" DB_NAME)"
    export DB_USER="$(_root_env_value "$env_file" DB_USER)"
    export PGADMIN_ENABLED="$(_root_env_value "$env_file" PGADMIN_ENABLED)"
    export PGADMIN_DOMAIN="$(_root_env_value "$env_file" PGADMIN_DOMAIN)"
    export PGADMIN_URL="$PGADMIN_DOMAIN"
    export PGADMIN_REPLICAS="$(_root_env_value "$env_file" PGADMIN_REPLICAS)"
    export PGADMIN_EMAIL="$(_root_env_value "$env_file" PGADMIN_EMAIL)"
    export WEB_ENABLED="$(_root_env_value "$env_file" WEB_ENABLED)"
    export WEB_IMAGE_NAME="$(_root_env_value "$env_file" WEB_IMAGE_NAME)"
    export WEB_IMAGE_VERSION="$(_root_env_value "$env_file" WEB_IMAGE_VERSION)"
    export WEB_REPLICAS="$(_root_env_value "$env_file" WEB_REPLICAS)"
    export WEB_MEMORY_LIMIT="$(_root_env_value "$env_file" WEB_MEMORY_LIMIT)"
}

# _load_generic_service_env_fields
# Exports legacy redirect, nginx, and Mongo Express convenience settings.
#
# Arguments:
#   $1 - Existing root `.env` file path.
#
# Returns:
#   0 after exporting generic optional-service variables.
#
# Side effects:
#   Replaces process environment variables with parsed public values.
_load_generic_service_env_fields() {
    local env_file="$1"

    export REDIRECT_TARGET_BASE_URL="$(_root_env_value "$env_file" REDIRECT_TARGET_BASE_URL)"
    export REDIRECT_STATUS_CODE="$(_root_env_value "$env_file" REDIRECT_STATUS_CODE)"
    export NGINX_REPLICAS="$(_root_env_value "$env_file" NGINX_REPLICAS)"
    export MONGO_EXPRESS_URL="$(_root_env_value "$env_file" MONGO_EXPRESS_URL)"
    export MONGO_EXPRESS_REPLICAS="$(_root_env_value "$env_file" MONGO_EXPRESS_REPLICAS)"
    export MONGO_EXPRESS_USERNAME="$(_root_env_value "$env_file" MONGO_EXPRESS_USERNAME)"
}

# ==============================================================================
# load_root_env
# ==============================================================================
# Loads the root .env file (PROJECT_ROOT/.env), exports convenience globals,
# and hydrates the matching site profile when one exists. Reloading a restored
# or wizard-updated environment therefore cannot leave stale capability data in
# the long-running quick-start menu.
#
# Arguments:
#   $1 - project_root: absolute path to the repository root
#
# Returns:
#   0 if .env exists and was loaded, 1 if .env is missing
# ==============================================================================
load_root_env() {
    local project_root="$1"
    local env_file="${project_root}/.env"
    local profile_id=""

    if [ ! -f "$env_file" ]; then
        return 1
    fi
    _load_stack_env_fields "$env_file"
    if [ -z "$DATA_ROOT" ]; then
        export DATA_ROOT="$project_root"
    fi
    _load_executable_env_fields "$env_file"
    _load_generic_service_env_fields "$env_file"
    profile_id="${DEPLOYMENT_PROFILE_ID:-${BACKEND_APP_ID:-}}"
    if [ -n "$profile_id" ]; then
        if [ ! -f "${project_root}/site-configs/${profile_id}.json" ]; then
            echo "Deployment profile is missing: ${profile_id}" >&2
            return 1
        fi
        load_app_config "$project_root" "$profile_id" || return 1
    fi
    return 0
}
