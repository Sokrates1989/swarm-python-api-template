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
        if _service_replicas_healthy "${stack_name}_api"; then
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
        local MENU_SETUP_SECRETS=$MENU_NEXT
        MENU_NEXT=$((MENU_NEXT+1))
        local MENU_RESTORE_ENV=$MENU_NEXT
        MENU_NEXT=$((MENU_NEXT+1))
        local MENU_RESTORE_SECRETS=$MENU_NEXT
        MENU_NEXT=$((MENU_NEXT+1))
        local MENU_SETUP_AUTH=""
        if declare -F setup_auth_provider >/dev/null; then
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
        echo "  ${MENU_SETUP_SECRETS}) Manage Docker secrets"
        echo "  ${MENU_RESTORE_ENV}) Quick restore from saved .env"
        echo "  ${MENU_RESTORE_SECRETS}) Quick restore from saved secrets.env"
        if [ -n "$MENU_SETUP_AUTH" ]; then
            echo "  ${MENU_SETUP_AUTH}) Configure Authentication (Cognito/Keycloak)"
        fi
        echo ""

        echo "Deployment:"
        echo "  ${MENU_DEPLOY}) Deploy to Docker Swarm"
        echo "  ${MENU_STATUS}) Check deployment status"
        echo "  ${MENU_LOGS}) View service logs"
        echo ""

        echo "Management:"
        echo "  ${MENU_UPDATE_IMAGE}) Update API image"
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

        case $choice in
        ${MENU_DEPLOY})
            echo "🚀 Deploying to Docker Swarm..."
            echo ""
            echo "⚠️  Make sure you have:"
            echo "   - Created Docker secrets"
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
            echo "📜 Service Logs"
            echo ""
            echo "Which service logs do you want to view?"
            echo "1) API"
            echo "2) Database"
            echo "3) Redis"
            echo "4) All"
            echo ""
            if [[ -r /dev/tty ]]; then
                read -r -p "Your choice (1-4): " log_choice < /dev/tty
            else
                read -r -p "Your choice (1-4): " log_choice
            fi

            case $log_choice in
                1)
                    docker service logs -f "${STACK_NAME}_api"
                    ;;
                2)
                    if [ "$DB_TYPE" = "mongodb" ]; then
                        docker service logs -f "${STACK_NAME}_mongodb"
                    elif [ "$DB_TYPE" = "neo4j" ]; then
                        docker service logs -f "${STACK_NAME}_neo4j"
                    else
                        docker service logs -f "${STACK_NAME}_postgres"
                    fi
                    ;;
                3)
                    docker service logs -f "${STACK_NAME}_redis"
                    ;;
                4)
                    local services
                    services=$(docker service ls --filter "label=com.docker.stack.namespace=${STACK_NAME}" --format '{{.Name}}' 2>/dev/null)
                    if [ -z "$services" ]; then
                        echo "No services found for stack: $STACK_NAME"
                    else
                        for svc in $services; do
                            echo ""
                            echo "===== $svc ====="
                            docker service logs --tail 50 "$svc" 2>/dev/null || true
                        done
                    fi
                    ;;
                *)
                    echo "Invalid choice"
                    ;;
            esac
            ;;
        ${MENU_UPDATE_IMAGE})
            echo "🔄 Update API Image"
            echo "========================"
            echo ""
            echo "  Current image: $IMAGE_NAME:$IMAGE_VERSION"
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
                1)
                    if [ -n "$patch_version" ]; then
                        new_version="$patch_version"
                    fi
                    ;;
                2)
                    if [ -n "$minor_version" ]; then
                        new_version="$minor_version"
                    fi
                    ;;
                3)
                    if [ -n "$major_version" ]; then
                        new_version="$major_version"
                    fi
                    ;;
                4)
                    local manual_version
                    if [[ -r /dev/tty ]]; then
                        read -r -p "Enter version tag: " manual_version < /dev/tty
                    else
                        read -r -p "Enter version tag: " manual_version
                    fi
                    new_version="$manual_version"
                    ;;
                *)
                    if [ -n "$patch_version" ]; then
                        new_version="$patch_version"
                    fi
                    ;;
            esac

            if [ -z "$new_version" ]; then
                echo "Version unchanged."
                break
            fi

            if [ "$new_version" = "$IMAGE_VERSION" ]; then
                echo "Version unchanged."
                break
            fi

            echo ""
            echo "Pulling image: $IMAGE_NAME:$new_version"
            if docker pull "$IMAGE_NAME:$new_version"; then
                echo "✅ Image pulled successfully"
            else
                echo "❌ Image pull failed"
                read -r -p "Continue anyway? (y/N): " continue_anyway
                if [[ ! "$continue_anyway" =~ ^[Yy]$ ]]; then
                    break
                fi
            fi

            echo ""
            echo "Updating service..."
            docker service update --image "$IMAGE_NAME:$new_version" "${STACK_NAME}_api"

            # Persist to .env
            if [ -f "$env_file" ]; then
                update_env_values "$env_file" "IMAGE_VERSION" "$new_version"
                echo "✅ Saved IMAGE_VERSION=$new_version to .env"
            fi
            IMAGE_VERSION="$new_version"

            echo ""
            echo "✅ Service update initiated!"
            echo "Monitor progress with: docker service ps ${STACK_NAME}_api"
            ;;
        ${MENU_SCALE})
            echo "📊 Scale Services"
            echo ""
            echo "Which service do you want to scale?"
            echo "1) API"
            echo "2) Redis"
            if [ "$DB_TYPE" = "postgresql" ]; then
                echo "3) PostgreSQL"
            elif [ "$DB_TYPE" = "mongodb" ]; then
                echo "3) MongoDB"
            elif [ "$DB_TYPE" = "neo4j" ]; then
                echo "3) Neo4j"
            fi
            echo ""
            if [[ -r /dev/tty ]]; then
                read -r -p "Your choice: " scale_choice < /dev/tty
            else
                read -r -p "Your choice: " scale_choice
            fi

            if [[ -r /dev/tty ]]; then
                read -r -p "Number of replicas: " replicas < /dev/tty
            else
                read -r -p "Number of replicas: " replicas
            fi

            case $scale_choice in
                1)
                    docker service scale "${STACK_NAME}_api=$replicas"
                    if [ -f "$env_file" ]; then
                        update_env_values "$env_file" "API_REPLICAS" "$replicas"
                        echo "Saved API_REPLICAS=$replicas to .env"
                    fi
                    ;;
                2)
                    docker service scale "${STACK_NAME}_redis=$replicas"
                    ;;
                3)
                    if [ "$DB_TYPE" = "neo4j" ]; then
                        docker service scale "${STACK_NAME}_neo4j=$replicas"
                    elif [ "$DB_TYPE" = "mongodb" ]; then
                        docker service scale "${STACK_NAME}_mongodb=$replicas"
                    else
                        docker service scale "${STACK_NAME}_postgres=$replicas"
                    fi
                    ;;
                *)
                    echo "Invalid choice"
                    ;;
            esac
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
                echo "  2) Restore secrets (if saved): ${MENU_RESTORE_SECRETS}) Restore from secrets.env"
                echo "  3) Deploy:                   ${MENU_DEPLOY}) Deploy to Docker Swarm"
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
            echo "🔨 Rebuilding swarm-stack.yml..."
            echo ""
            local build_script="${PROJECT_ROOT:-.}/scripts/build-site-stack.sh"
            if [ -x "$build_script" ]; then
                "$build_script"
            else
                echo "⚠️  build-site-stack.sh not found or not executable."
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
