#!/bin/bash
# ==============================================================================
# felix-release.sh - Strict felix-new Swarm release operations menu
# ==============================================================================
#
# Routes the exact candidate profile through the digest-bound Python state
# machine. Generic and protected legacy deployments never enter this path.
# ==============================================================================

FELIX_RELEASE_MODULE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FELIX_RELEASE_REPOSITORY_ROOT="$(cd "${FELIX_RELEASE_MODULE_DIR}/../.." && pwd)"
FELIX_RELEASE_CLI="${FELIX_RELEASE_REPOSITORY_ROOT}/scripts/felix_deploy.py"

# _felix_release_run
# Runs one explicit candidate-only release state transition.
#
# Arguments:
#   $1 - command: prepare-data, preflight, deploy, health, rollback,
#        drill-rollback, status, or logs.
#
# Returns:
#   The strict Python release CLI exit code.
#
# Side effects:
#   Depends on the selected command. Deploy and rollback operations change only
#   the felix-new candidate stack; no operation targets a legacy stack/hostname.
_felix_release_run() {
    local command="$1"

    if ! declare -F _is_felix_candidate_profile >/dev/null ||
        ! _is_felix_candidate_profile; then
        echo "[ERROR] Strict Felix release operations require the exact felix-new profile."
        return 1
    fi
    if [ ! -f "$FELIX_RELEASE_CLI" ]; then
        echo "[ERROR] Strict Felix release CLI is missing."
        return 1
    fi
    if ! command -v python3 >/dev/null 2>&1; then
        echo "[ERROR] python3 is required for strict Felix release operations."
        return 1
    fi

    python3 "$FELIX_RELEASE_CLI" \
        --root "$FELIX_RELEASE_REPOSITORY_ROOT" \
        "$command"
}

# felix_release_menu
# Presents the complete candidate deploy, health, rollback, and evidence flow.
#
# Arguments:
#   None.
#
# Returns:
#   0 when the operator returns to the main menu.
#
# Side effects:
#   Runs only the explicitly selected strict candidate operation.
felix_release_menu() {
    local choice
    while true; do
        echo ""
        echo "Felix strict release"
        echo "  1) Prepare exact candidate data directories"
        echo "  2) Run strict preflight"
        echo "  3) Backup, deploy candidate, and require strict health"
        echo "  4) Run strict health and legacy continuity checks"
        echo "  5) Run WebApp/API automatic rollback and data-continuity drill"
        echo "  6) Show sanitized candidate status"
        echo "  7) Show redacted candidate WebApp/API logs"
        echo "  8) Explicitly rollback candidate WebApp/API services"
        echo "  0) Back"
        read -r -p "Felix release choice (0-8): " choice

        case "$choice" in
            1) _felix_release_run prepare-data || true ;;
            2) _felix_release_run preflight || true ;;
            3) _felix_release_run deploy || true ;;
            4) _felix_release_run health || true ;;
            5) _felix_release_run drill-rollback || true ;;
            6) _felix_release_run status || true ;;
            7) _felix_release_run logs || true ;;
            8) _felix_release_run rollback || true ;;
            0) return 0 ;;
            *) echo "[WARN] Enter a value from 0 through 8." ;;
        esac
    done
}
