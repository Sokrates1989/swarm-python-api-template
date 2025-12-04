#!/bin/bash
# ==============================================================================
# health-check.sh - Stack health check module
# ==============================================================================
#
# This module verifies that a deployed Docker Swarm stack is healthy. It waits
# for services to reach desired replica counts, inspects logs for errors, and
# optionally tests the API health endpoint via curl.
#
# Functions:
#   check_deployment_health - Run comprehensive health checks on a stack
#
# Dependencies:
#   - Docker Swarm with the target stack deployed
#   - curl (optional, for API health endpoint testing)
#
# ==============================================================================

# ------------------------------------------------------------------------------
# check_deployment_health
# ------------------------------------------------------------------------------
# Waits up to 3 minutes for all stack services to become healthy, then prints
# status, relevant log excerpts, and (if Traefik is used) tests the API /health
# endpoint.
#
# Arguments:
#   $1 - stack_name: Docker stack name
#   $2 - db_type: "postgresql" or "neo4j"
#   $3 - proxy_type: "traefik" or "none"
#   $4 - api_url: domain for API health endpoint
#   $5 - wait_seconds: (optional) extra seconds to wait before log inspection
#
# Returns:
#   0 always (informational output only)
# ------------------------------------------------------------------------------
check_deployment_health() {
    local stack_name="$1"
    local db_type="$2"
    local proxy_type="$3"
    local api_url="$4"
    local wait_seconds="${5:-0}"  # Default to 0 if not provided
    
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
            else
                echo "✅ Service $service is healthy: $replicas"
            fi
        fi
    done
    
    # Show detailed task status for all services
    echo ""
    echo "Service task details:"
    echo ""
    for service in "${services[@]}"; do
        local service_name="${stack_name}_${service}"
        echo "ℹ️  ${service_name}:"
        docker service ps "$service_name" --no-trunc
        echo ""
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

    # Wait for services to initialize (if configured)
    if [ "$wait_seconds" -gt 0 ]; then
        echo "⏳ Waiting $wait_seconds seconds for services to initialize..."
        sleep "$wait_seconds"
        echo ""
    fi
    
    # Check API logs (increased to 50 lines to capture connection success)
    echo "--- API Logs ---"
    docker service logs "${stack_name}_api" --tail 50 2>&1 | grep -i "startup\|ready\|error\|failed\|connection\|database\|migration" || echo "No relevant log entries found"
    echo ""
    
    # Check database logs
    if [ "$db_type" = "postgresql" ]; then
        echo "--- PostgreSQL Logs ---"
        docker service logs "${stack_name}_postgres" --tail 30 2>&1 | grep -i "ready\|accept\|error\|failed\|connection" || echo "No relevant log entries found"
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
    echo "📋 Health Check Summary"
    echo "======================="
    echo ""
    echo "Stack checked: $stack_name"
    echo ""
    echo "Useful commands:"
    echo "  docker stack services $stack_name          # Check service status"
    echo "  docker service logs ${stack_name}_api      # View API logs"
    echo "  docker service ps ${stack_name}_api        # Check API tasks"
    echo ""
    
    return 0
}
