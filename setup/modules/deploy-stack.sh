#!/bin/bash
# ==============================================================================
# deploy-stack.sh - Docker Swarm stack deployment module
# ==============================================================================
#
# This module handles deploying the swarm-stack.yml to Docker Swarm. It resolves
# absolute paths, checks for existing stacks (via stack-conflict-check.sh), and
# performs the actual "docker stack deploy" with .env variable interpolation.
#
# Functions:
#   deploy_stack - Deploy the stack to Swarm after confirmation
#
# Dependencies:
#   - stack-conflict-check.sh (check_stack_conflict)
#   - Docker Compose plugin (docker-compose config)
#   - Docker Swarm initialized
#
# ==============================================================================

# ------------------------------------------------------------------------------
# deploy_stack
# ------------------------------------------------------------------------------
# Deploys a Docker Swarm stack using docker-compose config for variable
# interpolation. Prompts for confirmation and checks for existing stacks.
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
    
    echo "🚀 Deploying Stack"
    echo "=================="
    echo ""
    echo "Stack name: $stack_name"
    echo "Stack file: $stack_file"
    echo ""
    
    # Check for existing stack and offer to remove it
    check_stack_conflict "$stack_name"
    
    read -p "Deploy now? (Y/n): " CONFIRM_DEPLOY
    if [[ "$CONFIRM_DEPLOY" =~ ^[Nn]$ ]]; then
        echo "Deployment cancelled."
        return 1
    fi
    
    echo ""
    echo "Deploying stack..."

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
        echo "❌ Neither docker-compose nor 'docker compose' is available"
        return 1
    fi

    local stack_file_name
    stack_file_name="$(basename "$stack_file_abs")"

    docker stack deploy -c <(
        cd "$stack_dir" \
        && "${compose_cmd[@]}" -f "$stack_file_name" config
    ) "$stack_name"
    
    if [ $? -ne 0 ]; then
        echo "❌ Deployment failed"
        return 1
    fi
    
    echo ""
    echo "✅ Stack deployed successfully"
    echo ""
    echo ""
    
    echo "📋 Deployment Summary"
    echo "===================="
    echo ""
    echo "Stack deployed: $stack_name"
    echo ""
    echo "Useful commands:"
    echo "  docker stack services $stack_name          # Check service status"
    echo "  docker service logs ${stack_name}_api      # View API logs"
    echo "  docker service ps ${stack_name}_api        # Check API tasks"
    echo "  docker stack rm $stack_name                # Remove stack"
    echo ""
    echo "💡 Tip: Run health checks with the health-check.sh module"
    echo ""
    
    return 0
}
