#!/bin/bash
# ==============================================================================
# menu-image-audit-profile.sh - Site-profile image audit adapter
# ==============================================================================
#
# Converts the active generic deployment profile and optional live Swarm state
# into the common audit contracts. Application images retain independent
# versions. Infrastructure images retain immutable runtime pins plus explicit
# tracked tags supplied by schema-5 site configs.
#
# Dependencies:
#   - menu-image-actions.sh for managed application records.
#   - menu-image-audit.sh for the shared operator workflow.
#   - menu-image-transaction.sh for verified public override deployment.
# ==============================================================================

# Guard against multiple sourcing.
if [ -n "${_MENU_IMAGE_AUDIT_PROFILE_LOADED:-}" ]; then
    return 0 2>/dev/null || true
fi
_MENU_IMAGE_AUDIT_PROFILE_LOADED=1

_MENU_IMAGE_AUDIT_PROFILE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${_MENU_IMAGE_AUDIT_PROFILE_DIR}/menu-image-audit.sh"
source "${_MENU_IMAGE_AUDIT_PROFILE_DIR}/menu-image-transaction.sh"

# ------------------------------------------------------------------------------
# _live_service_image_reference
# ------------------------------------------------------------------------------
# Resolves one Swarm service's exact image specification, including the digest
# Docker records after registry resolution.
#
# Arguments:
#   $1 - Profile-local service suffix.
#
# Output:
#   Exact live image reference, or no output when the service is absent.
# ------------------------------------------------------------------------------
_live_service_image_reference() {
    local service="$1"
    local stack_name="${STACK_NAME:-}"

    [ -n "$stack_name" ] || return 1
    docker service inspect "${stack_name}_${service}" \
        --format '{{.Spec.TaskTemplate.ContainerSpec.Image}}' 2>/dev/null |
        head -n 1
}

# ------------------------------------------------------------------------------
# _audit_infrastructure_reference
# ------------------------------------------------------------------------------
# Prefers the live digest-bearing image and falls back to the profile pin.
#
# Arguments:
#   $1 - Service suffix.
#   $2 - Profile-pinned image.
#
# Output:
#   Best exact image reference available.
# ------------------------------------------------------------------------------
_audit_infrastructure_reference() {
    local service="$1"
    local pinned="$2"
    local live=""

    live="$(_live_service_image_reference "$service")" || live=""
    printf '%s' "${live:-$pinned}"
}

# ------------------------------------------------------------------------------
# _operator_image_audit_records
# ------------------------------------------------------------------------------
# Emits the common registry-audit record contract for every active-profile
# application image and configured local infrastructure image.
# ------------------------------------------------------------------------------
_operator_image_audit_records() {
    local record=""
    local identifier=""
    local label=""
    local service=""
    local repository=""
    local version=""
    local current=""

    while IFS= read -r record; do
        [ -n "$record" ] || continue
        IFS='|' read -r identifier label service _ _ repository version <<< "$record"
        printf '%s|%s|application|%s|%s|\n' \
            "$identifier" "$label" "$repository" "$version"
    done < <(_managed_release_image_records)
    if [ "${DB_MODE:-local}" = 'local' ] &&
        [ "${APP_REQUIRES_DATABASE:-true}" = 'true' ] &&
        [ -n "${APP_DB_IMAGE:-}" ]; then
        current="$(_audit_infrastructure_reference postgres "$APP_DB_IMAGE")"
        printf 'postgres|PostgreSQL|infrastructure||%s|%s\n' \
            "$current" "${APP_DB_IMAGE_TRACK_TAG:-}"
    fi
    if [ "${APP_REQUIRES_REDIS:-false}" = 'true' ] &&
        [ -n "${APP_REDIS_IMAGE:-}" ]; then
        current="$(_audit_infrastructure_reference redis "$APP_REDIS_IMAGE")"
        printf 'redis|Redis|infrastructure||%s|%s\n' \
            "$current" "${APP_REDIS_IMAGE_TRACK_TAG:-}"
    fi
    if [ -n "${APP_PGADMIN_IMAGE:-}" ]; then
        current="$(_audit_infrastructure_reference pgadmin "$APP_PGADMIN_IMAGE")"
        printf 'pgadmin|pgAdmin|infrastructure||%s|%s\n' \
            "$current" "${APP_PGADMIN_IMAGE_TRACK_TAG:-}"
    fi
}

# ------------------------------------------------------------------------------
# _operator_application_image_references
# ------------------------------------------------------------------------------
# Emits exact configured or live application image references for Docker Scout
# base-image analysis.
# ------------------------------------------------------------------------------
_operator_application_image_references() {
    local record=""
    local service=""
    local repository=""
    local version=""
    local live=""

    while IFS= read -r record; do
        [ -n "$record" ] || continue
        IFS='|' read -r _ _ service _ _ repository version <<< "$record"
        live="$(_live_service_image_reference "$service")" || live=""
        printf '%s\n' "${live:-${repository}:${version}}"
    done < <(_managed_release_image_records)
}

# ------------------------------------------------------------------------------
# _operator_image_security_references
# ------------------------------------------------------------------------------
# Emits exact active image references for vulnerability scanning. A disabled
# pgAdmin management surface is omitted from security evidence until enabled.
# ------------------------------------------------------------------------------
_operator_image_security_references() {
    local current=""

    _operator_application_image_references
    if [ "${DB_MODE:-local}" = 'local' ] &&
        [ "${APP_REQUIRES_DATABASE:-true}" = 'true' ] &&
        [ -n "${APP_DB_IMAGE:-}" ]; then
        current="$(_audit_infrastructure_reference postgres "$APP_DB_IMAGE")"
        printf '%s\n' "$current"
    fi
    if [ "${APP_REQUIRES_REDIS:-false}" = 'true' ] &&
        [ -n "${APP_REDIS_IMAGE:-}" ]; then
        current="$(_audit_infrastructure_reference redis "$APP_REDIS_IMAGE")"
        printf '%s\n' "$current"
    fi
    if [ "${PGADMIN_ENABLED:-false}" = 'true' ] &&
        [ -n "${APP_PGADMIN_IMAGE:-}" ]; then
        current="$(_audit_infrastructure_reference pgadmin "$APP_PGADMIN_IMAGE")"
        printf '%s\n' "$current"
    fi
}

# ------------------------------------------------------------------------------
# _operator_infrastructure_image_records
# ------------------------------------------------------------------------------
# Emits profile-driven infrastructure maintenance records. Exact image values
# may come from a per-deployment override, while compatibility tracks remain
# controlled by the selected reusable site profile.
# ------------------------------------------------------------------------------
_operator_infrastructure_image_records() {
    local current=""

    if [ "${DB_MODE:-local}" = 'local' ] &&
        [ "${APP_REQUIRES_DATABASE:-true}" = 'true' ] &&
        [ -n "${APP_DB_IMAGE:-}" ]; then
        current="$(_audit_infrastructure_reference postgres "$APP_DB_IMAGE")"
        printf 'postgres|PostgreSQL|postgres|POSTGRES_IMAGE|%s|%s|database|%s\n' \
            "$current" \
            "${APP_DB_IMAGE_TRACK_TAG:-}" \
            'https://www.postgresql.org/docs/current/upgrading.html'
    fi
    if [ "${APP_REQUIRES_REDIS:-false}" = 'true' ] &&
        [ -n "${APP_REDIS_IMAGE:-}" ]; then
        current="$(_audit_infrastructure_reference redis "$APP_REDIS_IMAGE")"
        printf 'redis|Redis|redis|REDIS_IMAGE|%s|%s|cache|%s\n' \
            "$current" \
            "${APP_REDIS_IMAGE_TRACK_TAG:-}" \
            'https://redis.io/docs/latest/operate/oss_and_stack/install/version-mgmt/'
    fi
    if [ -n "${APP_PGADMIN_IMAGE:-}" ]; then
        current="$(_audit_infrastructure_reference pgadmin "$APP_PGADMIN_IMAGE")"
        printf 'pgadmin|pgAdmin|pgadmin|PGADMIN_IMAGE|%s|%s|management-ui|%s\n' \
            "$current" \
            "${APP_PGADMIN_IMAGE_TRACK_TAG:-}" \
            'https://www.pgadmin.org/docs/pgadmin4/latest/release_notes.html'
    fi
}

# ------------------------------------------------------------------------------
# _operator_apply_infrastructure_image_update
# ------------------------------------------------------------------------------
# Applies one verified exact infrastructure image through the same protected
# public-environment, renderer, deploy, health, and rollback boundary used by
# application image and runtime quick actions.
#
# Arguments:
#   $1 - Stable infrastructure identifier.
#   $2 - Operator-facing label.
#   $3 - Allowed public exact-image key.
#   $4 - Registry-verified repository@sha256 reference.
#
# Returns:
#   Shared transaction status.
# ------------------------------------------------------------------------------
_operator_apply_infrastructure_image_update() {
    local identifier="$1"
    local label="$2"
    local environment_key="$3"
    local target_reference="$4"
    local transaction_directory=""
    local status=0

    case "$identifier:$environment_key" in
        postgres:POSTGRES_IMAGE|redis:REDIS_IMAGE|pgadmin:PGADMIN_IMAGE) ;;
        *)
            echo "[ERROR] Unsupported infrastructure image assignment."
            return 1
            ;;
    esac
    if ! [[ "$target_reference" =~ ^[a-z0-9][a-z0-9._/-]*@sha256:[a-f0-9]{64}$ ]]; then
        echo "[ERROR] Infrastructure target must be an immutable image digest."
        return 1
    fi
    transaction_directory="$(mktemp -d \
        "${PROJECT_ROOT}/.infrastructure-image-update.XXXXXX")" || return 1
    _apply_profile_environment_update \
        "$transaction_directory" \
        "${label} compatible image refresh" \
        "always" \
        "${environment_key}=${target_reference}" || status=$?
    _clean_release_image_transaction "$transaction_directory"
    return "$status"
}
