#!/bin/bash
# ==============================================================================
# deploy-stack.sh - Docker Swarm stack deployment module
# ==============================================================================
#
# This module handles deploying the rendered swarm-stack.yml to Docker Swarm.
# Existing stacks are updated in place so Swarm can retain prior service specs
# for automatic or explicit rollback. The module never removes a healthy stack
# merely because a deployment with the same name already exists.
#
# Functions:
#   deploy_stack            - Deploy or update the stack after confirmation
#   rollback_stack_services - Roll back prior service specifications
#
# Dependencies:
#   - Docker Compose plugin (docker-compose config)
#   - Docker Swarm initialized
#
# ==============================================================================

# ------------------------------------------------------------------------------
# deploy_stack
# ------------------------------------------------------------------------------
# Deploys a Docker Swarm stack using Docker Compose config for interpolation.
# Existing services are updated in place, preserving Docker's previous service
# specification for rollback.
#
# Arguments:
#   $1 - stack_name: the Docker stack name
#   $2 - stack_file: path to swarm-stack.yml
#
# Returns:
#   0 on success, 1 on failure or cancellation
# ------------------------------------------------------------------------------
deploy_stack() {
    local stack_name="$1"
    local stack_file="$2"
    
    # Resolve absolute paths for stack file and .env
    local stack_dir
    stack_dir="$(cd "$(dirname "$stack_file")" 2>/dev/null && pwd)"
    if [ -z "$stack_dir" ]; then
        stack_dir="$(pwd)"
    fi
    local stack_file_abs="$stack_dir/$(basename "$stack_file")"
    local env_file="$stack_dir/.env"
    
    echo "[DEPLOY] Deploying Stack"
    echo "=================="
    echo ""
    echo "Stack name: $stack_name"
    echo "Stack file: $stack_file"
    echo ""
    
    read -p "Deploy now? (Y/n): " CONFIRM_DEPLOY
    if [[ "$CONFIRM_DEPLOY" =~ ^[Nn]$ ]]; then
        echo "Deployment cancelled."
        return 1
    fi
    
    echo ""
    echo "[DEPLOY] Deploying stack..."

    # Load environment variables from .env file for variable substitution
    if [ -f "$env_file" ]; then
        echo "   Loading environment from: $env_file"
        set -a  # automatically export all variables
        # shellcheck source=/dev/null
        source "$env_file"
        set +a  # stop automatically exporting
    fi

    local compose_cmd
    if command -v docker-compose >/dev/null 2>&1; then
        compose_cmd=(docker-compose)
    elif docker compose version >/dev/null 2>&1; then
        compose_cmd=(docker compose)
    else
        echo "[ERROR] Neither docker-compose nor 'docker compose' is available"
        return 1
    fi

    local stack_file_name
    stack_file_name="$(basename "$stack_file_abs")"

    docker stack deploy \
        --resolve-image always \
        --prune \
        -c <(
        cd "$stack_dir" \
        && "${compose_cmd[@]}" -f "$stack_file_name" config
    ) "$stack_name"
    
    if [ $? -ne 0 ]; then
        echo "[ERROR] Deployment failed"
        return 1
    fi
    
    echo ""
    echo "[OK] Stack deployed successfully"
    echo ""
    echo ""
    
    echo "[SUMMARY] Deployment Summary"
    echo "===================="
    echo ""
    echo "Stack deployed: $stack_name"
    local service_name="api"
    if [ "${STACK_FAMILY:-api}" = "nginx" ]; then
        service_name="nginx"
    fi
    echo ""
    echo "Useful commands:"
    echo "  docker stack services $stack_name          # Check service status"
    echo "  docker service logs ${stack_name}_${service_name}      # View service logs"
    echo "  docker service ps ${stack_name}_${service_name}        # Check service tasks"
    echo "  Use the quick-start rollback option to restore prior service specs"
    echo "  docker stack rm $stack_name                # Remove stack"
    echo ""
    echo "[TIP] Run health checks with the health-check.sh module"
    echo ""
    
    return 0
}

# ------------------------------------------------------------------------------
# _rollback_stack_service_names
# ------------------------------------------------------------------------------
# Lists services owned by one Docker stack through Docker's namespace label.
#
# Arguments:
#   $1 - stack_name: exact Docker stack name.
#
# Outputs:
#   One service name per line.
#
# Returns:
#   Docker service-list status.
# ------------------------------------------------------------------------------
_rollback_stack_service_names() {
    local stack_name="$1"

    docker service ls \
        --filter "label=com.docker.stack.namespace=${stack_name}" \
        --format '{{.Name}}'
}

# ------------------------------------------------------------------------------
# rollback_stack_services
# ------------------------------------------------------------------------------
# Requests Docker to restore the previous service specification for every
# service in a selected stack. Services without a previous specification are
# reported and left unchanged.
#
# Arguments:
#   $1 - stack_name: exact Docker stack name.
#
# Returns:
#   0 when at least one rollback starts and none fail; 1 on cancellation, an
#   absent stack, or any Docker rollback failure.
#
# Side effects:
#   Mutates service specifications only after default-yes confirmation.
# ------------------------------------------------------------------------------
rollback_stack_services() {
    local stack_name="$1"
    local services=""
    local confirmation=""
    local service_name=""
    local rolled_back=0
    local failures=0

    services="$(_rollback_stack_service_names "$stack_name")"
    if [ -z "$services" ]; then
        echo "[ERROR] No services found for stack: ${stack_name}"
        return 1
    fi
    echo ""
    echo "Rollback Docker Swarm services"
    echo "=============================="
    echo "Stack: ${stack_name}"
    echo "Docker will restore each service's previous retained specification."
    echo ""
    printf '%s\n' "$services" | sed 's/^/  - /'
    echo ""
    read -r -p "Start this rollback? (Y/n): " confirmation
    if [[ "$confirmation" =~ ^[Nn]$ ]]; then
        echo "Rollback cancelled."
        return 1
    fi
    while IFS= read -r service_name; do
        [ -n "$service_name" ] || continue
        echo "[ROLLBACK] ${service_name}"
        if docker service rollback "$service_name"; then
            rolled_back=$((rolled_back + 1))
        else
            failures=$((failures + 1))
            echo "[WARN] ${service_name} has no usable previous spec or rollback failed."
        fi
    done <<< "$services"
    echo ""
    echo "Rollback requests started: ${rolled_back}; failures: ${failures}"
    [ "$rolled_back" -gt 0 ] && [ "$failures" -eq 0 ]
}
