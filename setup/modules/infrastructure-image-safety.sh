#!/bin/bash
# ============================================================================
# infrastructure-image-safety.sh - Infrastructure update safety gates
# ============================================================================
#
# Owns operator guidance, PostgreSQL backup acknowledgement, exact-target
# vulnerability scanning, and broad-channel confirmation. The calling menu
# owns inventory/selection, while repository adapters own deployment effects.
#
# Dependencies:
#   - menu-image-audit.sh scanner and installation-help functions.
#   - menu-infrastructure-images.sh terminal input helper at execution time.
# ============================================================================

# Guard against multiple sourcing.
if [ -n "${_INFRASTRUCTURE_IMAGE_SAFETY_LOADED:-}" ]; then
    return 0 2>/dev/null || true
fi
_INFRASTRUCTURE_IMAGE_SAFETY_LOADED=1

# show_infrastructure_update_policy
# Explains the reusable compatibility, security, backup, and ignore policy.
show_infrastructure_update_policy() {
    echo ""
    echo "Infrastructure update policy"
    echo "============================"
    echo ""
    echo "Compatible maintenance refresh"
    echo "  - Resolves the profile's existing track (for example 16-alpine)."
    echo "  - Stores the selected registry manifest as an immutable digest."
    echo "  - Scans the target when Docker Scout or Trivy is available."
    echo "  - Deploys through the existing health and rollback boundary."
    echo ""
    echo "Security handling"
    echo "  - Fixable HIGH/CRITICAL findings remain visible even when an update"
    echo "    reminder is ignored. Targets with findings are not recommended."
    echo "  - An ignore applies to one exact target digest only. A newer digest"
    echo "    automatically restores the reminder."
    echo ""
    echo "Stateful and major-version handling"
    echo "  - PostgreSQL same-major refreshes require an explicit backup checkpoint."
    echo "  - PostgreSQL major changes are never offered as an image-only update."
    echo "    They require dump/restore, pg_upgrade, or logical replication testing."
    echo "  - Redis major changes require persistence and client-compatibility review."
    echo ""
    echo "Official guidance:"
    echo "  PostgreSQL: https://www.postgresql.org/docs/current/upgrading.html"
    echo "  Postgres image: https://hub.docker.com/_/postgres"
    echo "  Redis: https://redis.io/docs/latest/operate/oss_and_stack/install/upgrade/"
    echo "  Redis versions: https://redis.io/docs/latest/operate/oss_and_stack/install/version-mgmt/"
    echo "  pgAdmin releases: https://www.pgadmin.org/docs/pgadmin4/latest/release_notes.html"
}

# _postgres_backup_checkpoint
# Requires an explicit data-safety decision before a same-major database image
# refresh. It does not pretend a filesystem copy is a verified logical backup.
#
# Returns:
#   0 when the operator accepts the checkpoint; otherwise 1.
_postgres_backup_checkpoint() {
    local choice=""
    local confirm=""

    echo ""
    echo "PostgreSQL data-safety checkpoint"
    echo "---------------------------------"
    echo "This target remains inside the configured PostgreSQL major track."
    echo "PostgreSQL documents same-major releases as storage-compatible, but a"
    echo "recent restore-tested logical backup is still the recommended boundary."
    echo ""
    echo "  1) A recent verified backup exists; continue (recommended)"
    echo "  2) Continue without creating a new backup"
    echo "  3) Show official backup/upgrade guidance and cancel"
    echo "  0) Cancel"
    _infrastructure_read "Your choice [1]: " choice
    choice="${choice:-1}"
    case "$choice" in
        1) return 0 ;;
        2)
            echo "[WARN] Continuing without a new backup weakens recovery options."
            _infrastructure_read "Continue this same-major refresh? (y/N): " confirm
            [[ "$confirm" =~ ^[Yy]$ ]]
            ;;
        3)
            echo "https://www.postgresql.org/docs/current/backup-dump.html"
            echo "https://www.postgresql.org/docs/current/upgrading.html"
            return 1
            ;;
        *) return 1 ;;
    esac
}

# _preflight_infrastructure_target
# Scans one immutable target before deployment and requires explicit acceptance
# when scanning is unavailable, fails, or finds fixable high-severity issues.
#
# Arguments:
#   $1 - Exact target image reference.
#
# Returns:
#   0 when the target is clean or explicitly accepted; otherwise 1.
_preflight_infrastructure_target() {
    local reference="$1"
    local scanner=""
    local status=0
    local confirm=""

    if docker scout version >/dev/null 2>&1; then
        scanner='docker-scout'
        _scan_with_docker_scout "$reference" || status=$?
    elif command -v trivy >/dev/null 2>&1; then
        scanner='trivy'
        _scan_with_trivy "$reference" || status=$?
    else
        echo "[WARN] No Docker Scout or Trivy target scan is available."
        _show_docker_scout_install_help
        _show_trivy_install_help
        _infrastructure_read "Continue without a target scan? (y/N): " confirm
        [[ "$confirm" =~ ^[Yy]$ ]]
        return
    fi
    if [ "$status" -eq 0 ]; then
        echo "[OK] ${scanner} found no fixable HIGH/CRITICAL target findings."
        return 0
    fi
    if [ "$status" -eq 2 ]; then
        echo "[WARN] The target still contains fixable HIGH/CRITICAL findings."
    else
        echo "[WARN] ${scanner} could not complete the target scan."
    fi
    _infrastructure_read "Continue with this target anyway? (y/N): " confirm
    [[ "$confirm" =~ ^[Yy]$ ]]
}

# _confirm_broad_infrastructure_track
# Requires an extra decision for a broad latest channel that can cross the
# management tool's major version even though application data is external.
#
# Arguments:
#   $1 - Compatibility track.
#   $2 - State kind.
#
# Returns:
#   0 for a constrained track or explicit acceptance; otherwise 1.
_confirm_broad_infrastructure_track() {
    local track="$1"
    local state_kind="$2"
    local confirm=""

    if [ "$track" != "latest" ]; then
        return 0
    fi
    echo "[WARN] The 'latest' channel is broad and may cross a major version."
    if [ "$state_kind" = "management-ui" ]; then
        echo "       This updates the management UI, not the PostgreSQL data image."
    fi
    _infrastructure_read "Continue with this broad-channel refresh? (y/N): " confirm
    [[ "$confirm" =~ ^[Yy]$ ]]
}
