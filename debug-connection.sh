#!/bin/bash
# Debug script to check database connection configuration

echo "==================================="
echo "Database Connection Debug Script"
echo "==================================="
echo ""

# Read STACK_NAME from .env if available
ENV_FILE="${1:-.env}"
STACK_NAME=""
if [ -f "$ENV_FILE" ]; then
    STACK_NAME=$(grep "^STACK_NAME=" "$ENV_FILE" 2>/dev/null | head -n 1 | cut -d'=' -f2- | tr -d '"' | tr -d '\r')
fi

# Fallback if no STACK_NAME found
if [ -z "$STACK_NAME" ]; then
    # Try to detect from running stacks
    STACK_NAME=$(docker stack ls --format "{{.Name}}" 2>/dev/null | grep -E "postgres-template|python-api-template" | head -n 1)
fi

if [ -z "$STACK_NAME" ]; then
    echo "❌ Could not determine stack name"
    echo "Usage: $0 [env_file] or ensure .env has STACK_NAME=your_stack_name"
    exit 1
fi

echo "📋 Using stack: $STACK_NAME"
echo ""

# Get the API container ID
CONTAINER_ID=$(docker ps --filter "name=${STACK_NAME}_api" --format "{{.ID}}" | head -n 1)

if [ -z "$CONTAINER_ID" ]; then
    echo "❌ No running API container found for stack: $STACK_NAME"
    echo "Looking for containers with 'api' in the name:"
    docker ps --filter "name=api" --format "table {{.ID}}\t{{.Names}}\t{{.Status}}"
    exit 1
fi

echo "✅ Found API container: $CONTAINER_ID"
echo ""

echo "📋 Environment Variables in Container:"
echo "======================================"
docker exec $CONTAINER_ID env | grep -E "DB_|NEO4J_|REDIS_|STACK_" | sort
echo ""

echo "🔍 Checking DNS Resolution:"
echo "============================"
echo "Testing: ${STACK_NAME}_postgres"
docker exec $CONTAINER_ID sh -c "getent hosts ${STACK_NAME}_postgres || echo 'Cannot resolve ${STACK_NAME}_postgres'"
echo ""

echo "Testing: postgres (service alias)"
docker exec $CONTAINER_ID sh -c "getent hosts postgres || echo 'Cannot resolve postgres'"
echo ""

echo "Testing: tasks.postgres"
docker exec $CONTAINER_ID sh -c "getent hosts tasks.postgres || echo 'Cannot resolve tasks.postgres'"
echo ""

echo "🌐 Network Information:"
echo "======================="
docker exec $CONTAINER_ID sh -c "cat /etc/resolv.conf"
echo ""

echo "📦 Services in Stack:"
echo "===================="
docker stack services "$STACK_NAME"
echo ""

echo "🔗 Network Connectivity Test:"
echo "=============================="
echo "Testing PostgreSQL connection..."
docker exec $CONTAINER_ID sh -c "nc -zv ${STACK_NAME}_postgres 5432 2>&1 || echo 'Connection failed (nc may not be installed in container)'"
echo ""

echo "📝 Recent API Logs:"
echo "==================="
docker service logs "${STACK_NAME}_api" --tail 30 2>&1 | grep -E "database|connection|error|DB_" || echo "No relevant logs found"
echo ""

echo "🔐 Checking Secrets:"
echo "==================="
docker exec $CONTAINER_ID sh -c "ls -la /run/secrets/ 2>/dev/null || echo 'No secrets directory'"
echo ""

echo "Debug complete!"
