#!/bin/bash
# ==============================================================================
# menu-image-audit.sh - Registry freshness and image-security operations
# ==============================================================================
#
# Supplies the shared `a` menu for read-only registry checks, fixable
# HIGH/CRITICAL vulnerability scans, and application base-image advice. The
# repository adapter provides image records through documented hook functions;
# this module owns registry-tool invocation, cache updates, scanner fallback,
# and operator-facing status text.
#
# Dependencies:
#   - scripts/registry_image_tool.py.
#   - Docker Scout or Trivy for optional vulnerability scanning.
# ==============================================================================

# Guard against multiple sourcing.
if [ -n "${_MENU_IMAGE_AUDIT_LOADED:-}" ]; then
    return 0 2>/dev/null || true
fi
_MENU_IMAGE_AUDIT_LOADED=1

_MENU_IMAGE_AUDIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ------------------------------------------------------------------------------
# _image_audit_python
# ------------------------------------------------------------------------------
# Finds a Python 3 runtime for the standard-library registry helper.
#
# Output:
#   Executable command name.
#
# Returns:
#   0 when Python is available; otherwise 1.
# ------------------------------------------------------------------------------
_image_audit_python() {
    if command -v python3 >/dev/null 2>&1; then
        printf '%s' 'python3'
    elif command -v python >/dev/null 2>&1; then
        printf '%s' 'python'
    else
        echo "[ERROR] Python 3 is required for registry image checks." >&2
        return 1
    fi
}

# ------------------------------------------------------------------------------
# _image_audit_tool
# ------------------------------------------------------------------------------
# Resolves the repository-local registry helper.
#
# Output:
#   Absolute helper path.
# ------------------------------------------------------------------------------
_image_audit_tool() {
    printf '%s' "$(cd "${_MENU_IMAGE_AUDIT_DIR}/../.." && pwd)/scripts/registry_image_tool.py"
}

# ------------------------------------------------------------------------------
# _image_audit_cache
# ------------------------------------------------------------------------------
# Resolves the ignored public-evidence cache at the deployment root.
#
# Output:
#   Absolute cache path.
# ------------------------------------------------------------------------------
_image_audit_cache() {
    printf '%s' "${PROJECT_ROOT:-$(cd "${_MENU_IMAGE_AUDIT_DIR}/../.." && pwd)}/.image-audit-cache.json"
}

# ------------------------------------------------------------------------------
# _image_audit_privilege_prefix
# ------------------------------------------------------------------------------
# Chooses the prefix shown for Debian/Ubuntu package-management commands.
# Root shells receive directly runnable commands; unprivileged shells receive
# the conventional sudo prefix.
#
# Output:
#   Empty text for root, otherwise "sudo ".
# ------------------------------------------------------------------------------
_image_audit_privilege_prefix() {
    if [ "$(id -u)" -ne 0 ]; then
        printf '%s' 'sudo '
    fi
}

# ------------------------------------------------------------------------------
# _show_docker_scout_install_help
# ------------------------------------------------------------------------------
# Prints the official Docker Scout CLI-plugin installation and verification
# steps without executing or changing the host.
# ------------------------------------------------------------------------------
_show_docker_scout_install_help() {
    local privilege_prefix=""
    local scout_installer_url="https://raw.githubusercontent.com/docker/scout-cli/main/install.sh"

    privilege_prefix="$(_image_audit_privilege_prefix)"
    echo "[INFO] Install Docker Scout (CVE scan + base-image advice):"
    echo "       ${privilege_prefix}apt-get update"
    echo "       ${privilege_prefix}apt-get install -y curl"
    echo "       curl -sSfL ${scout_installer_url} | sh -s --"
    echo "       docker scout version"
    echo "       docker login"
    echo "       About: https://docs.docker.com/scout/"
    echo "       Guide: https://github.com/docker/scout-cli#cli-plugin-installation"
}

# ------------------------------------------------------------------------------
# _show_trivy_install_help
# ------------------------------------------------------------------------------
# Prints Aqua Security's official Debian/Ubuntu repository installation and
# verification steps without executing or changing the host.
# ------------------------------------------------------------------------------
_show_trivy_install_help() {
    local privilege_prefix=""

    privilege_prefix="$(_image_audit_privilege_prefix)"
    echo "[INFO] Or install Trivy (CVE scan fallback only):"
    echo "       ${privilege_prefix}apt-get install -y wget gnupg"
    echo "       wget -qO - https://aquasecurity.github.io/trivy-repo/deb/public.key |" \
        "gpg --dearmor | ${privilege_prefix}tee /usr/share/keyrings/trivy.gpg >/dev/null"
    echo "       echo 'deb [signed-by=/usr/share/keyrings/trivy.gpg]" \
        "https://aquasecurity.github.io/trivy-repo/deb generic main' |" \
        "${privilege_prefix}tee /etc/apt/sources.list.d/trivy.list >/dev/null"
    echo "       ${privilege_prefix}apt-get update"
    echo "       ${privilege_prefix}apt-get install -y trivy"
    echo "       trivy --version"
    echo "       About: https://trivy.dev/docs/latest/"
    echo "       Guide: https://www.trivy.dev/docs/latest/getting-started/installation/"
}

# ------------------------------------------------------------------------------
# registry_stable_tags
# ------------------------------------------------------------------------------
# Enumerates real stable semantic-version tags for one repository.
#
# Arguments:
#   $1 - Docker repository without tag.
#
# Output:
#   Descending tags, one per line.
# ------------------------------------------------------------------------------
registry_stable_tags() {
    local repository="$1"
    local python_command=""

    python_command="$(_image_audit_python)" || return 1
    "$python_command" "$(_image_audit_tool)" stable-tags \
        --repository "$repository"
}

# ------------------------------------------------------------------------------
# registry_verify_tag
# ------------------------------------------------------------------------------
# Verifies that one exact tag exists and declares linux/amd64 support.
#
# Arguments:
#   $1 - Docker repository without tag.
#   $2 - Exact tag.
#
# Output:
#   JSON digest/platform evidence.
# ------------------------------------------------------------------------------
registry_verify_tag() {
    local repository="$1"
    local tag="$2"
    local python_command=""

    python_command="$(_image_audit_python)" || return 1
    "$python_command" "$(_image_audit_tool)" verify \
        --repository "$repository" \
        --tag "$tag" \
        --platform 'linux/amd64'
}

# ------------------------------------------------------------------------------
# image_audit_overview_status
# ------------------------------------------------------------------------------
# Reads cached audit state without making network or scanner calls during menu
# redraws.
#
# Output:
#   Pipe-delimited semantic color level and status text.
# ------------------------------------------------------------------------------
image_audit_overview_status() {
    local python_command=""

    python_command="$(_image_audit_python 2>/dev/null)" || {
        printf '%s\n' 'off|[UNKNOWN] Python 3 unavailable for image audit'
        return 0
    }
    "$python_command" "$(_image_audit_tool)" cache-summary \
        --cache "$(_image_audit_cache)" \
        --max-age-hours "${IMAGE_AUDIT_MAX_AGE_HOURS:-24}" 2>/dev/null ||
        printf '%s\n' 'off|[UNKNOWN] image-audit cache unavailable'
}

# ------------------------------------------------------------------------------
# run_registry_image_audit
# ------------------------------------------------------------------------------
# Audits every repository-provided application and infrastructure record.
#
# Required adapter hook:
#   _operator_image_audit_records outputs
#   id|label|kind|repository|current|track-tag records.
#
# Returns:
#   0 after cache refresh; otherwise 1.
# ------------------------------------------------------------------------------
run_registry_image_audit() {
    local records=()
    local arguments=()
    local python_command=""
    local record=""

    if ! declare -F _operator_image_audit_records >/dev/null 2>&1; then
        echo "[ERROR] This deployment has no image-audit record adapter."
        return 1
    fi
    mapfile -t records < <(_operator_image_audit_records)
    if [ "${#records[@]}" -eq 0 ]; then
        echo "[WARN] No configured images were found to audit."
        return 1
    fi
    python_command="$(_image_audit_python)" || return 1
    for record in "${records[@]}"; do
        arguments+=(--record "$record")
    done
    echo ""
    echo "Registry image freshness"
    echo "------------------------"
    echo "Application images are compared with real stable SemVer tags."
    echo "Infrastructure digests are compared only with their configured"
    echo "update channels; major database upgrades are never inferred."
    echo ""
    "$python_command" "$(_image_audit_tool)" audit \
        --cache "$(_image_audit_cache)" \
        --platform 'linux/amd64' \
        "${arguments[@]}"
}

# ------------------------------------------------------------------------------
# _record_security_result
# ------------------------------------------------------------------------------
# Stores one aggregate scanner result beside registry evidence.
#
# Arguments:
#   $1 - ok, warning, or unknown.
#   $2 - Public summary text.
# ------------------------------------------------------------------------------
_record_security_result() {
    local status="$1"
    local summary="$2"
    local python_command=""

    python_command="$(_image_audit_python)" || return 1
    "$python_command" "$(_image_audit_tool)" security-result \
        --cache "$(_image_audit_cache)" \
        --status "$status" \
        --summary "$summary"
}

# ------------------------------------------------------------------------------
# _scan_with_docker_scout
# ------------------------------------------------------------------------------
# Scans one registry image for fixable HIGH/CRITICAL vulnerabilities.
#
# Arguments:
#   $1 - Exact image tag or digest reference.
#
# Returns:
#   0 when clean, 2 when findings exist, or 3 when scanning failed.
# ------------------------------------------------------------------------------
_scan_with_docker_scout() {
    local reference="$1"
    local status=0

    docker scout cves \
        --only-fixed \
        --only-severity critical,high \
        --platform linux/amd64 \
        --exit-code \
        "registry://${reference}" || status=$?
    case "$status" in
        0) return 0 ;;
        2) return 2 ;;
        *) return 3 ;;
    esac
}

# ------------------------------------------------------------------------------
# _scan_with_trivy
# ------------------------------------------------------------------------------
# Runs the equivalent fixable HIGH/CRITICAL policy through Trivy.
#
# Arguments:
#   $1 - Exact image tag or digest reference.
#
# Returns:
#   0 when clean, 2 when findings exist, or 3 when scanning failed.
# ------------------------------------------------------------------------------
_scan_with_trivy() {
    local reference="$1"
    local status=0

    trivy image \
        --scanners vuln \
        --ignore-unfixed \
        --severity HIGH,CRITICAL \
        --exit-code 2 \
        --no-progress \
        "$reference" || status=$?
    case "$status" in
        0) return 0 ;;
        2) return 2 ;;
        *) return 3 ;;
    esac
}

# ------------------------------------------------------------------------------
# run_image_security_scan
# ------------------------------------------------------------------------------
# Scans all adapter-provided exact image references, preferring Docker Scout
# and falling back to Trivy.
#
# Required adapter hook:
#   _operator_image_security_references outputs one exact reference per line.
#
# Returns:
#   0 after aggregate evidence is recorded; otherwise 1.
# ------------------------------------------------------------------------------
run_image_security_scan() {
    local references=()
    local reference=""
    local scanner=""
    local scan_status=0
    local findings=0
    local failures=0
    declare -A seen=()

    if ! declare -F _operator_image_security_references >/dev/null 2>&1; then
        echo "[ERROR] This deployment has no security-scan image adapter."
        return 1
    fi
    if docker scout version >/dev/null 2>&1; then
        scanner='docker-scout'
    elif command -v trivy >/dev/null 2>&1; then
        scanner='trivy'
    else
        echo "[WARN] Install Docker Scout or Trivy to scan image vulnerabilities."
        echo ""
        _show_docker_scout_install_help
        echo ""
        _show_trivy_install_help
        _record_security_result unknown 'No supported image scanner installed' || true
        return 1
    fi
    mapfile -t references < <(_operator_image_security_references)
    echo ""
    echo "Image vulnerability scan"
    echo "------------------------"
    echo "Scanner: ${scanner}"
    echo "Policy: fixable HIGH and CRITICAL vulnerabilities on linux/amd64"
    for reference in "${references[@]}"; do
        [ -n "$reference" ] || continue
        [ -z "${seen[$reference]:-}" ] || continue
        seen[$reference]=1
        echo ""
        echo "=== ${reference} ==="
        scan_status=0
        if [ "$scanner" = 'docker-scout' ]; then
            _scan_with_docker_scout "$reference" || scan_status=$?
        else
            _scan_with_trivy "$reference" || scan_status=$?
        fi
        case "$scan_status" in
            0) ;;
            2) findings=$((findings + 1)) ;;
            *) failures=$((failures + 1)) ;;
        esac
    done
    if [ "$findings" -gt 0 ]; then
        _record_security_result warning \
            "${findings} image(s) contain fixable HIGH/CRITICAL findings"
    elif [ "$failures" -gt 0 ]; then
        _record_security_result unknown \
            "${failures} image scan(s) could not be completed"
    else
        _record_security_result ok \
            'No fixable HIGH/CRITICAL findings in scanned images'
    fi
}

# ------------------------------------------------------------------------------
# run_base_image_recommendations
# ------------------------------------------------------------------------------
# Requests Docker Scout refresh/update advice for application images only.
#
# Required adapter hook:
#   _operator_application_image_references outputs exact application refs.
#
# Returns:
#   0 after reports complete; otherwise 1 when Scout is unavailable.
# ------------------------------------------------------------------------------
run_base_image_recommendations() {
    local references=()
    local reference=""

    if ! docker scout version >/dev/null 2>&1; then
        echo "[WARN] Docker Scout is required for base-image recommendations."
        echo "       Vulnerability scanning can still use Trivy when installed."
        echo ""
        _show_docker_scout_install_help
        return 1
    fi
    if ! declare -F _operator_application_image_references >/dev/null 2>&1; then
        echo "[ERROR] This deployment has no application-image adapter."
        return 1
    fi
    mapfile -t references < <(_operator_application_image_references)
    echo ""
    echo "Application base-image recommendations"
    echo "--------------------------------------"
    for reference in "${references[@]}"; do
        [ -n "$reference" ] || continue
        echo ""
        echo "=== ${reference} ==="
        docker scout recommendations \
            --platform linux/amd64 \
            "registry://${reference}" ||
            echo "[WARN] No base-image recommendation evidence for ${reference}."
    done
}

# ------------------------------------------------------------------------------
# run_complete_image_audit
# ------------------------------------------------------------------------------
# Runs registry, vulnerability, and base-image checks in one explicit action.
#
# Returns:
#   0 after all best-effort checks have run.
# ------------------------------------------------------------------------------
run_complete_image_audit() {
    run_registry_image_audit || true
    run_image_security_scan || true
    run_base_image_recommendations || true
}

# ------------------------------------------------------------------------------
# run_image_audit_menu
# ------------------------------------------------------------------------------
# Presents the stable cross-repository image audit and security submenu.
# ------------------------------------------------------------------------------
run_image_audit_menu() {
    local choice=""

    while true; do
        echo ""
        echo "Image Updates and Security"
        echo "=========================="
        echo "Inventory and maintenance:"
        echo "  1) Check registry freshness and tracked infrastructure digests"
        echo "  2) Infrastructure versions, compatible updates, and ignores"
        echo ""
        echo "Security:"
        echo "  3) Scan deployed/configured images for fixable HIGH/CRITICAL CVEs"
        echo "  4) Check application base-image refresh/update recommendations"
        echo "  5) Run the complete image audit"
        echo "  0) Back"
        echo ""
        if [[ -r /dev/tty ]]; then
            read -r -p "Your choice (0-5): " choice < /dev/tty
        else
            read -r -p "Your choice (0-5): " choice
        fi
        case "$choice" in
            1) run_registry_image_audit || true ;;
            2)
                if declare -F run_infrastructure_image_menu >/dev/null 2>&1; then
                    run_infrastructure_image_menu
                else
                    echo "[ERROR] Infrastructure image actions are unavailable."
                fi
                ;;
            3) run_image_security_scan || true ;;
            4) run_base_image_recommendations || true ;;
            5) run_complete_image_audit ;;
            0) return 0 ;;
            *) echo "[WARN] Choose a value from 0 through 5." ;;
        esac
    done
}
