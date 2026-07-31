#!/bin/bash
# ==============================================================================
# menu_handlers.sh - Main operations menu for deployment management
# ==============================================================================
#
# Provides the interactive menu loop used by quick-start.sh. All actions
# operate on ROOT-LEVEL artifacts (.env, swarm-stack.yml, data dirs).
#
# Expects load_root_env to have been called so that STACK_NAME, DB_TYPE,
# PROXY_TYPE, IMAGE_NAME, IMAGE_VERSION, DOMAIN, SECRET_PREFIX, etc.
# are exported.
#
# Dependencies:
#   - site_helpers.sh (load_root_env)
#   - secret-manager.sh (create_docker_secrets, list_docker_secrets)
#   - deploy-stack.sh (deploy_stack)
#   - health-check.sh (check_deployment_health)
#   - deployment-setup-actions.sh (_deploy_configured_stack,
#     _check_configured_stack_health)
#   - stack-conflict-check.sh (check_stack_conflict)
# ==============================================================================

# Source formatting helpers
MENU_HANDLERS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "${MENU_HANDLERS_DIR}/menu_formatting.sh" ]; then
    # shellcheck source=/dev/null
    source "${MENU_HANDLERS_DIR}/menu_formatting.sh"
fi

# Source auth provider module
if [ -f "${MENU_HANDLERS_DIR}/auth_provider.sh" ]; then
    # shellcheck source=/dev/null
    source "${MENU_HANDLERS_DIR}/auth_provider.sh"
fi

# Source git update helpers
if [ -f "${MENU_HANDLERS_DIR}/git_helpers.sh" ]; then
    # shellcheck source=/dev/null
    source "${MENU_HANDLERS_DIR}/git_helpers.sh"
fi

# Source safe environment/secret restore actions.
if [ -f "${MENU_HANDLERS_DIR}/menu-restore-actions.sh" ]; then
    # shellcheck source=/dev/null
    source "${MENU_HANDLERS_DIR}/menu-restore-actions.sh"
fi

# Source the single shared configuration action.
if [ -f "${MENU_HANDLERS_DIR}/menu-configuration-actions.sh" ]; then
    # shellcheck source=/dev/null
    source "${MENU_HANDLERS_DIR}/menu-configuration-actions.sh"
fi

# _stack_running
# Checks if a Docker stack is running.
#
# Arguments:
#   $1 - stack_name: name of the Docker stack
#
# Returns:
#   0 if running, 1 otherwise
_stack_running() {
    local stack_name="$1"
    docker stack ls --format '{{.Name}}' 2>/dev/null | grep -qx "${stack_name}"
}

# _service_replicas_healthy
# Checks whether one Docker service has reached its desired replica count.
#
# Arguments:
#   $1 - service_name: full Docker service name.
#
# Returns:
#   0 when current replicas equal desired replicas and desired is greater than
#   zero, 1 otherwise.
_service_replicas_healthy() {
    local service_name="$1"
    local replicas
    replicas=$(docker service ls --filter "name=${service_name}" --format '{{.Replicas}}' 2>/dev/null | head -n 1)

    if [[ "$replicas" =~ ^([0-9]+)/([0-9]+)$ ]]; then
        local current="${BASH_REMATCH[1]}"
        local desired="${BASH_REMATCH[2]}"
        [ "$desired" -gt 0 ] && [ "$current" = "$desired" ]
        return $?
    fi

    return 1
}

# _profile_requires_secrets
# Checks whether the active deployment profile declares Docker secrets.
#
# Arguments:
#   None. Reads the selected site config or legacy stack globals.
#
# Returns:
#   0 when secret actions should be shown, 1 when the profile has no secrets.
_profile_requires_secrets() {
    local profile_file=""

    if declare -F _profile_config_file >/dev/null 2>&1; then
        profile_file="$(_profile_config_file)" || profile_file=""
    fi
    if [ -n "$profile_file" ] && [ -f "$profile_file" ] &&
        declare -F site_profile_declares_secrets >/dev/null 2>&1; then
        site_profile_declares_secrets "$profile_file"
        return $?
    fi
    if [ "${STACK_FAMILY:-api}" = "nginx" ] || [ "${DB_TYPE:-postgresql}" = "none" ]; then
        return 1
    fi

    return 0
}

# _primary_service_suffix
# Resolves the active profile's primary service suffix.
#
# Arguments:
#   None. Reads PRIMARY_SERVICE and STACK_FAMILY from the loaded environment.
#
# Outputs:
#   Service suffix without the stack-name prefix.
#
# Returns:
#   0 always.
_primary_service_suffix() {
    if [ -n "${PRIMARY_SERVICE:-}" ]; then
        echo "$PRIMARY_SERVICE"
        return 0
    fi

    if [ "${STACK_FAMILY:-api}" = "nginx" ]; then
        echo "nginx"
        return 0
    fi

    echo "api"
}

# _stack_service_names
# Lists actual Docker services for the stack, or falls back to the primary
# service before a deployment exists.
#
# Arguments:
#   $1 - stack_name: Docker stack name.
#
# Outputs:
#   One Docker service name per line.
#
# Returns:
#   0 always.
_stack_service_names() {
    local stack_name="$1"
    local services

    services=$(docker service ls --filter "label=com.docker.stack.namespace=${stack_name}" --format '{{.Name}}' 2>/dev/null || true)
    if [ -n "$services" ]; then
        printf '%s\n' $services
        return 0
    fi

    echo "${stack_name}_$(_primary_service_suffix)"
}

# _stack_services_healthy
# Checks whether every deployed stack service has reached its desired replica
# count. This avoids assuming an API service exists for nginx-only profiles.
#
# Arguments:
#   $1 - stack_name: Docker stack name.
#
# Returns:
#   0 when all deployed services are healthy, 1 otherwise.
_stack_services_healthy() {
    local stack_name="$1"
    local services
    local saw_service=false

    services="$(_stack_service_names "$stack_name")"
    while IFS= read -r service_name; do
        [ -z "$service_name" ] && continue
        saw_service=true
        _service_replicas_healthy "$service_name" || return 1
    done <<< "$services"

    [ "$saw_service" = true ]
}

# show_deployment_overview
# Displays a boxed deployment overview using globals from load_root_env.
#
# Arguments:
#   (none — reads exported globals)
show_deployment_overview() {
    local stack_name="${STACK_NAME:-unknown}"
    local proxy_type="${PROXY_TYPE:-none}"
    local db_type="${DB_TYPE:-postgresql}"
    local api_url="${DOMAIN:-}"
    local image_name="${IMAGE_NAME:-}"
    local image_version="${IMAGE_VERSION:-latest}"
    local deployment_profile="${DEPLOYMENT_PROFILE_ID:-${BACKEND_APP_ID:-}}"

    local ok_icon="✅"
    local off_icon="⏹️"
    local warn_icon="⚠️"
    local stack_status="${off_icon} not running"
    local image_icon="${off_icon}"

    if _stack_running "$stack_name"; then
        if _stack_services_healthy "$stack_name"; then
            stack_status="${ok_icon} healthy"
            image_icon="${ok_icon}"
        else
            stack_status="${warn_icon} degraded"
            image_icon="${warn_icon}"
        fi
    else
        stack_status="${off_icon} not running"
        image_icon="${off_icon}"
    fi

    _box_rule
    _box_line "Deployment Overview"
    _box_rule
    _box_line "Stack    : ${stack_name} (${stack_status})"
    if [ -n "$deployment_profile" ]; then
        _box_line "Profile  : ${deployment_profile}"
    fi
    _box_line "Proxy    : ${proxy_type}"
    _box_line "DB Type  : ${db_type}"
    if [ -n "$api_url" ]; then
        _box_line "Domain   : ${api_url}"
    fi
    _box_line "Images   :"
    _box_line_list "${image_icon} ${image_name}:${image_version}"
    if declare -F show_git_status_line >/dev/null; then
        _box_line "$(show_git_status_line)"
    fi
    _box_rule
    echo ""
}

# ==============================================================================
# show_main_menu
# ==============================================================================
# Main interactive menu loop. Operates on root-level deployment artifacts.
#
# Expects quick-start.sh to have called load_root_env so STACK_NAME, DB_TYPE,
# PROXY_TYPE, IMAGE_NAME, IMAGE_VERSION, DOMAIN, SECRET_PREFIX are set.
# ==============================================================================
show_main_menu() {
    local choice
    local env_file="${PROJECT_ROOT:-.}/.env"
    local stack_file="${PROJECT_ROOT:-.}/swarm-stack.yml"

    # Check for repo updates once on menu entry
    if declare -F check_git_updates >/dev/null; then
        check_git_updates
    fi

    while true; do
        local MENU_NEXT=1
        local MENU_SETUP_WIZARD=$MENU_NEXT
        MENU_NEXT=$((MENU_NEXT+1))
        local MENU_SETUP_SECRETS="__disabled_setup_secrets"
        local MENU_RESTORE_ENV=$MENU_NEXT
        MENU_NEXT=$((MENU_NEXT+1))
        local MENU_RESTORE_SECRETS="__disabled_restore_secrets"
        if _profile_requires_secrets; then
            MENU_SETUP_SECRETS=$MENU_NEXT
            MENU_NEXT=$((MENU_NEXT+1))
            if declare -F profile_supports_secret_file_workflow >/dev/null 2>&1 &&
                profile_supports_secret_file_workflow; then
                MENU_RESTORE_SECRETS=$MENU_NEXT
                MENU_NEXT=$((MENU_NEXT+1))
            fi
        fi
        local MENU_SETUP_AUTH=""
        local MENU_KEYCLOAK_BOOTSTRAP=""
        if declare -F profile_supports_keycloak_bootstrap >/dev/null 2>&1 &&
            profile_supports_keycloak_bootstrap; then
            MENU_KEYCLOAK_BOOTSTRAP=$MENU_NEXT
            MENU_NEXT=$((MENU_NEXT+1))
        elif declare -F setup_auth_provider >/dev/null; then
            MENU_SETUP_AUTH=$MENU_NEXT
            MENU_NEXT=$((MENU_NEXT+1))
        fi

        local MENU_DEPLOY=$MENU_NEXT
        MENU_NEXT=$((MENU_NEXT+1))
        local MENU_ROLLBACK=$MENU_NEXT
        MENU_NEXT=$((MENU_NEXT+1))
        local MENU_STATUS=$MENU_NEXT
        MENU_NEXT=$((MENU_NEXT+1))
        local MENU_LOGS=$MENU_NEXT
        MENU_NEXT=$((MENU_NEXT+1))

        local MENU_UPDATE_IMAGE=$MENU_NEXT
        MENU_NEXT=$((MENU_NEXT+1))
        local MENU_SCALE=$MENU_NEXT
        MENU_NEXT=$((MENU_NEXT+1))
        local MENU_REMOVE=$MENU_NEXT
        MENU_NEXT=$((MENU_NEXT+1))

        local MENU_BUILD_STACK=$MENU_NEXT
        MENU_NEXT=$((MENU_NEXT+1))

        local MENU_CONFIGURE_ADMIN_UI=""
        if [ "$DB_MODE" = "local" ] &&
            [ "$DB_TYPE" != "none" ] &&
            [ -n "${APP_ADMIN_UI_TYPE:-}" ]; then
            MENU_CONFIGURE_ADMIN_UI=$MENU_NEXT
            MENU_NEXT=$((MENU_NEXT+1))
        fi

        local MENU_INSPECT=$MENU_NEXT
        MENU_NEXT=$((MENU_NEXT+1))

        local MENU_CICD=$MENU_NEXT
        MENU_NEXT=$((MENU_NEXT+1))

        local MENU_EXIT=$MENU_NEXT

        echo ""
        echo "================ Main Menu ================"
        echo ""
        if declare -F _box_rule >/dev/null; then
            show_deployment_overview
        fi

        echo "Setup:"
        echo "  ${MENU_SETUP_WIZARD}) Re-run setup wizard"
        if _profile_requires_secrets; then
            echo "  ${MENU_SETUP_SECRETS}) Manage Docker secrets"
        fi
        echo "  ${MENU_RESTORE_ENV}) Quick restore from saved .env"
        if [ "$MENU_RESTORE_SECRETS" != "__disabled_restore_secrets" ]; then
            echo "  ${MENU_RESTORE_SECRETS}) Quick restore from saved secrets.env"
        fi
        if [ -n "$MENU_SETUP_AUTH" ]; then
            echo "  ${MENU_SETUP_AUTH}) Configure Authentication (Cognito/Keycloak)"
        fi
        if [ -n "$MENU_KEYCLOAK_BOOTSTRAP" ]; then
            echo "  ${MENU_KEYCLOAK_BOOTSTRAP}) Bootstrap / update Keycloak realm"
        fi
        echo ""

        echo "Deployment:"
        echo "  ${MENU_DEPLOY}) Deploy to Docker Swarm"
        echo "  ${MENU_ROLLBACK}) Roll back retained service specifications"
        echo "  ${MENU_STATUS}) Check deployment status"
        echo "  ${MENU_LOGS}) View service logs"
        echo ""

        echo "Management:"
        echo "  ${MENU_UPDATE_IMAGE}) Change service image configuration"
        echo "  ${MENU_SCALE}) Change replica configuration"
        echo "  ${MENU_REMOVE}) Remove deployment"
        echo "  ${MENU_BUILD_STACK}) Rebuild swarm stack"
        if [ -n "$MENU_CONFIGURE_ADMIN_UI" ]; then
            echo "  ${MENU_CONFIGURE_ADMIN_UI}) Change database-management configuration"
        fi
        echo "  ${MENU_INSPECT}) Inspect deployment artifacts"
        echo ""

        echo "CI/CD:"
        echo "  ${MENU_CICD}) GitHub Actions CI/CD helper"
        echo ""
        echo "  ${MENU_EXIT}) Exit"
        echo ""

        if [ "$_GIT_UPDATE_STATUS" = "behind" ]; then
            echo "  ────────────────────────────────────────"
            echo "  u) ⬆️  Update deployment scripts (${_GIT_UPDATE_BEHIND_COUNT} update(s) available)"
            echo "  ────────────────────────────────────────"
            echo ""
        fi

        local prompt_text="Your choice (1-${MENU_EXIT}"
        if [ "$_GIT_UPDATE_STATUS" = "behind" ]; then
            prompt_text="${prompt_text}, u"
        fi
        prompt_text="${prompt_text}): "

        if [[ -r /dev/tty ]]; then
            read -r -p "$prompt_text" choice < /dev/tty
        else
            read -r -p "$prompt_text" choice
        fi

        if [ -n "$MENU_SETUP_AUTH" ] && [ "$choice" = "$MENU_SETUP_AUTH" ]; then
            setup_auth_provider
            echo ""
            show_auth_status
            echo ""
            read -r -p "Press Enter to continue..."
            continue
        fi
        if [ -n "$MENU_KEYCLOAK_BOOTSTRAP" ] &&
            [ "$choice" = "$MENU_KEYCLOAK_BOOTSTRAP" ]; then
            if ! run_profile_keycloak_bootstrap; then
                echo "[ERROR] Keycloak bootstrap did not complete."
            fi
            read -r -p "Press Enter to continue..."
            continue
        fi

        case $choice in
        ${MENU_DEPLOY})
            echo "[DEPLOY] Deploying to Docker Swarm..."
            echo ""
            echo "Before deployment, make sure you have:"
            if _profile_requires_secrets; then
                echo "   - Created Docker secrets"
            else
                echo "   - No Docker secrets are required for this profile"
            fi
            echo "   - Configured your domain DNS"
            echo "   - Created data directories"
            echo ""

            if [ ! -f "$stack_file" ]; then
                echo "⚠️  swarm-stack.yml not found at project root."
                echo "   Run 'Rebuild swarm stack' or the setup wizard first."
            else
                _deploy_configured_stack
            fi
            ;;
        ${MENU_ROLLBACK})
            rollback_stack_services "$STACK_NAME" || true
            ;;
        ${MENU_STATUS})
            echo "🏥 Running deployment health check..."
            echo ""
            _check_configured_stack_health
            ;;
        ${MENU_LOGS})
            echo "[LOGS] Service Logs"
            echo ""

            local services
            services="$(_stack_service_names "$STACK_NAME")"
            if [ -z "$services" ]; then
                echo "No services found for stack: $STACK_NAME"
                break
            fi

            echo "Which service logs do you want to view?"
            local index=1
            while IFS= read -r svc; do
                [ -z "$svc" ] && continue
                echo "${index}) ${svc}"
                index=$((index + 1))
            done <<< "$services"
            echo "${index}) All"
            echo ""

            local log_choice
            if [[ -r /dev/tty ]]; then
                read -r -p "Your choice (1-${index}): " log_choice < /dev/tty
            else
                read -r -p "Your choice (1-${index}): " log_choice
            fi

            if [ "$log_choice" = "$index" ]; then
                while IFS= read -r svc; do
                    [ -z "$svc" ] && continue
                    echo ""
                    echo "===== $svc ====="
                    docker service logs --tail 50 "$svc" 2>/dev/null || true
                done <<< "$services"
            elif [[ "$log_choice" =~ ^[0-9]+$ ]] && [ "$log_choice" -ge 1 ] && [ "$log_choice" -lt "$index" ]; then
                local selected_service
                selected_service=$(printf '%s\n' "$services" | sed -n "${log_choice}p")
                docker service logs -f "$selected_service"
            else
                echo "Invalid choice"
            fi
            ;;
        ${MENU_UPDATE_IMAGE})
            _run_shared_reconfiguration \
                "Change image repositories or versions through the shared wizard." ||
                true
            ;;
        ${MENU_SCALE})
            _run_shared_reconfiguration \
                "Change service replica counts through the shared wizard." ||
                true
            ;;
        ${MENU_REMOVE})
            echo "🗑️  Remove Deployment"
            echo ""
            echo "⚠️  WARNING: This will remove all services in the '${STACK_NAME}' stack."
            echo "Data in volumes will be preserved."
            echo ""
            if [[ -r /dev/tty ]]; then
                read -r -p "Are you sure? Type 'yes' to confirm: " confirm < /dev/tty
            else
                read -r -p "Are you sure? Type 'yes' to confirm: " confirm
            fi
            if [ "$confirm" = "yes" ]; then
                echo ""
                echo "Removing stack: $STACK_NAME"
                docker stack rm "$STACK_NAME"
                echo ""
                echo "✅ Stack removal initiated!"
                echo "Wait for all services to be removed before redeploying."
            else
                echo "Removal cancelled."
            fi
            ;;
        ${MENU_SETUP_WIZARD})
            _run_shared_reconfiguration "Re-run deployment setup." || true
            ;;
        ${MENU_SETUP_SECRETS})
            manage_docker_secrets_menu
            ;;
        ${MENU_RESTORE_ENV})
            restore_deployment_environment "${PROJECT_ROOT:-.}" || true
            ;;
        ${MENU_RESTORE_SECRETS})
            restore_profile_secrets "$STACK_NAME" || true
            ;;
        ${MENU_BUILD_STACK})
            echo "[BUILD] Rebuilding swarm-stack.yml..."
            echo ""
            local build_script="${PROJECT_ROOT:-.}/scripts/build-site-stack.sh"
            if [ -f "$build_script" ]; then
                bash "$build_script"
            else
                echo "[WARN] build-site-stack.sh not found."
                echo "   Expected at: $build_script"
            fi
            ;;
        ${MENU_CONFIGURE_ADMIN_UI})
            _run_shared_reconfiguration \
                "Change database-management settings through the shared wizard." ||
                true
            ;;
        ${MENU_INSPECT})
            echo ""
            echo "🔍 Deployment Artifacts"
            echo "===================================="
            echo ""
            echo "  .env:             ${env_file}"
            echo "  swarm-stack.yml:  ${stack_file}"
            echo ""

            if [ -f "$stack_file" ]; then
                echo "  Stack file:     ✅ exists"
            else
                echo "  Stack file:     ❌ not built yet"
            fi

            echo ""
            echo "--- .env contents ---"
            if [ -f "$env_file" ]; then
                cat "$env_file"
            else
                echo "  (not generated yet)"
            fi
            echo ""
            ;;
        ${MENU_CICD})
            run_ci_cd_github_helper
            ;;
        ${MENU_EXIT})
            echo "👋 Goodbye!"
            exit 0
            ;;
        u|U)
            if [ "$_GIT_UPDATE_STATUS" = "behind" ]; then
                handle_git_pull
            else
                echo "ℹ️  Repository is already up to date."
            fi
            ;;
        *)
            echo "❌ Invalid choice"
            ;;
        esac

        echo ""
    done
}
