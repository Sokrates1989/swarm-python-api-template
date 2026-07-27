#!/bin/bash
# ==============================================================================
# docker-secrets-menu.sh - Profile-aware Docker secret menu
# ==============================================================================
#
# Keeps generic secret creation behavior separate from the strict Felix
# candidate boundary. Felix exposes only its exact database secret and the
# existing production Keycloak ownership handoff; it never derives or manually
# accepts a backend client secret.
# ==============================================================================

# _secret_status_line
# Prints one existence result without reading or displaying the secret value.
#
# Arguments:
#   $1 - Exact Docker secret name.
#
# Returns:
#   0 when the secret exists, 1 when it is missing.
_secret_status_line() {
    local secret_name="$1"

    if docker secret inspect "$secret_name" >/dev/null 2>&1; then
        echo "[OK]      ${secret_name}"
        return 0
    fi
    echo "[MISSING] ${secret_name}"
    return 1
}

# _secret_editor
# Selects an installed terminal editor for one interactive secret value.
#
# Arguments:
#   None.
#
# Outputs:
#   The first supported editor name.
#
# Returns:
#   0 when nano, vim, or vi is available; 1 otherwise.
_secret_editor() {
    local editor

    for editor in nano vim vi; do
        if command -v "$editor" >/dev/null 2>&1; then
            printf '%s\n' "$editor"
            return 0
        fi
    done
    return 1
}

# _generic_secret_prefix
# Resolves the historical uppercase prefix for non-Felix deployments.
#
# Arguments:
#   None. Reads SECRET_PREFIX and STACK_NAME.
#
# Outputs:
#   Uppercase identifier prefix.
#
# Returns:
#   0 always.
_generic_secret_prefix() {
    printf '%s' "${SECRET_PREFIX:-$STACK_NAME}" |
        tr '[:lower:]' '[:upper:]' |
        sed 's/[^A-Z0-9]/_/g'
}

# _require_stopped_stack_for_secret_change
# Keeps generic in-use secret replacement behind an explicit stack-removal
# confirmation.
#
# Arguments:
#   None. Reads STACK_NAME.
#
# Returns:
#   0 when no stack is running or confirmed removal completes; 1 otherwise.
#
# Side effects:
#   May remove the currently selected non-Felix stack after explicit approval.
_require_stopped_stack_for_secret_change() {
    local remove_stack=""

    if ! docker stack ls --format "{{.Name}}" 2>/dev/null |
        grep -q "^${STACK_NAME}$"; then
        echo "[OK] No running stack found."
        return 0
    fi

    echo "[WARN] Stack '${STACK_NAME}' is running."
    echo "Docker secrets cannot be replaced while that stack uses them."
    if [[ -r /dev/tty ]]; then
        read -r -p "Remove stack before updating secrets? (y/N): " remove_stack < /dev/tty
    else
        read -r -p "Remove stack before updating secrets? (y/N): " remove_stack
    fi
    if [[ ! "$remove_stack" =~ ^[Yy]$ ]]; then
        echo "[INFO] Secret update cancelled."
        return 1
    fi

    docker stack rm "$STACK_NAME"
    echo "Waiting for stack removal..."
    while docker stack ls --format "{{.Name}}" 2>/dev/null |
        grep -q "^${STACK_NAME}$"; do
        sleep 2
    done
    echo "[OK] Stack removed."
    return 0
}

# _show_felix_candidate_secret_menu
# Displays exact Felix secret status and available ownership-safe actions.
#
# Arguments:
#   None.
#
# Returns:
#   0 after rendering the menu.
#
# Side effects:
#   Queries Docker secret metadata without reading secret values.
_show_felix_candidate_secret_menu() {
    echo ""
    echo "Felix candidate Docker secrets"
    echo "--------------------------------"
    _secret_status_line "FELIX_NEW_DB_PASSWORD" || true
    _secret_status_line "FELIX_NEW_KEYCLOAK_ADMIN_CLIENT_SECRET" || true
    if [ "${PGADMIN_ENABLED:-false}" = "true" ]; then
        _secret_status_line "FELIX_NEW_PGADMIN_PASSWORD" || true
    fi
    echo ""
    echo "  1) Create or replace the database password"
    echo "  2) Show production Keycloak secret owner"
    if [ "${PGADMIN_ENABLED:-false}" = "true" ]; then
        echo "  3) Create or replace the pgAdmin password"
    else
        echo "  3) pgAdmin password (disabled by deployment profile)"
    fi
    echo "  4) Refresh exact secret status"
    echo "  0) Back"
}

# _create_felix_editor_secret
# Opens the protected editor flow for one exact Felix Docker secret.
#
# Arguments:
#   $1 - Exact allowlisted Docker secret name.
#
# Returns:
#   The secret creation result, or 1 when no supported editor exists.
#
# Side effects:
#   May create or replace the selected Docker secret.
_create_felix_editor_secret() {
    local secret_name="$1"
    local editor=""

    editor="$(_secret_editor)" || {
        echo "[ERROR] Install nano, vim, or vi for secret entry."
        return 1
    }
    create_single_secret "$secret_name" "$editor"
}

# _show_felix_keycloak_secret_owner
# Delegates client-secret maintenance to the production Keycloak checkout.
#
# Arguments:
#   None.
#
# Returns:
#   The production-owner helper result, or 1 when unavailable.
_show_felix_keycloak_secret_owner() {
    if ! declare -F show_felix_production_keycloak_handoff >/dev/null; then
        echo "[ERROR] Production Keycloak ownership helper is unavailable."
        return 1
    fi
    show_felix_production_keycloak_handoff
}

# _create_enabled_pgadmin_secret
# Creates the optional pgAdmin password only for an enabled profile.
#
# Arguments:
#   None.
#
# Returns:
#   The protected editor flow result, or 1 when pgAdmin is disabled.
#
# Side effects:
#   May create or replace FELIX_NEW_PGADMIN_PASSWORD.
_create_enabled_pgadmin_secret() {
    if [ "${PGADMIN_ENABLED:-false}" != "true" ]; then
        echo "[INFO] Enable pgAdmin in the Felix setup wizard first."
        return 1
    fi
    _create_felix_editor_secret "FELIX_NEW_PGADMIN_PASSWORD"
}

# _manage_felix_candidate_secrets
# Manages exact Felix backend, Keycloak, and optional pgAdmin boundaries.
#
# Arguments:
#   None.
#
# Returns:
#   0 after returning to the main menu.
#
# Side effects:
#   May create/recreate Felix database or enabled pgAdmin passwords. The
#   Keycloak owner action is informational and never accepts a secret value.
_manage_felix_candidate_secrets() {
    local choice=""

    while true; do
        _show_felix_candidate_secret_menu
        read -r -p "Felix secret choice (0-4): " choice
        case "$choice" in
            1) _create_felix_editor_secret "FELIX_NEW_DB_PASSWORD" || true ;;
            2) _show_felix_keycloak_secret_owner || true ;;
            3) _create_enabled_pgadmin_secret || true ;;
            4) ;;
            0) return 0 ;;
            *) echo "[WARN] Enter a value from 0 through 4." ;;
        esac
    done
}

# _manage_generic_docker_secrets
# Preserves the historical prefixed secret workflow for non-Felix profiles.
#
# Arguments:
#   None.
#
# Returns:
#   0 after one action or returning to the main menu.
#
# Side effects:
#   May create generic Docker secrets or remove a confirmed running stack.
_manage_generic_docker_secrets() {
    local prefix_upper
    local choice=""
    local db_password_secret
    local admin_api_key_secret
    local backup_restore_api_key_secret
    local backup_delete_api_key_secret

    prefix_upper="$(_generic_secret_prefix)"
    db_password_secret="${prefix_upper}_DB_PASSWORD"
    admin_api_key_secret="${prefix_upper}_ADMIN_API_KEY"
    backup_restore_api_key_secret="${prefix_upper}_BACKUP_RESTORE_API_KEY"
    backup_delete_api_key_secret="${prefix_upper}_BACKUP_DELETE_API_KEY"

    echo ""
    echo "Generic Docker secret status (${prefix_upper}*)"
    _secret_status_line "$db_password_secret" || true
    _secret_status_line "$admin_api_key_secret" || true
    _secret_status_line "$backup_restore_api_key_secret" || true
    _secret_status_line "$backup_delete_api_key_secret" || true
    echo ""
    echo "  1) Create secrets from secrets.env file"
    echo "  2) Create secrets interactively"
    echo "  3) List all Docker secrets"
    echo "  0) Back"
    read -r -p "Secret choice (0-3): " choice

    case "$choice" in
        1)
            _require_stopped_stack_for_secret_change || return 0
            create_secrets_from_env_file \
                "secrets.env" \
                "${PROJECT_ROOT}/setup/templates/secrets.env.template" \
                "$prefix_upper"
            ;;
        2)
            _require_stopped_stack_for_secret_change || return 0
            create_docker_secrets \
                "$db_password_secret" \
                "$admin_api_key_secret" \
                "$backup_restore_api_key_secret" \
                "$backup_delete_api_key_secret"
            ;;
        3) list_docker_secrets ;;
        0) ;;
        *) echo "[WARN] Enter a value from 0 through 3." ;;
    esac
    return 0
}

# manage_docker_secrets_menu
# Routes candidate Felix to exact secret ownership and all other profiles to
# the historical generic workflow.
#
# Arguments:
#   None.
#
# Returns:
#   0 after the selected secret workflow returns.
#
# Side effects:
#   Depends on the explicitly selected child action.
manage_docker_secrets_menu() {
    echo ""
    echo "Manage Docker secrets"
    echo "====================="

    if declare -F _is_felix_candidate_profile >/dev/null &&
        _is_felix_candidate_profile; then
        _manage_felix_candidate_secrets
        return $?
    fi
    _manage_generic_docker_secrets
}
