#!/bin/bash
# ==============================================================================
# menu-overview.sh - Shared managed-service deployment overview
# ==============================================================================
#
# Discovers every service owned by the configured stack and renders compact
# plain and boxed summaries. A running stack is authoritative; before first
# deployment, the generated stack file supplies the configured service list.
# No application name or fixed service inventory is embedded here.
#
# Dependencies:
#   - Docker CLI for live stack state.
#   - menu_formatting.sh for boxed output.
#   - site_helpers.sh for safe root dotenv reads.
# ==============================================================================

# Guard against multiple sourcing.
if [ -n "${_MENU_OVERVIEW_LOADED:-}" ]; then
    return 0 2>/dev/null || true
fi
_MENU_OVERVIEW_LOADED=1

# Load color-aware box primitives when this module is sourced directly.
MENU_OVERVIEW_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "${MENU_OVERVIEW_DIR}/menu_formatting.sh" ]; then
    # shellcheck source=/dev/null
    source "${MENU_OVERVIEW_DIR}/menu_formatting.sh"
fi

# ------------------------------------------------------------------------------
# _stack_running
# ------------------------------------------------------------------------------
# Checks whether one exact Docker Swarm stack exists.
#
# Arguments:
#   $1 - Stack name.
#
# Returns:
#   0 when the stack exists; otherwise 1.
# ------------------------------------------------------------------------------
_stack_running() {
    local stack_name="$1"

    docker stack ls --format '{{.Name}}' 2>/dev/null |
        grep -qx "$stack_name"
}

# ------------------------------------------------------------------------------
# _replica_count_is_healthy
# ------------------------------------------------------------------------------
# Checks a Docker current/desired replica count without another CLI request.
#
# Arguments:
#   $1 - Replica text such as 1/1.
#
# Returns:
#   0 when current equals a nonzero desired count; otherwise 1.
# ------------------------------------------------------------------------------
_replica_count_is_healthy() {
    local replicas="$1"

    if [[ "$replicas" =~ ^([0-9]+)/([0-9]+)$ ]]; then
        [ "${BASH_REMATCH[2]}" -gt 0 ] &&
            [ "${BASH_REMATCH[1]}" = "${BASH_REMATCH[2]}" ]
        return $?
    fi
    return 1
}

# ------------------------------------------------------------------------------
# _service_replicas_healthy
# ------------------------------------------------------------------------------
# Checks one live Docker service's current and desired replicas.
#
# Arguments:
#   $1 - Full Docker service name.
#
# Returns:
#   0 when the service is healthy; otherwise 1.
# ------------------------------------------------------------------------------
_service_replicas_healthy() {
    local service_name="$1"
    local replicas=""

    replicas="$(docker service ls \
        --filter "name=${service_name}" \
        --format '{{.Replicas}}' 2>/dev/null | head -n 1)"
    _replica_count_is_healthy "$replicas"
}

# ------------------------------------------------------------------------------
# _primary_service_suffix
# ------------------------------------------------------------------------------
# Resolves the profile-declared primary service suffix for fallback displays.
#
# Output:
#   Service suffix without the stack prefix.
# ------------------------------------------------------------------------------
_primary_service_suffix() {
    if [ -n "${PRIMARY_SERVICE:-}" ]; then
        printf '%s' "$PRIMARY_SERVICE"
    elif [ "${STACK_FAMILY:-api}" = "nginx" ]; then
        printf '%s' 'nginx'
    else
        printf '%s' 'api'
    fi
}

# ------------------------------------------------------------------------------
# _deployed_stack_service_records
# ------------------------------------------------------------------------------
# Reads every live service through Docker's stack namespace label.
#
# Arguments:
#   $1 - Stack name.
#
# Output:
#   One full-name|replicas|image record per line.
# ------------------------------------------------------------------------------
_deployed_stack_service_records() {
    local stack_name="$1"

    docker service ls \
        --filter "label=com.docker.stack.namespace=${stack_name}" \
        --format '{{.Name}}|{{.Replicas}}|{{.Image}}' 2>/dev/null || true
}

# ------------------------------------------------------------------------------
# _resolve_overview_image_reference
# ------------------------------------------------------------------------------
# Resolves standard generated-stack image placeholders from the loaded root
# environment. Infrastructure images are already concrete in rendered files.
#
# Arguments:
#   $1 - Image reference from the generated stack.
#
# Output:
#   Best available configured image reference.
# ------------------------------------------------------------------------------
_resolve_overview_image_reference() {
    local image="$1"

    image="${image//\$\{IMAGE_NAME\}/${IMAGE_NAME:-}}"
    image="${image//\$\{IMAGE_VERSION\}/${IMAGE_VERSION:-latest}}"
    image="${image//\$\{WEB_IMAGE_NAME\}/${WEB_IMAGE_NAME:-}}"
    image="${image//\$\{WEB_IMAGE_VERSION\}/${WEB_IMAGE_VERSION:-latest}}"
    printf '%s' "$image"
}

# ------------------------------------------------------------------------------
# _configured_stack_service_records
# ------------------------------------------------------------------------------
# Extracts service/image pairs from the generated Compose file before a stack
# exists. This small reader recognizes only top-level service names and their
# direct image keys; it never attempts to execute or fully parse YAML.
#
# Arguments:
#   $1 - Generated stack path.
#
# Output:
#   One service|configured|image record per line.
# ------------------------------------------------------------------------------
_configured_stack_service_records() {
    local stack_file="$1"
    local service=""
    local replicas=""
    local image=""

    [ -f "$stack_file" ] || return 0
    while IFS='|' read -r service replicas image; do
        [ -n "$service" ] && [ -n "$image" ] || continue
        image="$(_resolve_overview_image_reference "$image")"
        printf '%s|%s|%s\n' "$service" "$replicas" "$image"
    done < <(
        awk '
          /^services:[[:space:]]*$/ { in_services=1; next }
          in_services && /^[^[:space:]#]/ { exit }
          in_services && /^  [A-Za-z0-9_.-]+:[[:space:]]*$/ {
            service=$0
            sub(/^  /, "", service)
            sub(/:[[:space:]]*$/, "", service)
            next
          }
          in_services && service != "" && /^    image:[[:space:]]*/ {
            image=$0
            sub(/^    image:[[:space:]]*/, "", image)
            sub(/^"/, "", image); sub(/"$/, "", image)
            print service "|configured|" image
            service=""
          }
        ' "$stack_file"
    )
}

# ------------------------------------------------------------------------------
# _fallback_stack_service_records
# ------------------------------------------------------------------------------
# Provides release-managed primary/Web records when no rendered stack exists.
#
# Arguments:
#   $1 - Stack name.
#
# Output:
#   One configured service record per available image.
# ------------------------------------------------------------------------------
_fallback_stack_service_records() {
    local stack_name="$1"
    local primary="$(_primary_service_suffix)"

    if [ -n "${IMAGE_NAME:-}" ]; then
        printf '%s|configured|%s:%s\n' \
            "$primary" "$IMAGE_NAME" "${IMAGE_VERSION:-latest}"
    fi
    if [ "${WEB_ENABLED:-false}" = "true" ] &&
        [ -n "${WEB_IMAGE_NAME:-}" ]; then
        printf '%s|configured|%s:%s\n' \
            'web' "$WEB_IMAGE_NAME" "${WEB_IMAGE_VERSION:-latest}"
    fi
}

# ------------------------------------------------------------------------------
# _stack_service_records
# ------------------------------------------------------------------------------
# Selects live, rendered, or minimal fallback records in authority order.
#
# Arguments:
#   $1 - Stack name.
#
# Output:
#   One service-name|replicas-or-configured|image record per line.
# ------------------------------------------------------------------------------
_stack_service_records() {
    local stack_name="$1"
    local records=""
    local stack_file="${PROJECT_ROOT:-.}/swarm-stack.yml"

    records="$(_deployed_stack_service_records "$stack_name")"
    if [ -n "$records" ]; then
        printf '%s\n' "$records"
        return 0
    fi
    records="$(_configured_stack_service_records "$stack_file")"
    if [ -n "$records" ]; then
        printf '%s\n' "$records"
        return 0
    fi
    _fallback_stack_service_records "$stack_name"
}

# ------------------------------------------------------------------------------
# _stack_service_names
# ------------------------------------------------------------------------------
# Lists live service names, falling back to configured stack service suffixes.
#
# Arguments:
#   $1 - Stack name.
#
# Output:
#   One full Docker service name per line.
# ------------------------------------------------------------------------------
_stack_service_names() {
    local stack_name="$1"
    local service=""
    local replicas=""
    local image=""

    while IFS='|' read -r service replicas image; do
        [ -n "$service" ] || continue
        if [[ "$service" == "${stack_name}_"* ]]; then
            printf '%s\n' "$service"
        else
            printf '%s_%s\n' "$stack_name" "$service"
        fi
    done < <(_stack_service_records "$stack_name")
}

# ------------------------------------------------------------------------------
# _stack_services_healthy
# ------------------------------------------------------------------------------
# Requires every live stack service to reach its desired replica count.
#
# Arguments:
#   $1 - Stack name.
#
# Returns:
#   0 when at least one service exists and all are healthy; otherwise 1.
# ------------------------------------------------------------------------------
_stack_services_healthy() {
    local stack_name="$1"
    local service=""
    local replicas=""
    local image=""
    local saw_service=false

    while IFS='|' read -r service replicas image; do
        [ -n "$service" ] || continue
        saw_service=true
        _replica_count_is_healthy "$replicas" || return 1
    done < <(_deployed_stack_service_records "$stack_name")
    [ "$saw_service" = true ]
}

# ------------------------------------------------------------------------------
# _short_overview_image_reference
# ------------------------------------------------------------------------------
# Compacts long immutable digests while retaining repository and evidence type.
#
# Arguments:
#   $1 - Full image reference.
#
# Output:
#   Full tag reference or a digest reference shortened to 12 hash characters.
# ------------------------------------------------------------------------------
_short_overview_image_reference() {
    local image="$1"
    local repository=""
    local digest=""

    if [[ "$image" == *@sha256:* ]]; then
        repository="${image%@sha256:*}"
        digest="${image##*@sha256:}"
        printf '%s@sha256:%s...' "$repository" "${digest:0:12}"
        return 0
    fi
    printf '%s' "$image"
}

# ------------------------------------------------------------------------------
# _service_is_management_surface
# ------------------------------------------------------------------------------
# Identifies a database-administration service without app-specific branches.
#
# Arguments:
#   $1 - Stack service suffix.
#
# Returns:
#   0 for the profile-selected admin UI or known shared admin UI types.
# ------------------------------------------------------------------------------
_service_is_management_surface() {
    local service="$1"

    if [ -n "${APP_ADMIN_UI_TYPE:-}" ] &&
        [ "$service" = "$APP_ADMIN_UI_TYPE" ]; then
        return 0
    fi
    case "$service" in
        pgadmin|mongo-express) return 0 ;;
        *) return 1 ;;
    esac
}

# ------------------------------------------------------------------------------
# _bootstrap_user_cleanup_text
# ------------------------------------------------------------------------------
# Renders a warning only for users known to have been created by bootstrap.
#
# Output:
#   Color-aware reminder text, or nothing when no cleanup is pending.
# ------------------------------------------------------------------------------
_bootstrap_user_cleanup_text() {
    if [ "${KEYCLOAK_BOOTSTRAP_USERS_CLEANUP_PENDING:-}" != "true" ] ||
        [ -z "${KEYCLOAK_BOOTSTRAP_USERS_CLEANUP_NAMES:-}" ]; then
        return 0
    fi
    printf '%s: %s' \
        "$(_menu_colorize warning '[WARN] manual cleanup pending')" \
        "$KEYCLOAK_BOOTSTRAP_USERS_CLEANUP_NAMES"
}

# ------------------------------------------------------------------------------
# _advanced_logging_overview_text
# ------------------------------------------------------------------------------
# Renders the production-safe logging preset for supporting API profiles.
#
# Output:
#   Color-aware status, or nothing when the profile lacks this capability.
# ------------------------------------------------------------------------------
_advanced_logging_overview_text() {
    if ! declare -F profile_supports_advanced_logging >/dev/null 2>&1 ||
        ! profile_supports_advanced_logging; then
        return 0
    fi
    if [ "${ADVANCED_LOGGING_ENABLED:-true}" = "true" ]; then
        _menu_colorize ok '[OK] INFO diagnostics'
    else
        _menu_colorize off '[OFF] WARNING and ERROR only'
    fi
}

# ------------------------------------------------------------------------------
# _database_admin_overview_text
# ------------------------------------------------------------------------------
# Renders configured database-management state from profile capabilities.
#
# Output:
#   Color-aware state, or nothing when the profile has no supported admin UI.
# ------------------------------------------------------------------------------
_database_admin_overview_text() {
    local display_name=""

    if ! declare -F profile_supports_database_admin_toggle >/dev/null 2>&1 ||
        ! profile_supports_database_admin_toggle; then
        return 0
    fi
    display_name="$(database_admin_display_name)"
    if [ "${PGADMIN_ENABLED:-false}" = "true" ]; then
        printf '%s (%s)' \
            "$(_menu_colorize warning "[WARN] ${display_name} enabled")" \
            "replicas=${PGADMIN_REPLICAS:-1}"
    else
        _menu_colorize off "[OFF] ${display_name} disabled"
    fi
}

# ------------------------------------------------------------------------------
# _overview_service_line
# ------------------------------------------------------------------------------
# Formats one managed service record for a human-readable overview.
#
# Arguments:
#   $1 - Stack name.
#   $2 - Service name or full Docker service name.
#   $3 - Replica text or configured sentinel.
#   $4 - Image reference.
#
# Output:
#   Compact status, service, replica, and image text.
# ------------------------------------------------------------------------------
_overview_service_line() {
    local stack_name="$1"
    local service="$2"
    local replicas="$3"
    local image="$4"
    local status='[OFF]'
    local level='off'
    local note=''
    local current=0
    local desired=0

    service="${service#${stack_name}_}"
    if _replica_count_is_healthy "$replicas"; then
        if _service_is_management_surface "$service"; then
            status='[WARN]'
            level='warning'
            note=' [management UI active]'
        else
            status='[OK]'
            level='ok'
        fi
    elif [ "$replicas" != "configured" ]; then
        if [[ "$replicas" =~ ^([0-9]+)/([0-9]+)$ ]]; then
            current="${BASH_REMATCH[1]}"
            desired="${BASH_REMATCH[2]}"
            if [ "$current" -lt "$desired" ]; then
                status='[ERROR]'
                level='error'
            else
                status='[WARN]'
                level='warning'
            fi
        else
            status='[WARN]'
            level='warning'
        fi
    fi
    image="$(_short_overview_image_reference "$image")"
    status="$(_menu_colorize "$level" "$status")"
    printf '%s %s (%s) %s%s' \
        "$status" "$service" "$replicas" "$image" "$note"
}

# ------------------------------------------------------------------------------
# _print_boxed_service_overview
# ------------------------------------------------------------------------------
# Adds every managed service record to the existing overview box.
#
# Arguments:
#   $1 - Stack name.
# ------------------------------------------------------------------------------
_print_boxed_service_overview() {
    local stack_name="$1"
    local service=""
    local replicas=""
    local image=""

    _box_line 'Services :'
    while IFS='|' read -r service replicas image; do
        [ -n "$service" ] || continue
        _box_line_list "$(_overview_service_line \
            "$stack_name" "$service" "$replicas" "$image")"
    done < <(_stack_service_records "$stack_name")
}

# ------------------------------------------------------------------------------
# show_deployment_overview
# ------------------------------------------------------------------------------
# Displays the operations-menu box with profile identity and every managed
# service discovered from this deployment instance.
# ------------------------------------------------------------------------------
show_deployment_overview() {
    local stack_name="${STACK_NAME:-unknown}"
    local stack_status=""
    local logging_status=""
    local database_admin_status=""

    if _stack_running "$stack_name"; then
        if _stack_services_healthy "$stack_name"; then
            stack_status="$(_menu_colorize ok '[OK] healthy')"
        else
            stack_status="$(_menu_colorize error '[ERROR] unhealthy')"
        fi
    else
        stack_status="$(_menu_colorize error '[OFF] not running')"
    fi
    logging_status="$(_advanced_logging_overview_text)"
    database_admin_status="$(_database_admin_overview_text)"
    _box_rule
    _box_line 'Deployment Overview'
    _box_rule
    _box_line "Stack    : ${stack_name} (${stack_status})"
    if [ -n "${DEPLOYMENT_PROFILE_ID:-${BACKEND_APP_ID:-}}" ]; then
        _box_line "Profile  : ${DEPLOYMENT_PROFILE_ID:-${BACKEND_APP_ID}}"
    fi
    if [ -n "${APP_RELEASE_STACK_ID:-}" ]; then
        _box_line "Release  : ${APP_RELEASE_STACK_ID} (floor ${APP_RELEASE_VERSION_FLOOR})"
    fi
    _box_line "Proxy    : ${PROXY_TYPE:-none}"
    _box_line "DB Type  : ${DB_TYPE:-none}"
    if [ -n "${DOMAIN:-}" ]; then
        _box_line "API      : ${DOMAIN}"
    fi
    if [ -n "${WEB_DOMAIN:-}" ]; then
        _box_line "WebApp   : ${WEB_DOMAIN}"
    fi
    if [ -n "$logging_status" ]; then
        _box_line "Logging  : ${logging_status}"
    fi
    if [ -n "$database_admin_status" ]; then
        _box_line "DB Admin : ${database_admin_status}"
    fi
    _print_boxed_service_overview "$stack_name"
    if [ -n "$(_bootstrap_user_cleanup_text)" ]; then
        _box_line "Bootstrap users: $(_bootstrap_user_cleanup_text)"
    fi
    if declare -F show_git_status_line >/dev/null; then
        _box_line "$(show_git_status_line)"
    fi
    _box_rule
    echo ""
}
