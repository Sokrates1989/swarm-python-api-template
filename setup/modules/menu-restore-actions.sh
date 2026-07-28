#!/bin/bash
# ==============================================================================
# menu-restore-actions.sh - Safe deployment configuration restore actions
# ==============================================================================
#
# Restores public deployment configuration and profile secret files from the
# operations menu. Environment restore is transactional with respect to the
# active render target: an existing stack artifact is retained as a timestamped
# backup and the selected profile is rendered immediately.
#
# Dependencies:
#   - load_root_env from site_helpers.sh
#   - create_profile_secrets_from_env_file from docker-secrets-menu.sh
# ==============================================================================

# Guard against multiple sourcing.
if [ -n "${_MENU_RESTORE_ACTIONS_LOADED:-}" ]; then
    return 0 2>/dev/null || true
fi
_MENU_RESTORE_ACTIONS_LOADED=1

# ------------------------------------------------------------------------------
# _restore_and_load_environment
# ------------------------------------------------------------------------------
# Activates one saved environment and restores the prior root file when profile
# loading rejects it.
#
# Arguments:
#   $1 - Project root.
#   $2 - Saved environment path.
#   $3 - Backup timestamp.
#
# Returns:
#   load_root_env status after activation.
#
# Side effects:
#   Replaces or rolls back root .env and may retain an invalid first-time file.
# ------------------------------------------------------------------------------
_restore_and_load_environment() {
    local project_root="$1"
    local saved_env_path="$2"
    local timestamp="$3"
    local env_file="${project_root}/.env"
    local env_backup=""

    if [ -f "$env_file" ]; then
        env_backup="${env_file}.backup.${timestamp}"
        cp "$env_file" "$env_backup"
        echo "[OK] Backed up existing .env to: ${env_backup}"
    fi
    cp "$saved_env_path" "$env_file"
    if load_root_env "$project_root"; then
        return 0
    fi
    if [ -n "$env_backup" ]; then
        cp "$env_backup" "$env_file"
        load_root_env "$project_root" || true
    else
        mv "$env_file" "${env_file}.invalid.${timestamp}"
    fi
    echo "[ERROR] Saved environment was rejected; prior state was retained."
    return 1
}

# ------------------------------------------------------------------------------
# _rollback_restored_artifacts
# ------------------------------------------------------------------------------
# Removes a failed render from active use and restores the prior public
# environment and stack artifact when they existed.
#
# Arguments:
#   $1 - Project root.
#   $2 - Backup timestamp.
#   $3 - Previous stack backup path, or empty.
#
# Returns:
#   0 after restoring the last consistent state.
#
# Side effects:
#   Moves failed artifacts aside and copies retained backups into active paths.
# ------------------------------------------------------------------------------
_rollback_restored_artifacts() {
    local project_root="$1"
    local timestamp="$2"
    local stack_backup="${3:-}"
    local env_file="${project_root}/.env"
    local stack_file="${project_root}/swarm-stack.yml"
    local env_backup="${env_file}.backup.${timestamp}"

    if [ -f "$stack_file" ]; then
        mv "$stack_file" "${stack_file}.failed.${timestamp}"
    fi
    if [ -n "$stack_backup" ] && [ -f "$stack_backup" ]; then
        cp "$stack_backup" "$stack_file"
    fi
    if [ -f "$env_backup" ]; then
        cp "$env_backup" "$env_file"
        load_root_env "$project_root" || true
    elif [ -f "$env_file" ]; then
        mv "$env_file" "${env_file}.failed.${timestamp}"
    fi
    echo "[OK] Prior deployment artifacts were restored."
}

# ------------------------------------------------------------------------------
# restore_deployment_environment
# ------------------------------------------------------------------------------
# Restores a saved root environment, reloads its declared site profile, and
# immediately regenerates the matching Swarm stack artifact.
#
# Arguments:
#   $1 - Project root.
#
# Returns:
#   0 after environment and stack restoration; otherwise 1.
#
# Side effects:
#   Replaces root .env, backs up previous artifacts, and renders
#   swarm-stack.yml. It never deploys.
# ------------------------------------------------------------------------------
restore_deployment_environment() {
    local project_root="$1"
    local stack_file="${project_root}/swarm-stack.yml"
    local build_script="${project_root}/scripts/build-site-stack.sh"
    local saved_env_path=""
    local timestamp=""
    local stack_backup=""

    echo "Quick Restore from Saved .env"
    echo "==================================="
    echo ""
    echo "The restored profile is validated and its stack is rebuilt immediately."
    read -r -p "Path to saved .env file: " saved_env_path
    if [ -z "$saved_env_path" ]; then
        echo "[INFO] No path provided. Restore cancelled."
        return 1
    fi
    if [ ! -f "$saved_env_path" ]; then
        echo "[ERROR] File not found: ${saved_env_path}"
        return 1
    fi
    if [ ! -f "$build_script" ]; then
        echo "[ERROR] Stack renderer is missing: ${build_script}"
        return 1
    fi

    timestamp="$(date +%Y%m%d_%H%M%S)"
    _restore_and_load_environment \
        "$project_root" \
        "$saved_env_path" \
        "$timestamp" ||
        return 1

    if [ -f "$stack_file" ]; then
        stack_backup="${stack_file}.backup.${timestamp}"
        mv "$stack_file" "$stack_backup"
        echo "[OK] Retained previous stack at: ${stack_backup}"
    fi
    if ! bash "$build_script"; then
        echo "[ERROR] Stack rebuild failed; the failed output will not be deployable."
        _rollback_restored_artifacts \
            "$project_root" \
            "$timestamp" \
            "$stack_backup"
        return 1
    fi

    echo ""
    echo "[OK] Restored .env and rebuilt the matching swarm-stack.yml."
    echo "     Review secrets if needed, then choose Deploy from the main menu."
}

# ------------------------------------------------------------------------------
# restore_profile_secrets
# ------------------------------------------------------------------------------
# Imports a saved values file through the active profile's exact/prefixed secret
# policy. A running stack must be explicitly removed before replacements.
#
# Arguments:
#   $1 - Active Docker stack name.
#
# Returns:
#   Status from the profile secret importer or 1 on cancellation.
#
# Side effects:
#   May remove the selected stack and create or replace Docker secrets.
# ------------------------------------------------------------------------------
restore_profile_secrets() {
    local stack_name="$1"
    local saved_secrets_path=""
    local remove_stack=""

    echo "Quick Restore from Saved secrets.env"
    echo "========================================"
    echo ""
    echo "This creates only Docker secrets declared by the selected profile."
    echo "The stack must be stopped before replacing existing secrets."
    read -r -p "Path to saved secrets.env file: " saved_secrets_path
    if [ -z "$saved_secrets_path" ]; then
        echo "[INFO] No path provided. Restore cancelled."
        return 1
    fi
    if [ ! -f "$saved_secrets_path" ]; then
        echo "[ERROR] File not found: ${saved_secrets_path}"
        return 1
    fi
    if ! validate_profile_secret_values_file "$saved_secrets_path"; then
        echo "[ERROR] Saved secret values were rejected before stack mutation."
        return 1
    fi

    if docker stack ls --format "{{.Name}}" 2>/dev/null |
        grep -q "^${stack_name}$"; then
        echo "[WARN] Stack '${stack_name}' is currently running."
        read -r -p "Remove stack before creating secrets? (y/N): " remove_stack
        if [[ ! "$remove_stack" =~ ^[Yy]$ ]]; then
            echo "[INFO] Secret restore cancelled. Stop the stack first."
            return 1
        fi
        docker stack rm "$stack_name"
        echo "Waiting for stack removal..."
        while docker stack ls --format "{{.Name}}" 2>/dev/null |
            grep -q "^${stack_name}$"; do
            sleep 2
        done
        echo "[OK] Stack removed."
    fi
    create_profile_secrets_from_env_file "$saved_secrets_path"
}
