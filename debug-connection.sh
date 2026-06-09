#!/bin/bash
# Debug script to check database connection configuration

echo "==================================="
echo "Database Connection Debug Script"
echo "==================================="
echo ""

# Get the API container ID
CONTAINER_ID=$(docker ps --filter "name=python-api-template_api" --format "{{.ID}}" | head -n 1)

if [ -z "$CONTAINER_ID" ]; then
    echo "❌ No running API container found"
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
echo "Testing: python-api-template_postgres"
docker exec $CONTAINER_ID sh -c "getent hosts python-api-template_postgres || echo 'Cannot resolve python-api-template_postgres'"
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
docker stack services python-api-template
echo ""

echo "🔗 Network Connectivity Test:"
echo "=============================="
echo "Testing PostgreSQL connection..."
docker exec $CONTAINER_ID sh -c "nc -zv python-api-template_postgres 5432 2>&1 || echo 'Connection failed'"
echo ""

echo "📝 Recent API Logs:"
echo "==================="
docker service logs python-api-template_api --tail 30 2>&1 | grep -E "database|connection|error|DB_" || echo "No relevant logs found"
echo ""

echo "🔐 Checking Secrets:"
echo "==================="
docker exec $CONTAINER_ID sh -c "ls -la /run/secrets/ 2>/dev/null || echo 'No secrets directory'"
echo ""

echo "Debug complete!"
