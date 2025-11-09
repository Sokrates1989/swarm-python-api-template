#!/bin/bash
# Stack deployment and health check module

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
    
    return 0
}

check_deployment_health() {
    local stack_name="$1"
    local db_type="$2"
    local proxy_type="$3"
    local api_url="$4"
    
    echo "🏥 Health Check"
    echo "==============="
    echo ""
    
    # Define services to check
    local services=("api" "redis")
    if [ "$db_type" = "postgresql" ]; then
        services+=("postgres")
    elif [ "$db_type" = "neo4j" ]; then
        services+=("neo4j")
    fi
    
    # Wait for services to become healthy (max 3 minutes)
    local max_wait=180  # 3 minutes
    local check_interval=5
    local elapsed=0
    local all_healthy=false
    
    echo "Waiting for all services to become healthy (max 3 minutes)..."
    echo ""
    
    while [ $elapsed -lt $max_wait ] && [ "$all_healthy" = false ]; do
        all_healthy=true
        
        for service in "${services[@]}"; do
            local service_name="${stack_name}_${service}"
            local replicas=$(docker service ls --filter "name=${service_name}" --format "{{.Replicas}}" 2>/dev/null)
            
            if [[ "$replicas" =~ ^([0-9]+)/([0-9]+) ]]; then
                local current="${BASH_REMATCH[1]}"
                local desired="${BASH_REMATCH[2]}"
                
                if [ "$current" != "$desired" ]; then
                    all_healthy=false
                    echo "[${elapsed}s] ⏳ Service $service: $replicas (waiting...)"
                fi
            fi
        done
        
        if [ "$all_healthy" = false ]; then
            sleep $check_interval
            elapsed=$((elapsed + check_interval))
        fi
    done
    
    # Final status check
    echo ""
    echo "Final service status:"
    echo ""
    docker stack services "$stack_name"
    echo ""
    
    # Check each service
    for service in "${services[@]}"; do
        local service_name="${stack_name}_${service}"
        local replicas=$(docker service ls --filter "name=${service_name}" --format "{{.Replicas}}")
        
        if [[ "$replicas" =~ ^([0-9]+)/([0-9]+) ]]; then
            local current="${BASH_REMATCH[1]}"
            local desired="${BASH_REMATCH[2]}"
            
            if [ "$current" != "$desired" ]; then
                echo "❌ Service $service has unequal replicas: $replicas"
                echo "   Checking service tasks..."
                docker service ps "$service_name" --no-trunc
                echo ""
            else
                echo "✅ Service $service is healthy: $replicas"
            fi
        fi
    done
    
    if [ "$all_healthy" = false ]; then
        echo ""
        echo "⚠️  Some services did not become healthy within 3 minutes."
        echo ""
    fi
    
    # Check logs
    echo ""
    echo "Checking service logs..."
    echo ""
    
    # Check API logs
    echo "--- API Logs ---"
    docker service logs "${stack_name}_api" --tail 20 2>&1 | grep -i "startup\|ready\|error\|failed" || echo "No relevant log entries found"
    echo ""
    
    # Check database logs
    if [ "$db_type" = "postgresql" ]; then
        echo "--- PostgreSQL Logs ---"
        docker service logs "${stack_name}_postgres" --tail 20 2>&1 | grep -i "ready\|accept\|error\|failed" || echo "No relevant log entries found"
        echo ""
    elif [ "$db_type" = "neo4j" ]; then
        echo "--- Neo4j Logs ---"
        docker service logs "${stack_name}_neo4j" --tail 20 2>&1 | grep -i "started\|remote\|error\|failed" || echo "No relevant log entries found"
        echo ""
    fi
    
    # Check Redis logs
    echo "--- Redis Logs ---"
    docker service logs "${stack_name}_redis" --tail 20 2>&1 | grep -i "ready\|accept\|error\|failed" || echo "No relevant log entries found"
    echo ""
    
    # Test API health endpoint
    if [ "$proxy_type" = "traefik" ]; then
        echo "Testing API health endpoint..."
        echo "URL: https://${api_url}/health"
        echo ""
        
        HEALTH_RESPONSE=$(curl -s -k "https://${api_url}/health" 2>&1 || echo "Connection failed")
        
        if echo "$HEALTH_RESPONSE" | grep -q "healthy"; then
            echo "✅ API health check passed"
            echo "Response: $HEALTH_RESPONSE"
        else
            echo "⚠️  API health check failed or not yet ready"
            echo "Response: $HEALTH_RESPONSE"
            echo ""
            echo "This might be normal if the API is still initializing."
            echo "Wait a few more minutes and try: curl https://${api_url}/health"
        fi
    fi
    
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
    
    return 0
}
