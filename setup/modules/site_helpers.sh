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
#   - site-configs/<appId>.json files following v3 schema
#   - Root .env file (optional, for running context)
#
# Exported Globals (set by load_app_config):
#   APP_CONFIG_FILE, APP_ID, APP_NAME, APP_DESCRIPTION,
#   APP_KIND, APP_STACK_FAMILY, APP_STACK_ROLE, APP_PRIMARY_SERVICE,
#   APP_ROUTING_CONTAINER_PORT, APP_DB_TYPE, APP_DB_DEFAULT_MODE,
#   APP_REQUIRES_REDIS, APP_REQUIRES_DATABASE, APP_SECRET_COUNT,
#   APP_IMAGE_NAME, APP_IMAGE_DEFAULT_VERSION,
#   APP_DEFAULT_REPLICAS, APP_DEFAULT_MEMORY_LIMIT,
#   APP_EXPOSURE_TYPE, APP_INTERNAL_URL, APP_INTERNAL_SERVICE,
#   APP_INTERNAL_NETWORK, APP_SECRETS_TEMPLATE, APP_SECRETS_PREFIXED,
#   APP_SECRET_NAMES, APP_OPTIONAL_SECRET_NAMES, APP_ENV_KEYS,
#   APP_RENDERER_TYPE, APP_RENDERER_STRICT
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
    APP_STACK_FAMILY="$(_jq_or_default "$config_file" '.stack.family' "$APP_KIND")"
    APP_STACK_ROLE="$(_jq_or_default "$config_file" '.stack.role' "api")"
    APP_PRIMARY_SERVICE="$(_jq_or_default "$config_file" '.stack.primaryService' "api")"
    APP_ROUTING_CONTAINER_PORT="$(_jq_or_default "$config_file" '.routing.containerPort' "8080")"
    APP_REDIRECTOR_ENABLED="$(_jq_or_default "$config_file" '.redirector.enabled' "false")"
    APP_REDIRECT_TARGET_BASE_URL="$(_jq_or_default "$config_file" '.redirector.defaultTargetBaseUrl' "")"
    APP_REDIRECT_STATUS_CODE="$(_jq_or_default "$config_file" '.redirector.statusCode' "302")"

    # Exposure metadata. Internal-only profiles (exposure.type == "internal")
    # are never given a public domain, Traefik labels, or published ports.
    APP_EXPOSURE_TYPE="$(_jq_or_default "$config_file" '.exposure.type' "public")"
    APP_INTERNAL_URL="$(_jq_or_default "$config_file" '.routing.internalUrl' "")"
    APP_INTERNAL_SERVICE="$(_jq_or_default "$config_file" '.routing.internalServiceName' "$APP_PRIMARY_SERVICE")"
    APP_INTERNAL_NETWORK="$(_jq_or_default "$config_file" '.networking.internalNetwork' "")"

    # Secret-handling metadata (optional). Profiles whose Docker secrets use
    # literal, unprefixed names (e.g. secure_messaging) declare their own
    # secrets template and set secretsConfig.prefixed = false.
    APP_SECRETS_TEMPLATE="$(_jq_or_default "$config_file" '.secretsConfig.template' "")"
    APP_SECRETS_PREFIXED="$(_jq_or_default "$config_file" '.secretsConfig.prefixed' "true")"
    APP_SECRET_NAMES="$(jq -r '.secrets[]?' "$config_file" 2>/dev/null | tr '\n' ' ')"
    APP_OPTIONAL_SECRET_NAMES="$(jq -r '.optionalSecrets[]?' "$config_file" 2>/dev/null | tr '\n' ' ')"

    # Executable renderer metadata. Schema 4 profiles use envKeys as the exact
    # rendered environment allowlist instead of informational documentation.
    APP_RENDERER_TYPE="$(_jq_or_default "$config_file" '.renderer.type' "generic")"
    APP_RENDERER_STRICT="$(_jq_or_default "$config_file" '.renderer.strict' "false")"
    APP_ENV_KEYS="$(jq -r '.envKeys[]?' "$config_file" 2>/dev/null | tr '\n' ' ')"

    # Database requirements
    APP_DB_TYPE="$(_jq_or_default "$config_file" '.database.type' "postgresql")"
    APP_DB_DEFAULT_MODE="$(_jq_or_default "$config_file" '.database.defaultMode' "local")"

    # Service requirements
    APP_REQUIRES_REDIS="$(_jq_or_default "$config_file" '.services.redis' "true")"
    APP_REQUIRES_DATABASE="$(_jq_or_default "$config_file" '.services.database' "true")"
    APP_SECRET_COUNT="$(_jq_or_default "$config_file" '.secrets | length' "0")"

    # Image defaults
    APP_IMAGE_NAME="$(_jq_or_default "$config_file" '.image.name' "")"
    APP_IMAGE_DEFAULT_VERSION="$(_jq_or_default "$config_file" '.image.defaultVersion' "latest")"

    # Resource defaults
    APP_DEFAULT_REPLICAS="$(_jq_or_default "$config_file" '.resources.defaultReplicas' "1")"
    APP_DEFAULT_MEMORY_LIMIT="$(_jq_or_default "$config_file" '.resources.defaultMemoryLimit' "512M")"

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

# ==============================================================================
# load_root_env
# ==============================================================================
# Loads the root .env file (PROJECT_ROOT/.env) and exports convenience
# globals used by menu_handlers, deploy-stack, and other modules.
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

    if [ ! -f "$env_file" ]; then
        return 1
    fi

    # Read key values from .env (simple grep-based, no eval for safety)
    _env_val() {
        grep "^${1}=" "$env_file" 2>/dev/null | head -n 1 | cut -d'=' -f2- | tr -d '"' | tr -d '\r'
    }

    export STACK_NAME="$(_env_val STACK_NAME)"
    export STACK_FAMILY="$(_env_val STACK_FAMILY)"
    export STACK_ROLE="$(_env_val STACK_ROLE)"
    export PRIMARY_SERVICE="$(_env_val PRIMARY_SERVICE)"
    export DOMAIN="$(_env_val DOMAIN)"
    export API_URL="$DOMAIN"
    export DB_TYPE="$(_env_val DB_TYPE)"
    export DB_MODE="$(_env_val DB_MODE)"
    export PROXY_TYPE="$(_env_val PROXY_TYPE)"
    export SSL_MODE="$(_env_val SSL_MODE)"
    export TRAEFIK_NETWORK="$(_env_val TRAEFIK_NETWORK)"
    export IMAGE_NAME="$(_env_val IMAGE_NAME)"
    export IMAGE_VERSION="$(_env_val IMAGE_VERSION)"
    export REDIRECT_TARGET_BASE_URL="$(_env_val REDIRECT_TARGET_BASE_URL)"
    export REDIRECT_STATUS_CODE="$(_env_val REDIRECT_STATUS_CODE)"
    export API_REPLICAS="$(_env_val API_REPLICAS)"
    export NGINX_REPLICAS="$(_env_val NGINX_REPLICAS)"
    export MEMORY_LIMIT="$(_env_val MEMORY_LIMIT)"
    export SECRET_PREFIX="$(_env_val SECRETS_PREFIX)"
    export DEPLOYMENT_PROFILE_ID="$(_env_val DEPLOYMENT_PROFILE_ID)"
    export APP_ID="$(_env_val APP_ID)"
    export APP_ENVIRONMENT="$(_env_val APP_ENVIRONMENT)"
    export APP_PROFILE="$(_env_val APP_PROFILE)"
    export BACKEND_APP_ID="$(_env_val BACKEND_APP_ID)"
    export BACKEND_DATA_PROFILE="$(_env_val BACKEND_DATA_PROFILE)"
    export AUTH_PROVIDER="$(_env_val AUTH_PROVIDER)"
    export API_BASE_URL="$(_env_val API_BASE_URL)"
    export CORS_ORIGINS="$(_env_val CORS_ORIGINS)"
    export KEYCLOAK_BASE_URL="$(_env_val KEYCLOAK_BASE_URL)"
    export KEYCLOAK_ISSUER_URL="$(_env_val KEYCLOAK_ISSUER_URL)"
    export KEYCLOAK_REALM="$(_env_val KEYCLOAK_REALM)"
    export KEYCLOAK_AUDIENCE="$(_env_val KEYCLOAK_AUDIENCE)"
    export KEYCLOAK_FRONTEND_CLIENT_ID="$(_env_val KEYCLOAK_FRONTEND_CLIENT_ID)"
    export DATA_ROOT="$(_env_val DATA_ROOT)"
    export PGADMIN_URL="$(_env_val PGADMIN_URL)"
    export PGADMIN_REPLICAS="$(_env_val PGADMIN_REPLICAS)"
    export PGADMIN_EMAIL="$(_env_val PGADMIN_EMAIL)"
    export MONGO_EXPRESS_URL="$(_env_val MONGO_EXPRESS_URL)"
    export MONGO_EXPRESS_REPLICAS="$(_env_val MONGO_EXPRESS_REPLICAS)"
    export MONGO_EXPRESS_USERNAME="$(_env_val MONGO_EXPRESS_USERNAME)"

    unset -f _env_val
    return 0
}
