#!/bin/bash
# ==============================================================================
# menu-configuration-actions.sh - Shared operations-menu reconfiguration
# ==============================================================================
#
# Reopens the one site-config-driven setup dialogue for image, replica,
# database-management, or general configuration changes. Public environment
# globals are reloaded even if a later post-configuration action fails after
# writing valid artifacts.
#
# Dependencies:
#   - setup/setup-wizard.sh
#   - load_root_env from site_helpers.sh
# ==============================================================================

# Guard against multiple sourcing.
if [ -n "${_MENU_CONFIGURATION_ACTIONS_LOADED:-}" ]; then
    return 0 2>/dev/null || true
fi
_MENU_CONFIGURATION_ACTIONS_LOADED=1

# _run_shared_reconfiguration
# Reopens the profile-independent setup dialogue and reloads the resulting
# public environment.
#
# Arguments:
#   $1 - Operator-facing reason for reconfiguration.
#
# Returns:
#   Setup action status, unless the generated environment cannot be reloaded.
_run_shared_reconfiguration() {
    local reason="$1"
    local setup_status=0

    echo "[CONFIG] ${reason}"
    echo ""
    "${PROJECT_ROOT:-.}/setup/setup-wizard.sh" || setup_status=$?
    if [ -f "${PROJECT_ROOT:-.}/.env" ]; then
        load_root_env "${PROJECT_ROOT:-.}" || return 1
    fi
    return "$setup_status"
}
