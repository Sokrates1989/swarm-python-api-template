#!/bin/bash
# ==============================================================================
# health-check.sh - Stack health check module
# ==============================================================================
#
# This module verifies that a deployed Docker Swarm stack is healthy. It discovers
# services from Docker stack labels when the deployment exists, then falls back to
# the profile primary service while a stack is still being configured.
#
# Functions:
#   check_deployment_health - Run comprehensive health checks on a stack
#
# Dependencies:
#   - Docker Swarm with the target stack deployed
#   - curl (optional, for HTTP health endpoint testing)
#
# ==============================================================================

# ------------------------------------------------------------------------------
# _health_primary_service_suffix
# ------------------------------------------------------------------------------
# Resolves the expected primary service suffix for the active deployment profile.
# Nginx profiles default to nginx; API profiles keep api for backward
# compatibility.
#
# Arguments:
#   None. Reads PRIMARY_SERVICE and STACK_FAMILY from the environment.
#
# Outputs:
#   Service suffix without the stack name prefix.
#
# Returns:
#   0 always.
# ------------------------------------------------------------------------------
_health_primary_service_suffix() {
    if [ -n "${PRIMARY_SERVICE:-}" ]; then
        echo "$PRIMARY_SERVICE"
        return 0
    fi

    if [ "${STACK_FAMILY:-api}" = "nginx" ]; then
        echo "nginx"
        return 0
    fi

    echo "api"
}

# ------------------------------------------------------------------------------
# _health_stack_services
# ------------------------------------------------------------------------------
# Lists concrete Docker service names for a stack. Docker labels are preferred so
# profile-specific services such as nginx are handled automatically. When no
# services are deployed yet, the function falls back to the expected primary
# service name.
#
# Arguments:
#   $1 - stack_name: Docker stack name.
#   $2 - db_type: deployment database type used only for legacy fallback.
#
# Outputs:
#   One Docker service name per line.
#
# Returns:
#   0 always.
# ------------------------------------------------------------------------------
_health_stack_services() {
    local stack_name="$1"
    local db_type="$2"
    local services

    services=$(docker service ls --filter "label=com.docker.stack.namespace=${stack_name}" --format '{{.Name}}' 2>/dev/null || true)
    if [ -n "$services" ]; then
        printf '%s\n' $services
        return 0
    fi

    printf '%s_%s\n' "$stack_name" "$(_health_primary_service_suffix)"

    if [ "${STACK_FAMILY:-api}" != "nginx" ]; then
        printf '%s_redis\n' "$stack_name"
        case "$db_type" in
            postgresql) printf '%s_postgres\n' "$stack_name" ;;
            mongodb) printf '%s_mongodb\n' "$stack_name" ;;
            neo4j) printf '%s_neo4j\n' "$stack_name" ;;
        esac
    fi
}

# ------------------------------------------------------------------------------
# _health_service_label
# ------------------------------------------------------------------------------
# Converts a Docker service name into the suffix shown to operators in health
# output.
#
# Arguments:
#   $1 - stack_name: Docker stack name.
#   $2 - service_name: full Docker service name.
#
# Outputs:
#   Service suffix when the stack prefix matches, otherwise the original name.
#
# Returns:
#   0 always.
# ------------------------------------------------------------------------------
_health_service_label() {
    local stack_name="$1"
    local service_name="$2"
    local prefix="${stack_name}_"

    if [[ "$service_name" == "$prefix"* ]]; then
        echo "${service_name#$prefix}"
        return 0
    fi

    echo "$service_name"
}

# ------------------------------------------------------------------------------
# _health_log_pattern
# ------------------------------------------------------------------------------
# Selects useful log keywords for each service family so nginx-only deployments
# do not search for database or migration messages.
#
# Arguments:
#   $1 - service_label: service suffix such as nginx, api, redis, or postgres.
#
# Outputs:
#   Extended grep pattern.
#
# Returns:
#   0 always.
# ------------------------------------------------------------------------------
_health_log_pattern() {
    local service_label="$1"

    case "$service_label" in
        nginx)
            echo 'ready|start|error|failed|warn|notice|emerg|crit|alert|complete|exit'
            ;;
        redis)
            echo 'ready|accept|error|failed|warn'
            ;;
        postgres|mongodb)
            echo 'ready|accept|error|failed|connection|warn'
            ;;
        neo4j)
            echo 'started|remote|error|failed|warn'
            ;;
        *)
            echo 'startup|ready|error|failed|connection|database|migration|warn'
            ;;
    esac
}

# ------------------------------------------------------------------------------
# _health_response_is_ok
# ------------------------------------------------------------------------------
# Checks whether an HTTP health response looks successful for API and nginx
# profiles.
#
# Arguments:
#   $1 - response: response body from curl.
#
# Returns:
#   0 when the response indicates health, 1 otherwise.
# ------------------------------------------------------------------------------
_health_response_is_ok() {
    local response="$1"
    echo "$response" | grep -Eiq '(^|[^a-z])(ok|healthy)([^a-z]|$)|"status"[[:space:]]*:[[:space:]]*"?OK"?'
}

# ------------------------------------------------------------------------------
# check_deployment_health
# ------------------------------------------------------------------------------
# Waits up to 3 minutes for all stack services to reach desired replicas, then
# prints status, task details, relevant log excerpts, and the HTTP /health result
# when Traefik exposes a domain.
#
# Arguments:
#   $1 - stack_name: Docker stack name.
#   $2 - db_type: database type, or none.
#   $3 - proxy_type: traefik or none.
#   $4 - site_domain: domain for the HTTP health endpoint.
#   $5 - wait_seconds: optional extra seconds before log inspection.
#
# Returns:
#   0 always because this function is informational for the interactive menu.
# ------------------------------------------------------------------------------
check_deployment_health() {
    local stack_name="$1"
    local db_type="$2"
    local proxy_type="$3"
    local site_domain="$4"
    local wait_seconds="${5:-0}"
    local services

    echo "[HEALTH] Health Check"
    echo "====================="
    echo ""

    services="$(_health_stack_services "$stack_name" "$db_type")"

    local max_wait=180
    local check_interval=5
    local elapsed=0
    local all_healthy=false

    echo "Waiting for all services to reach desired replicas (max 3 minutes)..."
    echo ""

    while [ "$elapsed" -lt "$max_wait" ] && [ "$all_healthy" = false ]; do
        all_healthy=true

        while IFS= read -r service_name; do
            [ -z "$service_name" ] && continue

            local replicas
            replicas=$(docker service ls --filter "name=${service_name}" --format '{{.Replicas}}' 2>/dev/null | head -n 1)

            if [[ "$replicas" =~ ^([0-9]+)/([0-9]+) ]]; then
                local current="${BASH_REMATCH[1]}"
                local desired="${BASH_REMATCH[2]}"
                local label
                label="$(_health_service_label "$stack_name" "$service_name")"

                if [ "$current" != "$desired" ]; then
                    all_healthy=false
                    echo "[${elapsed}s] [WAIT] Service $label: $replicas"
                fi
            else
                all_healthy=false
            fi
        done <<< "$services"

        if [ "$all_healthy" = false ]; then
            sleep "$check_interval"
            elapsed=$((elapsed + check_interval))
        fi
    done

    echo ""
    echo "Final service status:"
    echo ""
    docker stack services "$stack_name"
    echo ""

    while IFS= read -r service_name; do
        [ -z "$service_name" ] && continue

        local replicas
        replicas=$(docker service ls --filter "name=${service_name}" --format '{{.Replicas}}' 2>/dev/null | head -n 1)
        local label
        label="$(_health_service_label "$stack_name" "$service_name")"

        if [[ "$replicas" =~ ^([0-9]+)/([0-9]+) ]]; then
            local current="${BASH_REMATCH[1]}"
            local desired="${BASH_REMATCH[2]}"

            if [ "$current" != "$desired" ]; then
                echo "[WARN] Service $label has unequal replicas: $replicas"
            else
                echo "[OK] Service $label is healthy: $replicas"
            fi
        else
            echo "[WARN] Service $label was not found in Docker service list."
        fi
    done <<< "$services"

    echo ""
    echo "Service task details:"
    echo ""
    while IFS= read -r service_name; do
        [ -z "$service_name" ] && continue
        echo "[INFO] ${service_name}:"
        docker service ps "$service_name" --no-trunc 2>&1 || true
        echo ""
    done <<< "$services"

    if [ "$all_healthy" = false ]; then
        echo ""
        echo "[WARN] Some services did not reach desired replicas within 3 minutes."
        echo ""
    fi

    echo ""
    echo "Checking service logs..."
    echo ""

    if [ "$wait_seconds" -gt 0 ]; then
        echo "[WAIT] Waiting $wait_seconds seconds for services to initialize..."
        sleep "$wait_seconds"
        echo ""
    fi

    while IFS= read -r service_name; do
        [ -z "$service_name" ] && continue
        local label pattern
        label="$(_health_service_label "$stack_name" "$service_name")"
        pattern="$(_health_log_pattern "$label")"

        echo "--- ${label} logs ---"
        docker service logs "$service_name" --tail 50 2>&1 | grep -Ei "$pattern" || echo "No relevant log entries found"
        echo ""
    done <<< "$services"

    if [ "$proxy_type" = "traefik" ] && [ -n "$site_domain" ]; then
        echo "Testing HTTP health endpoint..."
        echo "URL: https://${site_domain}/health"
        echo ""

        local health_response
        health_response=$(curl -s -k "https://${site_domain}/health" 2>&1 || echo "Connection failed")

        if _health_response_is_ok "$health_response"; then
            echo "[OK] HTTP health check passed"
            echo "Response: $health_response"
        else
            echo "[WARN] HTTP health check failed or is not ready yet"
            echo "Response: $health_response"
            echo ""
            echo "Wait a few more minutes and try: curl https://${site_domain}/health"
        fi
    fi

    local primary_service="${stack_name}_$(_health_primary_service_suffix)"

    echo ""
    echo "[SUMMARY] Health Check Summary"
    echo "=============================="
    echo ""
    echo "Stack checked: $stack_name"
    echo ""
    echo "Useful commands:"
    echo "  docker stack services $stack_name          # Check service status"
    echo "  docker service logs $primary_service      # View primary service logs"
    echo "  docker service ps $primary_service        # Check primary service tasks"
    echo ""

    return 0
}
