#!/bin/bash
# ==============================================================================
# menu-runtime-actions.sh - Profile-driven logging and admin-UI quick actions
# ==============================================================================
#
# Exposes common operational toggles without reopening the full setup wizard.
# Every change uses the same protected environment, render, deploy, health, and
# rollback boundary as image updates. Capabilities come from the active site
# profile and never from application-specific branches.
# ==============================================================================

# Guard against multiple sourcing.
if [ -n "${_MENU_RUNTIME_ACTIONS_LOADED:-}" ]; then
    return 0 2>/dev/null || true
fi
_MENU_RUNTIME_ACTIONS_LOADED=1

_MENU_RUNTIME_ACTIONS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${_MENU_RUNTIME_ACTIONS_DIR}/deployment-environment-format.sh"
source "${_MENU_RUNTIME_ACTIONS_DIR}/menu-image-transaction.sh"

# profile_supports_advanced_logging
# Checks whether the executable API profile exposes a LOG_LEVEL runtime field.
#
# Returns:
#   0 when the production-safe INFO/WARNING toggle is supported; otherwise 1.
profile_supports_advanced_logging() {
    [ "${APP_RENDERER_TYPE:-}" = "executable" ] &&
        [ "${APP_ADVANCED_LOGGING_LEVEL:-INFO}" = "INFO" ] &&
        [[ " ${APP_ENV_KEYS:-} " == *" LOG_LEVEL "* ]]
}

# advanced_logging_status_label
# Describes the effective production-safe application logging preset.
#
# Output:
#   Enabled INFO diagnostics or disabled WARNING-only text.
advanced_logging_status_label() {
    if [ "${ADVANCED_LOGGING_ENABLED:-true}" = "true" ]; then
        echo "enabled (INFO diagnostics)"
    else
        echo "disabled (WARNING and ERROR only)"
    fi
}

# profile_supports_database_admin_toggle
# Checks whether the selected profile can run a local database-management UI.
#
# Returns:
#   0 when a local database and profile-declared admin UI are active options.
profile_supports_database_admin_toggle() {
    [ "${DB_MODE:-none}" = "local" ] &&
        [ "${DB_TYPE:-none}" != "none" ] &&
        [ -n "${APP_ADMIN_UI_TYPE:-}" ]
}

# database_admin_display_name
# Converts the profile admin-UI type into an operator-facing product name.
#
# Output:
#   pgAdmin, Mongo Express, or the profile value.
database_admin_display_name() {
    case "${APP_ADMIN_UI_TYPE:-}" in
        pgadmin) echo "pgAdmin" ;;
        mongo-express) echo "Mongo Express" ;;
        *) echo "${APP_ADMIN_UI_TYPE:-database management}" ;;
    esac
}

# database_admin_status_label
# Describes whether the optional database-management UI is configured.
#
# Output:
#   Enabled with replica count or disabled text.
database_admin_status_label() {
    if [ "${PGADMIN_ENABLED:-false}" = "true" ]; then
        echo "enabled (replicas=${PGADMIN_REPLICAS:-1})"
    else
        echo "disabled"
    fi
}

# _run_quick_profile_update
# Applies public assignments through the shared rollback-safe transaction.
#
# Arguments:
#   $1 - Operator-facing action label.
#   Remaining arguments - Exact KEY=VALUE public assignments.
#
# Returns:
#   0 after success or a no-op; otherwise 1.
_run_quick_profile_update() {
    local action_label="$1"
    shift
    local transaction_directory=""
    local status=0

    transaction_directory="$(mktemp -d \
        "${PROJECT_ROOT}/.operator-update.XXXXXX")" || return 1
    _apply_profile_environment_update \
        "$transaction_directory" \
        "$action_label" \
        "if-running" \
        "$@" || status=$?
    _clean_release_image_transaction "$transaction_directory"
    if [ "$status" -eq 2 ]; then
        return 0
    fi
    return "$status"
}

# toggle_advanced_logging
# Toggles INFO diagnostics versus WARNING-only production logging.
#
# Returns:
#   0 after success/cancellation; otherwise 1.
#
# Side effects:
#   Updates .env, rerenders, and redeploys a running stack after confirmation.
toggle_advanced_logging() {
    local current="${ADVANCED_LOGGING_ENABLED:-true}"
    local target="true"
    local action="Enable"

    if [ "$current" = "true" ]; then
        target="false"
        action="Disable"
    fi
    echo ""
    echo "Advanced application logging"
    echo "----------------------------"
    echo "Enabled uses INFO diagnostics; disabled keeps WARNING and ERROR logs."
    echo "Sensitive HTTP bodies/headers, SQL echo, and framework DEBUG remain off."
    echo ""
    if ! prompt_yes_no "${action} advanced logging?" "Y"; then
        echo "Logging configuration unchanged."
        return 0
    fi
    _run_quick_profile_update \
        "Advanced logging ${action,,}" \
        "ADVANCED_LOGGING_ENABLED=${target}"
}

# toggle_database_admin_ui
# Enables or removes the profile-declared database-management service.
#
# Returns:
#   0 after success/cancellation; otherwise 1.
#
# Side effects:
#   Updates .env, rerenders, and redeploys a running stack after confirmation.
toggle_database_admin_ui() {
    local current="${PGADMIN_ENABLED:-false}"
    local target="true"
    local replicas="${APP_ADMIN_UI_DEFAULT_REPLICAS:-1}"
    local action="Enable"
    local display_name=""

    display_name="$(database_admin_display_name)"
    [ "$replicas" -gt 0 ] 2>/dev/null || replicas=1
    if [ "$current" = "true" ]; then
        target="false"
        replicas=0
        action="Disable"
    fi
    echo ""
    echo "Database management"
    echo "-------------------"
    echo "${display_name}: $(database_admin_status_label)"
    echo "The shared renderer and health checks will apply the selected state."
    echo ""
    if ! prompt_yes_no "${action} ${display_name}?" "Y"; then
        echo "Database-management configuration unchanged."
        return 0
    fi
    _run_quick_profile_update \
        "${display_name} ${action,,}" \
        "PGADMIN_ENABLED=${target}" \
        "PGADMIN_REPLICAS=${replicas}"
}
