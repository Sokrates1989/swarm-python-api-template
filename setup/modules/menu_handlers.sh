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
#   - stack-conflict-check.sh (check_stack_conflict)
#   - config-builder.sh (update_env_values)
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
# Checks whether the active deployment profile needs Docker secrets.
#
# Arguments:
#   None. Reads STACK_FAMILY and DB_TYPE from the loaded environment.
#
# Returns:
#   0 when secret actions should be shown, 1 when the profile has no secrets.
_profile_requires_secrets() {
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

# _primary_service_name
# Builds the Docker service name for the active profile's primary service.
#
# Arguments:
#   None. Reads STACK_NAME and primary service environment values.
#
# Outputs:
#   Full Docker service name, such as stack_api or stack_nginx.
#
# Returns:
#   0 always.
_primary_service_name() {
    echo "${STACK_NAME}_$(_primary_service_suffix)"
}

# _primary_service_label
# Builds a human-readable label for primary-service menu text.
#
# Arguments:
#   None. Reads the active primary service suffix.
#
# Outputs:
#   Display label such as API, Nginx, or Service.
#
# Returns:
#   0 always.
_primary_service_label() {
    case "$(_primary_service_suffix)" in
        api) echo "API" ;;
        nginx) echo "Nginx" ;;
        *) echo "Service" ;;
    esac
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

# _bump_semver
# Bumps a semantic version string by level (patch/minor/major).
# Supports optional "v" prefix (e.g. v1.2.3).
# Returns empty string when input is not semver-like.
#
# Arguments:
#   $1 - version: current version string
#   $2 - level: bump level (patch, minor, or major)
#
# Returns:
#   Bumped version string (or empty if invalid)
_bump_semver() {
    local version="$1"
    local level="$2"

    if [ -z "$version" ]; then
        version="0.0.0"
    fi

    local prefix=""
    if [[ "$version" =~ ^[vV] ]]; then
        prefix="${version:0:1}"
        version="${version:1}"
    fi

    if [[ ! "$version" =~ ^[0-9]+(\.[0-9]+){0,2}$ ]]; then
        echo ""
        return 0
    fi

    local IFS='.'
    local major minor patch
    read -r major minor patch <<< "$version"
    major="${major:-0}"
    minor="${minor:-0}"
    patch="${patch:-0}"

    case "$level" in
        patch) patch=$((patch + 1)) ;;
        minor) minor=$((minor + 1)); patch=0 ;;
        major) major=$((major + 1)); minor=0; patch=0 ;;
        *) echo ""; return 0 ;;
    esac

    echo "${prefix}${major}.${minor}.${patch}"
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
            MENU_RESTORE_SECRETS=$MENU_NEXT
            MENU_NEXT=$((MENU_NEXT+1))
        fi
        local MENU_SETUP_AUTH=""
        local MENU_FELIX_KEYCLOAK=""
        if declare -F felix_keycloak_release_menu >/dev/null &&
            _is_felix_candidate_profile; then
            MENU_FELIX_KEYCLOAK=$MENU_NEXT
            MENU_NEXT=$((MENU_NEXT+1))
        elif declare -F setup_auth_provider >/dev/null; then
            MENU_SETUP_AUTH=$MENU_NEXT
            MENU_NEXT=$((MENU_NEXT+1))
        fi

        local MENU_DEPLOY=$MENU_NEXT
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

        local MENU_TOGGLE_ADMIN_UI=""
        if [ "$DB_MODE" = "local" ] && [ "$DB_TYPE" != "none" ]; then
            MENU_TOGGLE_ADMIN_UI=$MENU_NEXT
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
        if _profile_requires_secrets; then
            echo "  ${MENU_RESTORE_SECRETS}) Quick restore from saved secrets.env"
        fi
        if [ -n "$MENU_SETUP_AUTH" ]; then
            echo "  ${MENU_SETUP_AUTH}) Configure Authentication (Cognito/Keycloak)"
        fi
        if [ -n "$MENU_FELIX_KEYCLOAK" ]; then
            echo "  ${MENU_FELIX_KEYCLOAK}) Felix candidate Keycloak"
        fi
        echo ""

        echo "Deployment:"
        echo "  ${MENU_DEPLOY}) Deploy to Docker Swarm"
        echo "  ${MENU_STATUS}) Check deployment status"
        echo "  ${MENU_LOGS}) View service logs"
        echo ""

        echo "Management:"
        echo "  ${MENU_UPDATE_IMAGE}) Update service image"
        echo "  ${MENU_SCALE}) Scale services"
        echo "  ${MENU_REMOVE}) Remove deployment"
        echo "  ${MENU_BUILD_STACK}) Rebuild swarm stack"
        if [ -n "$MENU_TOGGLE_ADMIN_UI" ]; then
            local admin_ui_label="Enable"
            local admin_ui_replicas="0"
            if [ "$DB_TYPE" = "postgresql" ]; then
                admin_ui_replicas="${PGADMIN_REPLICAS:-0}"
            elif [ "$DB_TYPE" = "mongodb" ]; then
                admin_ui_replicas="${MONGO_EXPRESS_REPLICAS:-0}"
            fi
            if [ "$admin_ui_replicas" != "0" ]; then
                admin_ui_label="Disable"
            fi
            echo "  ${MENU_TOGGLE_ADMIN_UI}) ${admin_ui_label} Admin UI (${DB_TYPE})"
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
        if [ -n "$MENU_FELIX_KEYCLOAK" ] &&
            [ "$choice" = "$MENU_FELIX_KEYCLOAK" ]; then
            felix_keycloak_release_menu
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
                deploy_stack "$STACK_NAME" "$stack_file"
            fi
            ;;
        ${MENU_STATUS})
            echo "🏥 Running deployment health check..."
            echo ""
            check_deployment_health "$STACK_NAME" "$DB_TYPE" "$PROXY_TYPE" "$DOMAIN"
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
            local service_name
            local service_label
            service_name="$(_primary_service_name)"
            service_label="$(_primary_service_label)"

            echo "[IMAGE] Update ${service_label} Image"
            echo "=============================="
            echo ""
            echo "  Current image: $IMAGE_NAME:$IMAGE_VERSION"
            echo "  Target service: $service_name"
            echo ""

            local patch_version minor_version major_version
            patch_version="$(_bump_semver "$IMAGE_VERSION" "patch")"
            minor_version="$(_bump_semver "$IMAGE_VERSION" "minor")"
            major_version="$(_bump_semver "$IMAGE_VERSION" "major")"

            echo "Version options:"
            if [ -n "$patch_version" ] && [ -n "$minor_version" ] && [ -n "$major_version" ]; then
                echo "  [1] Patch  ($IMAGE_VERSION -> $patch_version)"
                echo "  [2] Minor  ($IMAGE_VERSION -> $minor_version)"
                echo "  [3] Major  ($IMAGE_VERSION -> $major_version)"
                echo "  [4] Enter manually"
            else
                echo "  [1] Patch  (unavailable for '$IMAGE_VERSION')"
                echo "  [2] Minor  (unavailable for '$IMAGE_VERSION')"
                echo "  [3] Major  (unavailable for '$IMAGE_VERSION')"
                echo "  [4] Enter manually"
            fi
            echo ""

            local default_choice="1"
            if [ -z "$patch_version" ] || [ -z "$minor_version" ] || [ -z "$major_version" ]; then
                default_choice="4"
            fi

            local version_choice
            if [[ -r /dev/tty ]]; then
                read -r -p "Choose version option [$default_choice]: " version_choice < /dev/tty
            else
                read -r -p "Choose version option [$default_choice]: " version_choice
            fi
            version_choice="${version_choice:-$default_choice}"

            local new_version=""
            case "$version_choice" in
                1) [ -n "$patch_version" ] && new_version="$patch_version" ;;
                2) [ -n "$minor_version" ] && new_version="$minor_version" ;;
                3) [ -n "$major_version" ] && new_version="$major_version" ;;
                4)
                    local manual_version
                    if [[ -r /dev/tty ]]; then
                        read -r -p "Enter version tag: " manual_version < /dev/tty
                    else
                        read -r -p "Enter version tag: " manual_version
                    fi
                    new_version="$manual_version"
                    ;;
                *) [ -n "$patch_version" ] && new_version="$patch_version" ;;
            esac

            if [ -z "$new_version" ] || [ "$new_version" = "$IMAGE_VERSION" ]; then
                echo "Version unchanged."
                break
            fi

            echo ""
            echo "Pulling image: $IMAGE_NAME:$new_version"
            if docker pull "$IMAGE_NAME:$new_version"; then
                echo "[OK] Image pulled successfully"
            else
                echo "[ERROR] Image pull failed"
                read -r -p "Continue anyway? (y/N): " continue_anyway
                if [[ ! "$continue_anyway" =~ ^[Yy]$ ]]; then
                    break
                fi
            fi

            echo ""
            echo "Updating service: $service_name"
            docker service update --image "$IMAGE_NAME:$new_version" "$service_name"

            if [ -f "$env_file" ]; then
                update_env_values "$env_file" "IMAGE_VERSION" "$new_version"
                echo "[OK] Saved IMAGE_VERSION=$new_version to .env"
            fi
            IMAGE_VERSION="$new_version"

            echo ""
            echo "[OK] Service update initiated."
            echo "Monitor progress with: docker service ps $service_name"
            ;;
        ${MENU_SCALE})
            echo "[SCALE] Scale Services"
            echo ""

            local services
            services="$(_stack_service_names "$STACK_NAME")"
            if [ -z "$services" ]; then
                echo "No services found for stack: $STACK_NAME"
                break
            fi

            echo "Which service do you want to scale?"
            local index=1
            while IFS= read -r svc; do
                [ -z "$svc" ] && continue
                echo "${index}) ${svc}"
                index=$((index + 1))
            done <<< "$services"
            echo ""

            local scale_choice
            if [[ -r /dev/tty ]]; then
                read -r -p "Your choice (1-$((index - 1))): " scale_choice < /dev/tty
            else
                read -r -p "Your choice (1-$((index - 1))): " scale_choice
            fi

            if ! [[ "$scale_choice" =~ ^[0-9]+$ ]] || [ "$scale_choice" -lt 1 ] || [ "$scale_choice" -ge "$index" ]; then
                echo "Invalid choice"
                break
            fi

            local selected_service
            selected_service=$(printf '%s\n' "$services" | sed -n "${scale_choice}p")

            local replicas
            if [[ -r /dev/tty ]]; then
                read -r -p "Number of replicas: " replicas < /dev/tty
            else
                read -r -p "Number of replicas: " replicas
            fi

            if ! [[ "$replicas" =~ ^[0-9]+$ ]]; then
                echo "Invalid replica count"
                break
            fi

            docker service scale "${selected_service}=$replicas"

            if [ "$selected_service" = "$(_primary_service_name)" ] && [ -f "$env_file" ]; then
                if [ "${STACK_FAMILY:-api}" = "nginx" ]; then
                    update_env_values "$env_file" "NGINX_REPLICAS" "$replicas"
                    echo "Saved NGINX_REPLICAS=$replicas to .env"
                else
                    update_env_values "$env_file" "API_REPLICAS" "$replicas"
                    echo "Saved API_REPLICAS=$replicas to .env"
                fi
            fi
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
            echo "🔄 Re-running setup wizard..."
            echo ""
            "${PROJECT_ROOT:-.}/setup/setup-wizard.sh"
            # Reload .env after wizard
            load_root_env "${PROJECT_ROOT:-.}"
            ;;
        ${MENU_SETUP_SECRETS})
            echo "🔑 Manage Docker Secrets"
            echo ""

            # Derive prefix from SECRET_PREFIX or STACK_NAME
            local prefix_upper
            prefix_upper=$(echo "${SECRET_PREFIX:-$STACK_NAME}" | tr '[:lower:]' '[:upper:]' | sed 's/[^A-Z0-9]/_/g')

            local DB_PASSWORD_SECRET="${prefix_upper}DB_PASSWORD"
            local ADMIN_API_KEY_SECRET="${prefix_upper}ADMIN_API_KEY"
            local BACKUP_RESTORE_API_KEY_SECRET="${prefix_upper}BACKUP_RESTORE_API_KEY"
            local BACKUP_DELETE_API_KEY_SECRET="${prefix_upper}BACKUP_DELETE_API_KEY"

            echo "📋 Secret Status:"
            echo "  Prefix: ${prefix_upper}*"
            echo "------------------------"

            if docker secret inspect "$DB_PASSWORD_SECRET" &>/dev/null; then
                echo "✅ ${DB_PASSWORD_SECRET}"
            else
                echo "❌ ${DB_PASSWORD_SECRET} (missing)"
            fi

            if docker secret inspect "$ADMIN_API_KEY_SECRET" &>/dev/null; then
                echo "✅ ${ADMIN_API_KEY_SECRET}"
            else
                echo "❌ ${ADMIN_API_KEY_SECRET} (missing)"
            fi

            if docker secret inspect "$BACKUP_RESTORE_API_KEY_SECRET" &>/dev/null; then
                echo "✅ ${BACKUP_RESTORE_API_KEY_SECRET}"
            else
                echo "❌ ${BACKUP_RESTORE_API_KEY_SECRET} (missing)"
            fi

            if docker secret inspect "$BACKUP_DELETE_API_KEY_SECRET" &>/dev/null; then
                echo "✅ ${BACKUP_DELETE_API_KEY_SECRET}"
            else
                echo "❌ ${BACKUP_DELETE_API_KEY_SECRET} (missing)"
            fi

            echo ""
            echo "What would you like to do?"
            echo "1) Create secrets from secrets.env file (recommended)"
            echo "2) Create secrets interactively"
            echo "3) List all secrets"
            echo "4) Back to main menu"
            echo ""
            if [[ -r /dev/tty ]]; then
                read -r -p "Your choice (1-4): " secret_choice < /dev/tty
            else
                read -r -p "Your choice (1-4): " secret_choice
            fi

            case $secret_choice in
                1)
                    echo ""
                    echo "🔍 Checking for running stack..."

                    if docker stack ls --format "{{.Name}}" 2>/dev/null | grep -q "^${STACK_NAME}$"; then
                        echo "⚠️  WARNING: Stack '$STACK_NAME' is currently running!"
                        echo ""
                        echo "Secrets cannot be updated while in use by a running stack."
                        echo ""
                        if [[ -r /dev/tty ]]; then
                            read -r -p "Remove stack before updating secrets? (y/N): " REMOVE_STACK < /dev/tty
                        else
                            read -r -p "Remove stack before updating secrets? (y/N): " REMOVE_STACK
                        fi

                        if [[ "$REMOVE_STACK" =~ ^[Yy]$ ]]; then
                            echo ""
                            echo "Removing stack: $STACK_NAME"
                            docker stack rm "$STACK_NAME"

                            echo "Waiting for stack to be fully removed..."
                            while docker stack ls --format "{{.Name}}" 2>/dev/null | grep -q "^${STACK_NAME}$"; do
                                echo -n "."
                                sleep 2
                            done
                            echo ""
                            echo "✅ Stack removed successfully"
                            echo ""

                            create_secrets_from_env_file "secrets.env" "${SCRIPT_DIR}/templates/secrets.env.template" "$prefix_upper"
                        else
                            echo ""
                            echo "⚠️  Secret creation cancelled."
                            echo "Stop the stack manually with: docker stack rm $STACK_NAME"
                            echo "Then run this option again."
                        fi
                    else
                        echo "✅ No running stack found"
                        echo ""
                        create_secrets_from_env_file "secrets.env" "${SCRIPT_DIR}/templates/secrets.env.template" "$prefix_upper"
                    fi
                    ;;
                2)
                    echo ""
                    echo "🔍 Checking for running stack..."

                    if docker stack ls --format "{{.Name}}" 2>/dev/null | grep -q "^${STACK_NAME}$"; then
                        echo "⚠️  WARNING: Stack '$STACK_NAME' is currently running!"
                        echo ""
                        echo "Secrets cannot be updated while in use by a running stack."
                        echo ""
                        if [[ -r /dev/tty ]]; then
                            read -r -p "Remove stack before updating secrets? (y/N): " REMOVE_STACK < /dev/tty
                        else
                            read -r -p "Remove stack before updating secrets? (y/N): " REMOVE_STACK
                        fi

                        if [[ "$REMOVE_STACK" =~ ^[Yy]$ ]]; then
                            echo ""
                            echo "Removing stack: $STACK_NAME"
                            docker stack rm "$STACK_NAME"

                            echo "Waiting for stack to be fully removed..."
                            while docker stack ls --format "{{.Name}}" 2>/dev/null | grep -q "^${STACK_NAME}$"; do
                                echo -n "."
                                sleep 2
                            done
                            echo ""
                            echo "✅ Stack removed successfully"
                            echo ""

                            create_docker_secrets "$DB_PASSWORD_SECRET" "$ADMIN_API_KEY_SECRET" "$BACKUP_RESTORE_API_KEY_SECRET" "$BACKUP_DELETE_API_KEY_SECRET"
                        else
                            echo ""
                            echo "⚠️  Secret creation cancelled."
                            echo "Stop the stack manually with: docker stack rm $STACK_NAME"
                            echo "Then run this option again."
                        fi
                    else
                        echo "✅ No running stack found"
                        echo ""
                        create_docker_secrets "$DB_PASSWORD_SECRET" "$ADMIN_API_KEY_SECRET" "$BACKUP_RESTORE_API_KEY_SECRET" "$BACKUP_DELETE_API_KEY_SECRET"
                    fi
                    ;;
                3)
                    list_docker_secrets
                    ;;
                4)
                    echo "Returning to main menu..."
                    ;;
                *)
                    echo "Invalid choice"
                    ;;
            esac
            ;;
        ${MENU_RESTORE_ENV})
            echo "📁 Quick Restore from Saved .env"
            echo "==================================="
            echo ""
            echo "This restores your deployment configuration from a saved .env file."
            echo "The saved .env file will be copied to the project root."
            echo ""

            local saved_env_path=""
            read -p "Path to saved .env file: " saved_env_path

            if [ -z "$saved_env_path" ]; then
                echo "❌ No path provided. Skipping."
            elif [ ! -f "$saved_env_path" ]; then
                echo "❌ File not found: $saved_env_path"
            else
                # Backup existing .env if present
                if [ -f "$env_file" ]; then
                    local backup_name="${env_file}.backup.$(date +%Y%m%d_%H%M%S)"
                    cp "$env_file" "$backup_name"
                    echo "📦 Backed up existing .env to: $backup_name"
                fi

                cp "$saved_env_path" "$env_file"
                echo "✅ Restored .env from: $saved_env_path"
                echo ""
                echo "Next steps:"
                echo "  1) Rebuild swarm-stack.yml:  ${MENU_BUILD_STACK}) Rebuild swarm-stack.yml"
                if _profile_requires_secrets; then
                    echo "  2) Restore secrets (if saved): ${MENU_RESTORE_SECRETS}) Restore from secrets.env"
                    echo "  3) Deploy:                   ${MENU_DEPLOY}) Deploy to Docker Swarm"
                else
                    echo "  2) Deploy:                   ${MENU_DEPLOY}) Deploy to Docker Swarm"
                fi
                echo ""

                # Reload the environment
                load_root_env "${PROJECT_ROOT:-.}"
            fi
            ;;
        ${MENU_RESTORE_SECRETS})
            echo "🔐 Quick Restore from Saved secrets.env"
            echo "========================================"
            echo ""
            echo "This creates Docker secrets from a saved secrets.env file."
            echo "WARNING: The stack must be stopped before updating secrets."
            echo ""

            local saved_secrets_path=""
            read -p "Path to saved secrets.env file: " saved_secrets_path

            if [ -z "$saved_secrets_path" ]; then
                echo "❌ No path provided. Skipping."
            elif [ ! -f "$saved_secrets_path" ]; then
                echo "❌ File not found: $saved_secrets_path"
            else
                # Derive prefix
                local prefix_upper
                prefix_upper=$(echo "${SECRET_PREFIX:-$STACK_NAME}" | tr '[:lower:]' '[:upper:]' | sed 's/[^A-Z0-9]/_/g')

                # Check for running stack
                if docker stack ls --format "{{.Name}}" 2>/dev/null | grep -q "^${STACK_NAME}$"; then
                    echo "⚠️  WARNING: Stack '$STACK_NAME' is currently running!"
                    echo ""
                    read -r -p "Remove stack before creating secrets? (y/N): " REMOVE_STACK

                    if [[ "$REMOVE_STACK" =~ ^[Yy]$ ]]; then
                        echo ""
                        echo "Removing stack: $STACK_NAME"
                        docker stack rm "$STACK_NAME"

                        echo "Waiting for stack to be fully removed..."
                        while docker stack ls --format "{{.Name}}" 2>/dev/null | grep -q "^${STACK_NAME}$"; do
                            echo -n "."
                            sleep 2
                        done
                        echo ""
                        echo "✅ Stack removed"
                        echo ""

                        create_secrets_from_env_file "$saved_secrets_path" "${SCRIPT_DIR}/templates/secrets.env.template" "$prefix_upper"
                    else
                        echo "⚠️  Secret creation cancelled. Stop the stack first."
                    fi
                else
                    create_secrets_from_env_file "$saved_secrets_path" "${SCRIPT_DIR}/templates/secrets.env.template" "$prefix_upper"
                fi
            fi
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
        ${MENU_TOGGLE_ADMIN_UI})
            if [ "$DB_TYPE" = "postgresql" ]; then
                local current_replicas="${PGADMIN_REPLICAS:-0}"
                local target_replicas=1
                if [ "$current_replicas" != "0" ]; then
                    target_replicas=0
                fi
                docker service scale "${STACK_NAME}_pgadmin=$target_replicas"
                update_env_values "$env_file" "PGADMIN_REPLICAS" "$target_replicas"
                if [ "$target_replicas" -eq 1 ]; then
                    local pgadmin_login="${PGADMIN_EMAIL:-admin@example.com}"
                    echo "✅ pgAdmin enabled. Access at: ${PGADMIN_URL}"
                    echo "   Login: ${pgadmin_login} / (from secret ${SECRET_PREFIX}_db_ui_admin_password)"
                else
                    echo "✅ pgAdmin disabled (replicas=0)"
                fi
            elif [ "$DB_TYPE" = "mongodb" ]; then
                local current_replicas="${MONGO_EXPRESS_REPLICAS:-0}"
                local target_replicas=1
                if [ "$current_replicas" != "0" ]; then
                    target_replicas=0
                fi
                docker service scale "${STACK_NAME}_mongo-express=$target_replicas"
                update_env_values "$env_file" "MONGO_EXPRESS_REPLICAS" "$target_replicas"
                if [ "$target_replicas" -eq 1 ]; then
                    local mongo_user="${MONGO_EXPRESS_USERNAME:-dbadmin}"
                    echo "✅ Mongo Express enabled. Access at: ${MONGO_EXPRESS_URL}"
                    echo "   Login: ${mongo_user} / (from secret ${SECRET_PREFIX}_db_ui_admin_password)"
                else
                    echo "✅ Mongo Express disabled (replicas=0)"
                fi
            fi
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
