#!/bin/bash
# ==============================================================================
# legacy-profile-environment.sh - Schema-3 compatibility environment writer
# ==============================================================================
#
# Persists the normalized answers collected by deployment-profile-inputs.sh in
# the historical root .env format consumed by compose-module renderers. It owns
# no terminal interaction and contains no application-specific identity.
#
# Dependencies:
#   - setup/modules/deployment-profile-inputs.sh
# ==============================================================================

# Guard against multiple sourcing.
if [ -n "${_LEGACY_PROFILE_ENVIRONMENT_LOADED:-}" ]; then
    return 0 2>/dev/null || true
fi
_LEGACY_PROFILE_ENVIRONMENT_LOADED=1

# ------------------------------------------------------------------------------
# _write_legacy_database_environment
# ------------------------------------------------------------------------------
# Appends database-specific compatibility fields to the root environment.
#
# Arguments:
#   $1 - Destination environment path.
#
# Returns:
#   0 after appending applicable fields.
# ------------------------------------------------------------------------------
_write_legacy_database_environment() {
    local destination="$1"
    local normalized_stack="${STACK_NAME//-/_}"

    if [ "$DB_TYPE" = "postgresql" ]; then
        {
            echo "DB_HOST=${DB_HOST:-${STACK_NAME}_postgres}"
            echo "DB_PORT=${DB_PORT:-5432}"
            echo "DB_NAME=${DB_NAME:-${normalized_stack}_db}"
            echo "DB_USER=${DB_USER:-${normalized_stack}_user}"
            echo "POSTGRES_HOST=${DB_HOST:-${STACK_NAME}_postgres}"
            echo "POSTGRES_PORT=${DB_PORT:-5432}"
            echo "POSTGRES_DB=${DB_NAME:-${normalized_stack}_db}"
            echo "POSTGRES_USER=${DB_USER:-${normalized_stack}_user}"
            if [ "$DB_MODE" = "local" ]; then
                echo "POSTGRES_PASSWORD_FILE=/run/secrets/${SECRET_PREFIX}_db_password"
                echo "POSTGRES_REPLICAS=1"
            fi
        } >> "$destination"
    elif [ "$DB_TYPE" = "mongodb" ]; then
        {
            echo "MONGODB_HOST=${DB_HOST:-mongodb}"
            echo "MONGODB_PORT=${DB_PORT:-27017}"
            echo "MONGODB_DB=${DB_NAME:-${normalized_stack}_db}"
            echo "MONGODB_USER=${DB_USER:-${normalized_stack}_user}"
            if [ "$DB_MODE" = "local" ]; then
                echo "MONGODB_PASSWORD_FILE=/run/secrets/${SECRET_PREFIX}_db_password"
            fi
        } >> "$destination"
    elif [ "$DB_TYPE" = "neo4j" ]; then
        {
            echo "NEO4J_HOST=${DB_HOST:-neo4j}"
            echo "NEO4J_PORT=${DB_PORT:-7687}"
            if [ "$DB_MODE" = "local" ]; then
                echo "NEO4J_AUTH_FILE=/run/secrets/${SECRET_PREFIX}_db_password"
            fi
        } >> "$destination"
    fi
}

# ------------------------------------------------------------------------------
# _legacy_environment_admin_secret_name
# ------------------------------------------------------------------------------
# Derives the exact prefixed Docker secret used by an enabled schema-3 admin UI.
#
# Output:
#   Uppercase Docker secret identifier.
#
# Returns:
#   0 when the profile declares a safe admin secret suffix; otherwise 1.
# ------------------------------------------------------------------------------
_legacy_environment_admin_secret_name() {
    local secret_suffix="${APP_ADMIN_UI_SECRET:-}"

    if [[ ! "$secret_suffix" =~ ^[A-Z0-9_]+$ ]]; then
        echo "[ERROR] Enabled admin UI requires a safe adminUI.secret suffix." >&2
        return 1
    fi
    printf '%s_%s' "$SECRET_PREFIX" "$secret_suffix" |
        tr '[:lower:]' '[:upper:]' |
        sed 's/[^A-Z0-9]/_/g'
}

# ------------------------------------------------------------------------------
# _write_legacy_admin_environment
# ------------------------------------------------------------------------------
# Appends profile-declared database-management service values.
#
# Arguments:
#   $1 - Destination environment path.
#
# Returns:
#   0 after appending applicable fields.
# ------------------------------------------------------------------------------
_write_legacy_admin_environment() {
    local destination="$1"
    local admin_secret_name=""

    if [ -z "${APP_ADMIN_UI_TYPE:-}" ] || [ "$DB_MODE" != "local" ]; then
        return 0
    fi
    {
        echo ""
        echo "# Database management"
        echo "PGADMIN_ENABLED=${PGADMIN_ENABLED:-false}"
        echo "PGADMIN_PUBLISHED_PORT=${PGADMIN_PUBLISHED_PORT:-5054}"
    } >> "$destination"
    if [ "${PGADMIN_ENABLED:-false}" != "true" ]; then
        return 0
    fi
    admin_secret_name="$(_legacy_environment_admin_secret_name)" || return 1
    if [ "$APP_ADMIN_UI_TYPE" = "pgadmin" ]; then
        {
            echo "PGADMIN_URL=${PGADMIN_DOMAIN}"
            echo "PGADMIN_DOMAIN=${PGADMIN_DOMAIN}"
            echo "PGADMIN_REPLICAS=${PGADMIN_REPLICAS:-0}"
            echo "PGADMIN_EMAIL=${PGADMIN_EMAIL}"
            echo "PGADMIN_PASSWORD_FILE=/run/secrets/${admin_secret_name}"
        } >> "$destination"
    elif [ "$APP_ADMIN_UI_TYPE" = "mongo-express" ]; then
        {
            echo "MONGO_EXPRESS_URL=${MONGO_EXPRESS_URL}"
            echo "MONGO_EXPRESS_REPLICAS=${MONGO_EXPRESS_REPLICAS:-0}"
            echo "MONGO_EXPRESS_USERNAME=${MONGO_EXPRESS_USERNAME}"
            echo "MONGO_EXPRESS_USER=${MONGO_EXPRESS_USERNAME}"
            echo "MONGO_EXPRESS_PASSWORD_FILE=/run/secrets/${admin_secret_name}"
        } >> "$destination"
    fi
}

# ------------------------------------------------------------------------------
# _write_legacy_routing_environment
# ------------------------------------------------------------------------------
# Appends public or internal routing values for the selected profile.
#
# Arguments:
#   $1 - Destination environment path.
#
# Returns:
#   0 after appending routing fields.
# ------------------------------------------------------------------------------
_write_legacy_routing_environment() {
    local destination="$1"

    {
        echo ""
        echo "# Routing"
        echo "PROXY_TYPE=${PROXY_TYPE}"
        echo "API_BASE_URL=${API_BASE_URL}"
        echo "API_PUBLISHED_PORT=${API_PUBLISHED_PORT:-}"
        echo "PUBLISHED_PORT=${API_PUBLISHED_PORT:-}"
    } >> "$destination"
    if [ "$APP_IS_INTERNAL" = "true" ]; then
        {
            echo "INTERNAL_URL=${DOMAIN}"
            echo "INTERNAL_NETWORK=${INTERNAL_NETWORK}"
        } >> "$destination"
        return 0
    fi
    if [ "$PROXY_TYPE" = "traefik" ]; then
        {
            echo "SSL_MODE=${SSL_MODE}"
            echo "TRAEFIK_NETWORK=${TRAEFIK_NETWORK}"
            echo "TRAEFIK_CONSTRAINT_LABEL=${TRAEFIK_CONSTRAINT_LABEL}"
            echo "TRAEFIK_CERT_RESOLVER=${TRAEFIK_CERT_RESOLVER}"
            echo "TRAEFIK_ROUTER_NAME=${STACK_NAME}"
            echo "TRAEFIK_RULE='Host(\`${DOMAIN}\`)'"
            echo "TRAEFIK_ENTRYPOINT=websecure"
            if [ "$SSL_MODE" = "letsencrypt" ]; then
                echo "TRAEFIK_TLS_CERTRESOLVER=${TRAEFIK_CERT_RESOLVER}"
            fi
        } >> "$destination"
    else
        {
            echo "SSL_MODE="
            echo "TRAEFIK_NETWORK="
            echo "TRAEFIK_CONSTRAINT_LABEL="
        } >> "$destination"
    fi
}

# ------------------------------------------------------------------------------
# _write_legacy_service_environment
# ------------------------------------------------------------------------------
# Appends primary service, optional Redis, redirector, image, and resource data.
#
# Arguments:
#   $1 - Destination environment path.
#
# Returns:
#   0 after appending service fields.
# ------------------------------------------------------------------------------
_write_legacy_service_environment() {
    local destination="$1"

    if [ "${APP_REDIRECTOR_ENABLED:-false}" = "true" ] ||
        [ "${APP_STACK_ROLE:-}" = "redirector" ]; then
        {
            echo ""
            echo "# Redirector"
            echo "REDIRECT_TARGET_BASE_URL=${REDIRECT_TARGET_BASE_URL}"
            echo "REDIRECT_STATUS_CODE=${REDIRECT_STATUS_CODE}"
        } >> "$destination"
    fi
    if [ "${APP_REQUIRES_REDIS:-true}" = "true" ] &&
        [ "${APP_STACK_FAMILY:-api}" != "nginx" ]; then
        {
            echo ""
            echo "# Redis"
            echo "REDIS_HOST=redis"
            echo "REDIS_PORT=6379"
            echo "REDIS_REPLICAS=1"
            echo "REDIS_URL=redis://redis:6379/0"
        } >> "$destination"
    fi
    {
        echo ""
        echo "# Primary service"
        echo "PORT=${APP_ROUTING_CONTAINER_PORT:-8080}"
        if [ "${APP_STACK_FAMILY:-api}" != "nginx" ]; then
            echo "API_URL=${DOMAIN}"
            echo "PYTHON_VERSION=3.11"
            echo "DEBUG=false"
        fi
        echo ""
        echo "# Docker image"
        echo "IMAGE_NAME=${IMAGE_NAME}"
        echo "IMAGE_VERSION=${IMAGE_VERSION}"
        echo ""
        echo "# Resources"
        echo "API_REPLICAS=${API_REPLICAS}"
        echo "NGINX_REPLICAS=${NGINX_REPLICAS:-$API_REPLICAS}"
        echo "MEMORY_LIMIT=${MEMORY_LIMIT}"
        echo ""
        echo "# Data"
        echo "DATA_ROOT=${DATA_ROOT}"
    } >> "$destination"
}

# ------------------------------------------------------------------------------
# write_legacy_profile_environment
# ------------------------------------------------------------------------------
# Writes one complete schema-3 compatibility root environment atomically enough
# for the local setup process: a temporary sibling is populated then renamed.
#
# Returns:
#   0 after replacing root .env; otherwise nonzero.
#
# Side effects:
#   Replaces the ignored root .env file.
# ------------------------------------------------------------------------------
write_legacy_profile_environment() {
    local destination="${PROJECT_ROOT}/.env"
    local temporary="${PROJECT_ROOT}/.deployment-env.$$"

    {
        echo "# Generated by the shared site-config setup wizard."
        echo "# Deployment profile: ${APP_CONFIG_ID}"
        echo ""
        echo "# Deployment identity"
        echo "DEPLOYMENT_PROFILE_ID=${APP_CONFIG_ID}"
        echo "STACK_NAME=${STACK_NAME}"
        echo "DOMAIN=${DOMAIN}"
        echo "APP_ID=${APP_ID}"
        echo "BACKEND_APP_ID=${APP_ID}"
        echo "STACK_FAMILY=${APP_STACK_FAMILY:-api}"
        echo "STACK_ROLE=${APP_STACK_ROLE:-api}"
        echo "PRIMARY_SERVICE=${APP_PRIMARY_SERVICE:-api}"
        echo ""
        echo "# Database"
        echo "DB_TYPE=${DB_TYPE}"
        echo "DB_MODE=${DB_MODE}"
    } > "$temporary"

    _write_legacy_database_environment "$temporary"
    _write_legacy_admin_environment "$temporary"
    _write_legacy_service_environment "$temporary"
    _write_legacy_routing_environment "$temporary"
    if [ "${SECRETS_REQUIRED:-false}" = "true" ]; then
        {
            echo ""
            echo "# Docker secret identifiers"
            echo "SECRETS_PREFIX=${SECRET_PREFIX}"
        } >> "$temporary"
    fi
    mv -f "$temporary" "$destination"
    echo "Generated public deployment environment: ${destination}"
}
