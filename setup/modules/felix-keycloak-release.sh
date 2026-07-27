#!/bin/bash
# ==============================================================================
# felix-keycloak-release.sh - Pinned Felix candidate Keycloak menu adapter
# ==============================================================================
#
# Delegates explicit candidate operations to scripts/felix_keycloak_adapter.py.
# It handles only public usernames and protected file paths; administrator and
# client-secret values remain outside shell variables and terminal output.
# ==============================================================================

FELIX_KEYCLOAK_ADAPTER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FELIX_KEYCLOAK_REPOSITORY_ROOT="$(cd "${FELIX_KEYCLOAK_ADAPTER_DIR}/../.." && pwd)"
FELIX_KEYCLOAK_ADAPTER="${FELIX_KEYCLOAK_REPOSITORY_ROOT}/scripts/felix_keycloak_adapter.py"
FELIX_KEYCLOAK_EXPECTED_REALM="felix-new"
FELIX_KEYCLOAK_EXPECTED_STACK="felix-new"
FELIX_KEYCLOAK_EXPECTED_DOMAIN="api.felix-app.fe-wi.com"

# _is_felix_candidate_profile
# Verifies that the loaded root environment identifies only the candidate.
#
# Arguments:
#   None. Reads STACK_NAME, BACKEND_APP_ID, KEYCLOAK_REALM, and DOMAIN.
#
# Returns:
#   0 for the exact Felix candidate; 1 for generic or protected legacy targets.
_is_felix_candidate_profile() {
    [ "${STACK_NAME:-}" = "$FELIX_KEYCLOAK_EXPECTED_STACK" ] &&
        [ "${BACKEND_APP_ID:-}" = "felix" ] &&
        [ "${KEYCLOAK_REALM:-}" = "$FELIX_KEYCLOAK_EXPECTED_REALM" ] &&
        [ "${DOMAIN:-}" = "$FELIX_KEYCLOAK_EXPECTED_DOMAIN" ]
}

# _felix_keycloak_prompt_context
# Collects only the public admin username and protected credential-file path.
#
# Arguments:
#   None.
#
# Returns:
#   0 when both values are non-empty; 1 otherwise.
#
# Side effects:
#   Sets FELIX_KEYCLOAK_ADMIN_USER and FELIX_KEYCLOAK_ADMIN_PASSWORD_FILE.
_felix_keycloak_prompt_context() {
    local default_user="${KEYCLOAK_ADMIN_USER:-${KEYCLOAK_ADMIN:-Patrick}}"
    local default_file="${KEYCLOAK_ADMIN_PASSWORD_FILE:-/run/secrets/keycloak_admin_password}"

    read -r -p "Keycloak admin username [${default_user}]: " FELIX_KEYCLOAK_ADMIN_USER
    FELIX_KEYCLOAK_ADMIN_USER="${FELIX_KEYCLOAK_ADMIN_USER:-$default_user}"
    read -r -p "Protected admin password file [${default_file}]: " FELIX_KEYCLOAK_ADMIN_PASSWORD_FILE
    FELIX_KEYCLOAK_ADMIN_PASSWORD_FILE="${FELIX_KEYCLOAK_ADMIN_PASSWORD_FILE:-$default_file}"

    if [ -z "$FELIX_KEYCLOAK_ADMIN_USER" ] ||
        [ -z "$FELIX_KEYCLOAK_ADMIN_PASSWORD_FILE" ]; then
        echo "[ERROR] Admin username and protected password file are required."
        return 1
    fi
    return 0
}

# _felix_keycloak_run
# Delegates one explicit operation through the exact pinned Python adapter.
#
# Arguments:
#   $1 - command: check, plan, apply, verify, bridge-secret, or verify-legacy.
#
# Returns:
#   The canonical tool exit code.
#
# Side effects:
#   ``apply`` may reconcile approved candidate fields; ``bridge-secret`` may
#   create the exact Docker secret. No command deploys the Swarm stack.
_felix_keycloak_run() {
    local command="$1"

    if ! _is_felix_candidate_profile; then
        echo "[ERROR] Canonical Keycloak actions require the exact felix-new profile."
        return 1
    fi
    if [ ! -f "$FELIX_KEYCLOAK_ADAPTER" ]; then
        echo "[ERROR] Pinned Felix Keycloak adapter is missing."
        return 1
    fi
    if ! command -v python3 >/dev/null 2>&1; then
        echo "[ERROR] python3 is required for canonical Keycloak actions."
        return 1
    fi
    _felix_keycloak_prompt_context || return 1

    local arguments=(
        "$FELIX_KEYCLOAK_ADAPTER"
        --admin-user "$FELIX_KEYCLOAK_ADMIN_USER"
        --admin-password-file "$FELIX_KEYCLOAK_ADMIN_PASSWORD_FILE"
    )
    if [ -n "${FELIX_KEYCLOAK_TOOL_DIRECTORY:-}" ]; then
        arguments+=(--tool-directory "$FELIX_KEYCLOAK_TOOL_DIRECTORY")
    fi
    arguments+=("$command")
    python3 "${arguments[@]}"
}

# _felix_keycloak_advanced_compatibility
# Shows the Cognito compatibility boundary for non-Felix deployments.
#
# Arguments:
#   None.
#
# Returns:
#   0 after displaying the boundary.
_felix_keycloak_advanced_compatibility() {
    echo ""
    echo "Advanced authentication compatibility"
    echo "  Cognito and dual-provider setup remain available for generic profiles."
    echo "  They are intentionally disabled for the felix-new candidate because its"
    echo "  validated production profile requires Keycloak and file-backed secrets."
    echo "  Switch to a non-Felix deployment instance before using that helper."
    echo ""
}

# felix_keycloak_release_menu
# Presents explicit canonical candidate operations without implicit chaining.
#
# Arguments:
#   None.
#
# Returns:
#   0 when the operator returns to the main menu.
felix_keycloak_release_menu() {
    local choice
    while true; do
        echo ""
        echo "Felix candidate Keycloak"
        echo "  1) Check tool, server, and target safety"
        echo "  2) Plan / diff candidate reconciliation"
        echo "  3) Apply approved candidate reconciliation"
        echo "  4) Verify realm, clients, audience, roles, issuer, and JWKS"
        echo "  5) Bridge backend client secret directly into Docker"
        echo "  6) Verify protected legacy identities read-only"
        echo "  7) Advanced Cognito compatibility information"
        echo "  0) Back"
        read -r -p "Keycloak choice (0-7): " choice

        case "$choice" in
            1) _felix_keycloak_run check || true ;;
            2) _felix_keycloak_run plan || true ;;
            3) _felix_keycloak_run apply || true ;;
            4) _felix_keycloak_run verify || true ;;
            5) _felix_keycloak_run bridge-secret || true ;;
            6) _felix_keycloak_run verify-legacy || true ;;
            7) _felix_keycloak_advanced_compatibility ;;
            0) return 0 ;;
            *) echo "[WARN] Enter a value from 0 through 7." ;;
        esac
    done
}
