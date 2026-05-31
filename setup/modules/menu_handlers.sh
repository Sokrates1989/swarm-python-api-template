#!/bin/bash

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

# _env_value_or_default
# Reads a dotenv key with a fallback default value.
#
# Arguments:
# - $1: env file path
# - $2: key name
# - $3: default value
# Output:
# - prints the resolved value
_env_value_or_default() {
    local env_file="$1"
    local key="$2"
    local default_value="$3"

    if [ ! -f "$env_file" ]; then
        echo "$default_value"
        return 0
    fi

    local line
    line=$(grep "^${key}=" "$env_file" 2>/dev/null | head -n 1 || true)
    if [ -z "$line" ]; then
        echo "$default_value"
        return 0
    fi

    echo "${line#*=}" | tr -d '"' | tr -d '\r'
}

# _stack_running
# Checks if a Docker stack is running.
#
# Arguments:
# - $1: stack name
_stack_running() {
    local stack_name="$1"
    docker stack ls --format '{{.Name}}' 2>/dev/null | grep -qx "${stack_name}"
}

# show_deployment_overview
# Displays a boxed deployment overview for the current stack.
#
# Arguments:
# - $1: env file path
show_deployment_overview() {
    local env_file="${1:-.env}"
    local stack_name
    stack_name="$(_env_value_or_default "$env_file" "STACK_NAME" "api_production")"
    local proxy_type
    proxy_type="$(_env_value_or_default "$env_file" "PROXY_TYPE" "none")"
    local db_type
    db_type="$(_env_value_or_default "$env_file" "DB_TYPE" "postgresql")"
    local api_url
    api_url="$(_env_value_or_default "$env_file" "API_URL" "api.example.com")"
    local image_name
    image_name="$(_env_value_or_default "$env_file" "IMAGE_NAME" "your-username/your-api-name")"
    local image_version
    image_version="$(_env_value_or_default "$env_file" "IMAGE_VERSION" "latest")"

    local stack_state="not running"
    if _stack_running "$stack_name"; then
        stack_state="running"
    fi

    local ok_icon="✅"
    local off_icon="⏹️"
    local stack_status="${off_icon} not running"
    local image_icon="${off_icon}"
    if [ "$stack_state" = "running" ]; then
        stack_status="${ok_icon} running"
        image_icon="${ok_icon}"
    fi

    _box_rule
    _box_line "Deployment Overview"
    _box_rule
    _box_line "Stack    : ${stack_name} (${stack_status})"
    _box_line "Proxy    : ${proxy_type}"
    _box_line "DB Type  : ${db_type}"
    if [ -n "$api_url" ]; then
        _box_line "Domain   : ${api_url}"
    fi
    _box_line "Images   :"
    _box_line_list "${image_icon} ${image_name}:${image_version}"
    _box_rule
    echo ""
}

show_main_menu() {
    # show_main_menu
    # Main interactive menu loop.
    # Notes:
    # - Expects quick-start.sh to have sourced required modules and set STACK_NAME/API_URL/DB_TYPE/PROXY_TYPE/IMAGE_NAME/IMAGE_VERSION.
    local choice

    while true; do
        local MENU_NEXT=1
        local MENU_SETUP_WIZARD=$MENU_NEXT
        MENU_NEXT=$((MENU_NEXT+1))
        local MENU_SETUP_SECRETS=$MENU_NEXT
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

        local MENU_CICD=$MENU_NEXT
        MENU_NEXT=$((MENU_NEXT+1))

        local MENU_EXIT=$MENU_NEXT

        echo ""
        echo "================ Main Menu ================"
        echo ""
        if declare -F _box_rule >/dev/null; then
            show_deployment_overview ".env"
        fi

        echo "Setup:"
        echo "  ${MENU_SETUP_WIZARD}) Re-run setup wizard"
        echo "  ${MENU_SETUP_SECRETS}) Manage Docker secrets"
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
        echo ""

        echo "CI/CD:"
        echo "  ${MENU_CICD}) GitHub Actions CI/CD helper"
        echo ""
        echo "  ${MENU_EXIT}) Exit"
        echo ""

        if [[ -r /dev/tty ]]; then
            read -r -p "Your choice (1-${MENU_EXIT}): " choice < /dev/tty
        else
            read -r -p "Your choice (1-${MENU_EXIT}): " choice
        fi

        if [ -n "$MENU_SETUP_AUTH" ] && [ "$choice" = "$MENU_SETUP_AUTH" ]; then
            setup_auth_provider

            # Show updated status
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

            STACK_FILE="$(pwd)/swarm-stack.yml"
            deploy_stack "$STACK_NAME" "$STACK_FILE"
            ;;
        ${MENU_STATUS})
            echo "🏥 Running deployment health check..."
            echo ""
            check_deployment_health "$STACK_NAME" "$DB_TYPE" "$PROXY_TYPE" "$API_URL"
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
                    if [ "$DB_TYPE" = "neo4j" ]; then
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
            echo ""
            if [[ -r /dev/tty ]]; then
                read -r -p "Enter new image version [$IMAGE_VERSION]: " new_version < /dev/tty
            else
                read -r -p "Enter new image version [$IMAGE_VERSION]: " new_version
            fi
            new_version="${new_version:-$IMAGE_VERSION}"

            echo ""
            echo "Pulling image: $IMAGE_NAME:$new_version"
            docker pull "$IMAGE_NAME:$new_version"

            echo ""
            echo "Updating service..."
            docker service update --image "$IMAGE_NAME:$new_version" "${STACK_NAME}_api"

            if [ -f .env ]; then
                update_env_values ".env" "IMAGE_VERSION" "$new_version"
                echo "Saved IMAGE_VERSION=$new_version to .env"
            else
                echo "⚠️  .env not found; skipping persistence of IMAGE_VERSION"
            fi

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
                    if [ -f .env ]; then
                        update_env_values ".env" "API_REPLICAS" "$replicas"
                        echo "Saved API_REPLICAS=$replicas to .env"
                    fi
                    ;;
                2)
                    docker service scale "${STACK_NAME}_redis=$replicas"
                    if [ -f .env ]; then
                        update_env_values ".env" "REDIS_REPLICAS" "$replicas"
                        echo "Saved REDIS_REPLICAS=$replicas to .env"
                    fi
                    ;;
                3)
                    if [ "$DB_TYPE" = "neo4j" ]; then
                        docker service scale "${STACK_NAME}_neo4j=$replicas"
                        if [ -f .env ]; then
                            update_env_values ".env" "NEO4J_REPLICAS" "$replicas"
                            echo "Saved NEO4J_REPLICAS=$replicas to .env"
                        fi
                    else
                        docker service scale "${STACK_NAME}_postgres=$replicas"
                        if [ -f .env ]; then
                            update_env_values ".env" "POSTGRES_REPLICAS" "$replicas"
                            echo "Saved POSTGRES_REPLICAS=$replicas to .env"
                        fi
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
            echo "⚠️  WARNING: This will remove all services in the stack."
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
            ./setup/setup-wizard.sh
            ;;
        ${MENU_SETUP_SECRETS})
            echo "🔑 Manage Docker Secrets"
            echo ""

            STACK_NAME_UPPER=$(echo "$STACK_NAME" | tr '[:lower:]' '[:upper:]' | sed 's/[^A-Z0-9]/_/g')

            DB_PASSWORD_SECRET="${STACK_NAME_UPPER}_DB_PASSWORD"
            ADMIN_API_KEY_SECRET="${STACK_NAME_UPPER}_ADMIN_API_KEY"
            BACKUP_RESTORE_API_KEY_SECRET="${STACK_NAME_UPPER}_BACKUP_RESTORE_API_KEY"
            BACKUP_DELETE_API_KEY_SECRET="${STACK_NAME_UPPER}_BACKUP_DELETE_API_KEY"

            echo "📋 Current Secret Status:"
            echo "------------------------"

            if docker secret inspect "$DB_PASSWORD_SECRET" &>/dev/null; then
                echo "✅ Database password secret exists"
            else
                echo "❌ Database password secret missing"
            fi

            if docker secret inspect "$ADMIN_API_KEY_SECRET" &>/dev/null; then
                echo "✅ Admin API key secret exists"
            else
                echo "❌ Admin API key secret missing"
            fi

            if docker secret inspect "$BACKUP_RESTORE_API_KEY_SECRET" &>/dev/null; then
                echo "✅ Backup restore API key secret exists"
            else
                echo "❌ Backup restore API key secret missing"
            fi

            if docker secret inspect "$BACKUP_DELETE_API_KEY_SECRET" &>/dev/null; then
                echo "✅ Backup delete API key secret exists"
            else
                echo "❌ Backup delete API key secret missing"
            fi

            echo ""
            echo "What would you like to do?"
            echo "1) Create/update all secrets"
            echo "2) List all secrets"
            echo "3) Back to main menu"
            echo ""
            if [[ -r /dev/tty ]]; then
                read -r -p "Your choice (1-3): " secret_choice < /dev/tty
            else
                read -r -p "Your choice (1-3): " secret_choice
            fi

            case $secret_choice in
                1)
                    echo ""
                    echo "🔍 Checking for running stack..."

                    if docker stack ls --format "{{.Name}}" | grep -q "^${STACK_NAME}$"; then
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
                            while docker stack ls --format "{{.Name}}" | grep -q "^${STACK_NAME}$"; do
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
                2)
                    list_docker_secrets
                    ;;
                3)
                    echo "Returning to main menu..."
                    ;;
                *)
                    echo "Invalid choice"
                    ;;
            esac
            ;;
        ${MENU_CICD})
            run_ci_cd_github_helper
            ;;
        ${MENU_EXIT})
            echo "👋 Goodbye!"
            exit 0
            ;;
        *)
            echo "❌ Invalid choice"
            ;;
        esac

        echo ""
    done
}
