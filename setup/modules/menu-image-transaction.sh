#!/bin/bash
# ==============================================================================
# menu-image-transaction.sh - Atomic image configuration deployment boundary
# ==============================================================================
#
# Stages public image assignments, preserves the current environment and stack,
# rerenders through the active profile, and invokes the shared Swarm deploy and
# health boundary. Failures before Docker accepts a mutation restore both local
# artifacts; post-mutation health failures retain the selected desired state for
# diagnosis and explicit service rollback.
#
# Dependencies:
#   - deployment-environment-format.sh.
#   - site_helpers.sh and deployment-setup-actions.sh at execution time.
# ==============================================================================

# Guard against multiple sourcing.
if [ -n "${_MENU_IMAGE_TRANSACTION_LOADED:-}" ]; then
    return 0 2>/dev/null || true
fi
_MENU_IMAGE_TRANSACTION_LOADED=1

# ------------------------------------------------------------------------------
# _replace_deployment_environment_value
# ------------------------------------------------------------------------------
# Rewrites one exact public dotenv assignment in a staged file without
# evaluating either existing content or the replacement value.
#
# Arguments:
#   $1 - Staged environment file.
#   $2 - Exact uppercase key.
#   $3 - Validated public value.
#
# Returns:
#   0 after replacement or append; otherwise nonzero.
# ------------------------------------------------------------------------------
_replace_deployment_environment_value() {
    local environment_file="$1"
    local key="$2"
    local value="$3"
    local rewritten="${environment_file}.rewrite"
    local line=""
    local replaced=false

    : > "$rewritten" || return 1
    while IFS= read -r line || [ -n "$line" ]; do
        if [[ "$line" == "${key}="* ]]; then
            printf '%s=%s\n' "$key" "$value" >> "$rewritten"
            replaced=true
        else
            printf '%s\n' "$line" >> "$rewritten"
        fi
    done < "$environment_file"
    if [ "$replaced" = false ]; then
        printf '%s=%s\n' "$key" "$value" >> "$rewritten"
    fi
    mv -f "$rewritten" "$environment_file"
}

# ------------------------------------------------------------------------------
# _stage_release_image_environment
# ------------------------------------------------------------------------------
# Applies every prepared image assignment to a protected environment copy.
#
# Arguments:
#   $1 - Staged environment file.
#   Remaining arguments - KEY=VALUE image assignments.
#
# Returns:
#   0 after every assignment is staged; otherwise nonzero.
# ------------------------------------------------------------------------------
_stage_release_image_environment() {
    local environment_file="$1"
    shift
    local assignment=""
    local key=""
    local value=""

    for assignment in "$@"; do
        key="${assignment%%=*}"
        value="${assignment#*=}"
        _replace_deployment_environment_value \
            "$environment_file" "$key" "$value" || return 1
    done
}

# ------------------------------------------------------------------------------
# _restore_release_image_artifacts
# ------------------------------------------------------------------------------
# Restores the pre-action public environment and rendered stack when failure
# occurs before Docker Swarm accepted a deployment mutation.
#
# Arguments:
#   $1 - Transaction directory.
#
# Returns:
#   0 after restoration.
# ------------------------------------------------------------------------------
_restore_release_image_artifacts() {
    local transaction_directory="$1"
    local stack_backup="${transaction_directory}/swarm-stack.yml"

    cp "${transaction_directory}/.env" "${PROJECT_ROOT}/.env"
    chmod 600 "${PROJECT_ROOT}/.env"
    if [ -f "$stack_backup" ]; then
        cp "$stack_backup" "${PROJECT_ROOT}/swarm-stack.yml"
    else
        rm -f "${PROJECT_ROOT}/swarm-stack.yml"
    fi
    load_root_env "$PROJECT_ROOT" || true
    echo "[OK] Restored the previous image configuration and rendered stack."
}

# ------------------------------------------------------------------------------
# _clean_release_image_transaction
# ------------------------------------------------------------------------------
# Deletes only the known files created inside one image-update transaction.
#
# Arguments:
#   $1 - Transaction directory created by this module.
# ------------------------------------------------------------------------------
_clean_release_image_transaction() {
    local transaction_directory="$1"

    rm -f \
        "${transaction_directory}/.env" \
        "${transaction_directory}/staged.env" \
        "${transaction_directory}/staged.env.rewrite" \
        "${transaction_directory}/swarm-stack.yml"
    rmdir "$transaction_directory" 2>/dev/null || true
}

# ------------------------------------------------------------------------------
# _apply_release_image_update
# ------------------------------------------------------------------------------
# Commits the staged public configuration, rerenders, deploys without a second
# confirmation, and runs the common health check.
#
# Arguments:
#   $1 - Protected transaction directory.
#
# Returns:
#   0 after verified deployment, 2 when values already match, or 1 on failure.
# ------------------------------------------------------------------------------
_apply_release_image_update() {
    local transaction_directory="$1"
    local staged_environment="${transaction_directory}/staged.env"
    local stack_file="${PROJECT_ROOT}/swarm-stack.yml"

    cp "${PROJECT_ROOT}/.env" "${transaction_directory}/.env" || return 1
    cp "${PROJECT_ROOT}/.env" "$staged_environment" || return 1
    if [ -f "$stack_file" ]; then
        cp "$stack_file" "${transaction_directory}/swarm-stack.yml" || return 1
    fi
    _stage_release_image_environment \
        "$staged_environment" \
        "${IMAGE_UPDATE_ENV_ASSIGNMENTS[@]}" || return 1
    if cmp -s "${PROJECT_ROOT}/.env" "$staged_environment"; then
        echo "[INFO] The selected image configuration is already active."
        return 2
    fi
    if declare -F backup_existing_files >/dev/null 2>&1; then
        backup_existing_files "$PROJECT_ROOT"
    fi
    mv -f "$staged_environment" "${PROJECT_ROOT}/.env"
    chmod 600 "${PROJECT_ROOT}/.env"
    if ! format_deployment_environment_file "${PROJECT_ROOT}/.env"; then
        _restore_release_image_artifacts "$transaction_directory"
        return 1
    fi
    if ! bash "${PROJECT_ROOT}/scripts/build-site-stack.sh"; then
        _restore_release_image_artifacts "$transaction_directory"
        return 1
    fi
    if ! load_root_env "$PROJECT_ROOT"; then
        _restore_release_image_artifacts "$transaction_directory"
        return 1
    fi
    DEPLOY_CONFIGURED_STACK_MUTATED=false
    if _deploy_configured_stack confirmed; then
        echo ""
        echo "[OK] Service image update deployed and health-verified."
        echo "     Stack: ${STACK_NAME}"
        echo "     Version: ${IMAGE_UPDATE_SELECTED_VERSION}"
        return 0
    fi
    if [ "${DEPLOY_CONFIGURED_STACK_MUTATED:-false}" != "true" ]; then
        _restore_release_image_artifacts "$transaction_directory"
    else
        echo "[ERROR] Swarm accepted the update, but health acceptance failed."
        echo "        The selected configuration remains recorded for diagnosis."
        echo "        Swarm update policies may already have rolled back failed tasks;"
        echo "        inspect status and use the rollback menu when required."
    fi
    return 1
}
