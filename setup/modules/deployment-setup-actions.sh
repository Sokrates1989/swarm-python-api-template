#!/bin/bash
# ==============================================================================
# deployment-setup-actions.sh - Shared post-configuration action menu
# ==============================================================================
#
# Offers the same numbered actions after every profile is configured. Actions
# appear only when declared capabilities require them. Rendering remains
# delegated to render_selected_profile_stack, supplied by setup-wizard.sh.
#
# Dependencies:
#   - setup/modules/deployment-profile-prompts.sh
#   - data-dirs, docker-secrets-menu, keycloak-bootstrap, deploy-stack, and
#     health-check setup modules
# ==============================================================================

# Guard against multiple sourcing.
if [ -n "${_DEPLOYMENT_SETUP_ACTIONS_LOADED:-}" ]; then
    return 0 2>/dev/null || true
fi
_DEPLOYMENT_SETUP_ACTIONS_LOADED=1

# Tracks preparation within one menu process so a full deployment does not
# repeat recursive ownership work immediately before the stack mutation.
_DEPLOYMENT_DATA_DIRECTORIES_READY=false

# ------------------------------------------------------------------------------
# _deployment_profile_uses_keycloak
# ------------------------------------------------------------------------------
# Checks the selected profile's authentication capability.
#
# Returns:
#   0 only when the profile declares Keycloak.
# ------------------------------------------------------------------------------
_deployment_profile_uses_keycloak() {
    if declare -F profile_supports_keycloak_bootstrap >/dev/null 2>&1; then
        profile_supports_keycloak_bootstrap
        return $?
    fi
    [ "$(_jq_or_default "$APP_CONFIG_FILE" '.auth.provider' "none")" = "keycloak" ] &&
        [ "$(_jq_or_default "$APP_CONFIG_FILE" '.renderer.type' "generic")" = "executable" ]
}

# ------------------------------------------------------------------------------
# _prepare_profile_external_network
# ------------------------------------------------------------------------------
# Verifies or creates the selected profile-declared external internal overlay.
# Public Traefik networks are owned by the proxy stack and remain selection-only.
#
# Returns:
#   0 when no preparation is required or the overlay is ready; otherwise 1.
#
# Side effects:
#   May create one explicitly confirmed Swarm overlay network.
_prepare_profile_external_network() {
    local selected_action=""
    local create_arguments=(network create --driver=overlay)

    if [ "${APP_INTERNAL_NETWORK_EXTERNAL:-false}" != "true" ]; then
        return 0
    fi
    if _swarm_overlay_network_is_usable "$INTERNAL_NETWORK"; then
        echo "[OK] Required external overlay exists: ${INTERNAL_NETWORK}"
        return 0
    fi
    prompt_deployment_choice \
        selected_action \
        "External overlay '${INTERNAL_NETWORK}' is missing" \
        "create" \
        "create|Create the declared Swarm overlay now" \
        "cancel|Cancel deployment"
    if [ "$selected_action" != "create" ]; then
        echo "[INFO] Deployment cancelled before network mutation."
        return 1
    fi
    if [ "${APP_INTERNAL_NETWORK_ATTACHABLE:-false}" = "true" ]; then
        create_arguments+=(--attachable)
    fi
    if ! docker "${create_arguments[@]}" "$INTERNAL_NETWORK"; then
        echo "[ERROR] Could not create external overlay: ${INTERNAL_NETWORK}"
        return 1
    fi
    echo "[OK] Created external overlay: ${INTERNAL_NETWORK}"
}

# ------------------------------------------------------------------------------
# _check_configured_stack_health
# ------------------------------------------------------------------------------
# Runs capability-aware acceptance checks for the active root environment.
#
# Returns:
#   0 when service replicas and every applicable public endpoint are healthy;
#   otherwise nonzero.
# ------------------------------------------------------------------------------
_check_configured_stack_health() {
    check_deployment_health \
        "$STACK_NAME" \
        "$DB_TYPE" \
        "$PROXY_TYPE" \
        "$DOMAIN" \
        20 \
        "${API_PUBLISHED_PORT:-}" \
        "${APP_ROUTING_HEALTH_PATH:-/health}" \
        "${WEB_DOMAIN:-}" \
        "${WEB_PUBLISHED_PORT:-}" \
        "${APP_ROUTING_WEB_HEALTH_PATH:-/health}"
}

# ------------------------------------------------------------------------------
# _prepare_deployment_data_directories
# ------------------------------------------------------------------------------
# Creates and repairs all profile data directories once per menu process.
#
# Returns:
#   0 when directories and runtime ownership are ready; otherwise nonzero.
#
# Side effects:
#   May create host directories and repair ownership of API writable mounts.
# ------------------------------------------------------------------------------
_prepare_deployment_data_directories() {
    if [ "$_DEPLOYMENT_DATA_DIRECTORIES_READY" = "true" ]; then
        return 0
    fi
    create_data_directories "$DATA_ROOT" "$DB_TYPE" "$DB_MODE" || return 1
    _DEPLOYMENT_DATA_DIRECTORIES_READY=true
}

# ------------------------------------------------------------------------------
# _deploy_configured_stack
# ------------------------------------------------------------------------------
# Repairs profile data-directory ownership, deploys the already-rendered stack,
# and runs the common health check.
#
# Arguments:
#   $1 - Optional "confirmed" mode when a parent workflow already confirmed
#        the exact deployment plan.
#
# Returns:
#   0 after deployment and health verification; otherwise nonzero. The global
#   DEPLOY_CONFIGURED_STACK_MUTATED reports whether Docker accepted the deploy.
#
# Side effects:
#   Mutates the selected Docker Swarm stack after the operator chooses deploy.
# ------------------------------------------------------------------------------
_deploy_configured_stack() {
    local stack_file="${PROJECT_ROOT}/swarm-stack.yml"
    local confirmation_mode="${1:-prompt}"

    DEPLOY_CONFIGURED_STACK_MUTATED=false

    if [ ! -f "$stack_file" ]; then
        echo "[ERROR] swarm-stack.yml is missing. Build it first."
        return 1
    fi
    _prepare_deployment_data_directories || return 1
    verify_required_docker_secrets "$stack_file" || return 1
    _prepare_profile_external_network || return 1
    deploy_stack "$STACK_NAME" "$stack_file" "$confirmation_mode" || return 1
    DEPLOY_CONFIGURED_STACK_MUTATED=true
    _check_configured_stack_health
}

# ------------------------------------------------------------------------------
# _run_full_deployment
# ------------------------------------------------------------------------------
# Runs the explicit directory, render, secret, and deploy sequence.
#
# Returns:
#   0 when every selected step succeeds; otherwise nonzero.
#
# Side effects:
#   May create host directories and Docker secrets and deploy a Swarm stack.
# ------------------------------------------------------------------------------
_run_full_deployment() {
    echo ""
    echo "Full deploy sequence"
    echo "--------------------"
    _prepare_deployment_data_directories || return 1
    render_selected_profile_stack || return 1
    if [ "${SECRETS_REQUIRED:-false}" = "true" ]; then
        echo ""
        echo "Required Docker secrets must exist before deployment."
        manage_docker_secrets_menu || return 1
    fi
    _deploy_configured_stack
}

# ------------------------------------------------------------------------------
# _show_configuration_summary
# ------------------------------------------------------------------------------
# Prints one renderer-independent configuration summary.
#
# Returns:
#   0 after printing public deployment values.
# ------------------------------------------------------------------------------
_show_configuration_summary() {
    echo ""
    echo "============================================"
    echo "Configuration complete!"
    echo "============================================"
    echo ""
    echo "Stack Name:   ${STACK_NAME}"
    echo "Domain:       ${DOMAIN}"
    if [ "${APP_REQUIRES_WEB:-false}" = "true" ]; then
        echo "Web Domain:   ${WEB_DOMAIN}"
    fi
    echo "App:          ${APP_NAME} (${APP_ID})"
    echo "Database:     ${DB_TYPE} (${DB_MODE})"
    echo "Image:        ${IMAGE_NAME}:${IMAGE_VERSION}"
    if [ "${APP_REQUIRES_WEB:-false}" = "true" ]; then
        echo "Web Image:    ${WEB_IMAGE_NAME}:${WEB_IMAGE_VERSION}"
    fi
    echo "Environment:  ${PROJECT_ROOT}/.env"
    echo "Stack file:   ${PROJECT_ROOT}/swarm-stack.yml"
}

# ------------------------------------------------------------------------------
# run_deployment_setup_actions
# ------------------------------------------------------------------------------
# Renders the shared dynamic final-action menu and executes one selected action.
#
# Returns:
#   Selected action status.
# ------------------------------------------------------------------------------
run_deployment_setup_actions() {
    local choices=(
        "done|Done (save and render only)"
        "directories|Create data directories"
        "render|Build swarm-stack.yml"
    )
    local selected_action=""

    if [ "${SECRETS_REQUIRED:-false}" = "true" ]; then
        choices+=("secrets|Manage profile Docker secrets")
        if profile_supports_secret_file_workflow; then
            choices+=(
                "secret-file|Create all editable Docker secrets from temporary secrets.env"
            )
        fi
    fi
    if _deployment_profile_uses_keycloak; then
        choices+=("keycloak|Bootstrap / update Keycloak realm")
    fi
    choices+=(
        "deploy|Deploy to Docker Swarm"
        "full|Full deploy (directories + stack + secrets + deploy)"
    )

    _show_configuration_summary
    prompt_deployment_choice \
        selected_action \
        "What would you like to do next?" \
        "done" \
        "${choices[@]}"
    case "$selected_action" in
        done)
            echo "Configuration saved; no runtime state was changed."
            ;;
        directories)
            _prepare_deployment_data_directories
            ;;
        render)
            render_selected_profile_stack
            ;;
        secrets)
            manage_docker_secrets_menu
            ;;
        secret-file)
            create_profile_secrets_from_env_file \
                "${PROJECT_ROOT}/secrets.env"
            ;;
        keycloak)
            run_profile_keycloak_bootstrap
            ;;
        deploy)
            _deploy_configured_stack
            ;;
        full)
            _run_full_deployment
            ;;
        *)
            echo "[ERROR] Unsupported setup action: ${selected_action}"
            return 1
            ;;
    esac
}
