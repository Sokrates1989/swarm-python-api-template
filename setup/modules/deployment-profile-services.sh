#!/bin/bash
# ==============================================================================
# deployment-profile-services.sh - Shared service and capability collection
# ==============================================================================
#
# Collects primary and WebApp image/resource choices, storage, optional
# database-management settings, and redirector values. Service visibility comes
# only from the loaded site profile.
#
# Dependencies:
#   - setup/modules/deployment-profile-prompts.sh
#   - _deployment_existing_value from deployment-profile-inputs.sh at runtime
# ==============================================================================

# Guard against multiple sourcing.
if [ -n "${_DEPLOYMENT_PROFILE_SERVICES_LOADED:-}" ]; then
    return 0 2>/dev/null || true
fi
_DEPLOYMENT_PROFILE_SERVICES_LOADED=1

# ------------------------------------------------------------------------------
# _collect_deployment_service
# ------------------------------------------------------------------------------
# Collects image, version, replica, and memory defaults for one service.
#
# Arguments:
#   $1 - Operator-facing service label.
#   $2 - Image variable name.
#   $3 - Image default.
#   $4 - Version variable name.
#   $5 - Version default.
#   $6 - Replica variable name.
#   $7 - Replica default.
#   $8 - Memory variable name.
#   $9 - Memory default.
#
# Returns:
#   0 after assigning all four caller-owned service fields.
# ------------------------------------------------------------------------------
_collect_deployment_service() {
    local label="$1"
    local image_variable="$2"
    local image_default="$3"
    local version_variable="$4"
    local version_default="$5"
    local replica_variable="$6"
    local replica_default="$7"
    local memory_variable="$8"
    local memory_default="$9"

    echo ""
    echo "${label} service"
    echo "----------------"
    prompt_deployment_value \
        "$image_variable" \
        "${label} image repository" \
        "$image_default" \
        "image"
    prompt_deployment_value \
        "$version_variable" \
        "${label} image version" \
        "$version_default" \
        "tag"
    prompt_deployment_value \
        "$replica_variable" \
        "${label} replicas" \
        "$replica_default" \
        "positive"
    prompt_deployment_value \
        "$memory_variable" \
        "${label} memory limit" \
        "$memory_default" \
        "memory"
}

# ------------------------------------------------------------------------------
# collect_deployment_services_and_storage
# ------------------------------------------------------------------------------
# Collects primary/additional service deployment values and the host data root.
# A profile recommendation or the checkout fallback supplies the first-run
# default; an explicit operator path is retained during reconfiguration.
#
# Returns:
#   0 after setting image, resource, WebApp, and storage globals.
# ------------------------------------------------------------------------------
collect_deployment_services_and_storage() {
    local primary_label="Backend"

    if [ "${APP_STACK_FAMILY:-api}" = "nginx" ]; then
        primary_label="Nginx"
    fi
    _collect_deployment_service \
        "$primary_label" \
        IMAGE_NAME \
        "$(_deployment_existing_value IMAGE_NAME "$APP_IMAGE_NAME")" \
        IMAGE_VERSION \
        "$(_deployment_existing_value IMAGE_VERSION "$APP_IMAGE_DEFAULT_VERSION")" \
        API_REPLICAS \
        "$(_deployment_existing_value API_REPLICAS "$APP_DEFAULT_REPLICAS")" \
        MEMORY_LIMIT \
        "$(_deployment_existing_value MEMORY_LIMIT "$APP_DEFAULT_MEMORY_LIMIT")"

    if [ "${APP_STACK_FAMILY:-api}" = "nginx" ]; then
        NGINX_REPLICAS="$API_REPLICAS"
    fi

    WEB_ENABLED="${APP_REQUIRES_WEB:-false}"
    WEB_IMAGE_NAME=""
    WEB_IMAGE_VERSION=""
    WEB_REPLICAS="1"
    WEB_MEMORY_LIMIT="${APP_WEB_DEFAULT_MEMORY_LIMIT:-unlimited}"
    if [ "$WEB_ENABLED" = "true" ]; then
        _collect_deployment_service \
            "WebApp" \
            WEB_IMAGE_NAME \
            "$(_deployment_existing_value WEB_IMAGE_NAME "$APP_WEB_IMAGE_NAME")" \
            WEB_IMAGE_VERSION \
            "$(_deployment_existing_value WEB_IMAGE_VERSION "$APP_WEB_IMAGE_DEFAULT_VERSION")" \
            WEB_REPLICAS \
            "$(_deployment_existing_value WEB_REPLICAS "$APP_WEB_DEFAULT_REPLICAS")" \
            WEB_MEMORY_LIMIT \
            "$(_deployment_existing_value WEB_MEMORY_LIMIT "$APP_WEB_DEFAULT_MEMORY_LIMIT")"
    fi

    prompt_deployment_value \
        DATA_ROOT \
        "Host data root" \
        "$(_deployment_existing_value DATA_ROOT "$APP_DATA_ROOT")" \
        "path"
}

# ------------------------------------------------------------------------------
# collect_deployment_database_management
# ------------------------------------------------------------------------------
# Collects the profile-declared optional database-management service.
#
# Returns:
#   0 after setting pgAdmin or Mongo Express globals.
# ------------------------------------------------------------------------------
collect_deployment_database_management() {
    local default_enabled="${APP_ADMIN_UI_DEFAULT_ENABLED:-false}"
    local default_domain=""
    local default_domain_prefix="${APP_ADMIN_UI_DEFAULT_DOMAIN_PREFIX:-admin}"
    local enabled_replicas="${APP_ADMIN_UI_DEFAULT_REPLICAS:-0}"

    PGADMIN_ENABLED="false"
    PGADMIN_REPLICAS="0"
    PGADMIN_DOMAIN="${APP_ADMIN_UI_DEFAULT_DOMAIN:-}"
    PGADMIN_EMAIL="${APP_ADMIN_UI_DEFAULT_EMAIL:-}"
    MONGO_EXPRESS_URL=""
    MONGO_EXPRESS_USERNAME=""
    MONGO_EXPRESS_REPLICAS="0"
    if [ "$DB_MODE" != "local" ] || [ -z "${APP_ADMIN_UI_TYPE:-}" ]; then
        return 0
    fi

    if [ "${APP_ADMIN_UI_DEFAULT_REPLICAS:-0}" -gt 0 ] 2>/dev/null; then
        default_enabled="true"
    fi
    default_enabled="$(_deployment_existing_value \
        PGADMIN_ENABLED \
        "$default_enabled")"
    prompt_deployment_toggle \
        PGADMIN_ENABLED \
        "Database management" \
        "$default_enabled" \
        "Include ${APP_ADMIN_UI_TYPE} in this stack"
    if [ "$PGADMIN_ENABLED" != "true" ]; then
        return 0
    fi

    default_domain="${APP_ADMIN_UI_DEFAULT_DOMAIN:-${default_domain_prefix}.${DOMAIN}}"
    if [ "$enabled_replicas" -lt 1 ] 2>/dev/null; then
        enabled_replicas=1
    fi
    if [ "${APP_ADMIN_UI_CONFIGURABLE_REPLICAS:-false}" = "true" ]; then
        prompt_deployment_value \
            PGADMIN_REPLICAS \
            "Database-management replicas" \
            "$(_deployment_existing_value \
                PGADMIN_REPLICAS \
                "$enabled_replicas")" \
            "positive"
        enabled_replicas="$PGADMIN_REPLICAS"
    fi
    if [ "$APP_ADMIN_UI_TYPE" = "pgadmin" ]; then
        prompt_deployment_value \
            PGADMIN_DOMAIN \
            "pgAdmin domain" \
            "$(_deployment_existing_value PGADMIN_DOMAIN "$default_domain")" \
            "domain"
        prompt_deployment_value \
            PGADMIN_EMAIL \
            "pgAdmin login email" \
            "$(_deployment_existing_value \
                PGADMIN_EMAIL \
                "${APP_ADMIN_UI_DEFAULT_EMAIL:-admin@${DOMAIN}}")" \
            "email"
        PGADMIN_REPLICAS="$enabled_replicas"
    elif [ "$APP_ADMIN_UI_TYPE" = "mongo-express" ]; then
        prompt_deployment_value \
            MONGO_EXPRESS_URL \
            "Mongo Express domain" \
            "$(_deployment_existing_value MONGO_EXPRESS_URL "$default_domain")" \
            "domain"
        prompt_deployment_value \
            MONGO_EXPRESS_USERNAME \
            "Mongo Express username" \
            "$(_deployment_existing_value MONGO_EXPRESS_USERNAME "dbadmin")" \
            "identifier"
        MONGO_EXPRESS_REPLICAS="$enabled_replicas"
    fi
    if [ "$PROXY_TYPE" = "none" ]; then
        prompt_deployment_value \
            PGADMIN_PUBLISHED_PORT \
            "Published database-management port" \
            "$PGADMIN_PUBLISHED_PORT" \
            "port"
    fi
}

# ------------------------------------------------------------------------------
# collect_deployment_redirector
# ------------------------------------------------------------------------------
# Collects redirect target and status only for profiles declaring the capability.
#
# Returns:
#   0 after setting redirector globals.
# ------------------------------------------------------------------------------
collect_deployment_redirector() {
    REDIRECT_TARGET_BASE_URL="$(_deployment_existing_value \
        REDIRECT_TARGET_BASE_URL \
        "${APP_REDIRECT_TARGET_BASE_URL:-}")"
    REDIRECT_STATUS_CODE="$(_deployment_existing_value \
        REDIRECT_STATUS_CODE \
        "${APP_REDIRECT_STATUS_CODE:-302}")"
    if [ "${APP_REDIRECTOR_ENABLED:-false}" != "true" ] &&
        [ "${APP_STACK_ROLE:-}" != "redirector" ]; then
        return 0
    fi

    echo ""
    echo "Redirector service"
    echo "------------------"
    prompt_deployment_value \
        REDIRECT_TARGET_BASE_URL \
        "Redirect target base URL" \
        "$REDIRECT_TARGET_BASE_URL" \
        "url"
    prompt_deployment_value \
        REDIRECT_STATUS_CODE \
        "Redirect status code" \
        "$REDIRECT_STATUS_CODE" \
        "integer"
}
