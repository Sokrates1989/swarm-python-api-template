#!/bin/bash
# Stack deployment module

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
    
    read -p "Deploy now? (Y/n): " CONFIRM_DEPLOY
    if [[ "$CONFIRM_DEPLOY" =~ ^[Nn]$ ]]; then
        echo "Deployment cancelled."
        return 1
    fi
    
    echo ""
    echo "Deploying stack..."
    
    # Use temporary file to avoid process substitution issues
    local temp_config=$(mktemp)
    docker-compose -f "$stack_file_abs" --env-file "$env_file" config > "$temp_config"
    docker stack deploy -c "$temp_config" "$stack_name"
    local deploy_status=$?
    rm -f "$temp_config"
    
    if [ $deploy_status -ne 0 ]; then
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
