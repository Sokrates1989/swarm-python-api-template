#!/bin/bash
# Stack deployment module

deploy_stack() {
    local stack_name="$1"
    local stack_file="$2"
    local env_file="${stack_file%/*}/.env"
    
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
    docker stack deploy -c <(docker-compose -f "$stack_file" config) "$stack_name"
    
    if [ $? -ne 0 ]; then
        echo "❌ Deployment failed"
        return 1
    fi
    
    echo ""
    echo "✅ Stack deployed successfully"
    echo ""
    echo "⏳ Waiting 15 seconds for services to initialize..."
    sleep 15
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
