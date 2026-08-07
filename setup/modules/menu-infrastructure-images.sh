#!/bin/bash
# ============================================================================
# menu-infrastructure-images.sh - Safe infrastructure image maintenance
# ============================================================================
#
# Provides a shared read-only inventory, exact-digest reminder snoozes, and
# compatibility-track refresh workflow. Repository adapters enumerate active
# infrastructure records and apply one verified public image assignment through
# their existing deployment/health/rollback transaction.
#
# Dependencies:
#   - menu-image-audit.sh for registry and scanner helpers.
#   - infrastructure-image-safety.sh for backup/security/major-track gates.
#   - scripts/infrastructure_image_tool.py.
# ============================================================================

# Guard against multiple sourcing.
if [ -n "${_MENU_INFRASTRUCTURE_IMAGES_LOADED:-}" ]; then
    return 0 2>/dev/null || true
fi
_MENU_INFRASTRUCTURE_IMAGES_LOADED=1

_MENU_INFRASTRUCTURE_IMAGES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${_MENU_INFRASTRUCTURE_IMAGES_DIR}/menu-image-audit.sh"
source "${_MENU_INFRASTRUCTURE_IMAGES_DIR}/infrastructure-image-safety.sh"

# _infrastructure_image_tool
# Resolves the shared read-only infrastructure registry helper.
#
# Output:
#   Absolute helper path.
_infrastructure_image_tool() {
    printf '%s' "$(cd "${_MENU_INFRASTRUCTURE_IMAGES_DIR}/../.." && pwd)/scripts/infrastructure_image_tool.py"
}

# _infrastructure_read
# Reads one operator response from the controlling terminal when available.
#
# Arguments:
#   $1 - Prompt text.
#   $2 - Target variable name.
_infrastructure_read() {
    local prompt="$1"
    local target_name="$2"
    local answer=""

    if [[ -r /dev/tty ]]; then
        read -r -p "$prompt" answer < /dev/tty
    else
        read -r -p "$prompt" answer
    fi
    printf -v "$target_name" '%s' "$answer"
}

# _infrastructure_records
# Loads adapter-provided infrastructure operation records.
#
# Arguments:
#   $1 - Caller-owned Bash array variable.
#
# Returns:
#   0 when at least one record is available; otherwise 1.
_infrastructure_records() {
    local target_name="$1"
    local -n target="$target_name"

    target=()
    if ! declare -F _operator_infrastructure_image_records >/dev/null 2>&1; then
        echo "[ERROR] This deployment has no infrastructure-image adapter."
        return 1
    fi
    mapfile -t target < <(_operator_infrastructure_image_records)
    if [ "${#target[@]}" -eq 0 ]; then
        echo "[WARN] The active deployment has no managed infrastructure images."
        return 1
    fi
}

# _infrastructure_tool_arguments
# Converts adapter records to repeated CLI arguments in a caller-owned array.
#
# Arguments:
#   $1 - Source record array variable.
#   $2 - Target argument array variable.
_infrastructure_tool_arguments() {
    local source_name="$1"
    local target_name="$2"
    local -n source="$source_name"
    local -n target="$target_name"
    local record=""

    target=()
    for record in "${source[@]}"; do
        target+=(--record "$record")
    done
}

# show_infrastructure_image_inventory
# Displays deployed references, detected release aliases, track targets, and
# recent compatible tags without changing files, images, or services.
show_infrastructure_image_inventory() {
    local records=()
    local arguments=()
    local python_command=""

    _infrastructure_records records || return 1
    _infrastructure_tool_arguments records arguments
    python_command="$(_image_audit_python)" || return 1
    echo ""
    echo "Infrastructure Image Versions"
    echo "============================="
    echo "Current versions are inferred by matching the exact deployed digest"
    echo "to recent real registry tags. Compatibility tracks constrain updates."
    "$python_command" "$(_infrastructure_image_tool)" report \
        --platform linux/amd64 \
        "${arguments[@]}"
}

# _load_infrastructure_candidates
# Resolves all infrastructure records to machine-readable current/target data.
#
# Arguments:
#   $1 - Caller-owned candidate array variable.
#
# Returns:
#   0 when registry resolution succeeds; otherwise 1.
_load_infrastructure_candidates() {
    local target_name="$1"
    local -n target="$target_name"
    local records=()
    local arguments=()
    local python_command=""
    local output=""

    _infrastructure_records records || return 1
    _infrastructure_tool_arguments records arguments
    python_command="$(_image_audit_python)" || return 1
    output="$("$python_command" "$(_infrastructure_image_tool)" candidates \
        --cache "$(_image_audit_cache)" \
        --platform linux/amd64 \
        "${arguments[@]}")" || return 1
    target=()
    [ -z "$output" ] || mapfile -t target <<< "$output"
}

# _short_infrastructure_digest
# Formats a compact digest without obscuring its SHA-256 identity.
#
# Arguments:
#   $1 - Full digest.
#
# Output:
#   Prefix plus first twelve hexadecimal characters.
_short_infrastructure_digest() {
    local value="$1"

    if [[ "$value" == sha256:* ]]; then
        printf 'sha256:%.12s...' "${value#sha256:}"
    else
        printf '%s' "${value:-unknown}"
    fi
}

# _ignore_infrastructure_candidate
# Persists a public reason for suppressing one exact target reminder.
#
# Arguments:
#   $1 - Identifier.
#   $2 - Label.
#   $3 - Exact target digest.
_ignore_infrastructure_candidate() {
    local identifier="$1"
    local label="$2"
    local digest="$3"
    local reason=""
    local python_command=""

    _infrastructure_read "Public ignore reason [Deferred after operator review]: " reason
    reason="${reason:-Deferred after operator review}"
    python_command="$(_image_audit_python)" || return 1
    "$python_command" "$(_infrastructure_image_tool)" ignore \
        --cache "$(_image_audit_cache)" \
        --id "$identifier" \
        --label "$label" \
        --digest "$digest" \
        --reason "$reason" || return 1
    run_registry_image_audit || true
}

# _collect_active_infrastructure_updates
# Filters machine-readable candidate records to unsnoozed compatible updates.
#
# Arguments:
#   $1 - Candidate array variable.
#   $2 - Caller-owned update array variable.
_collect_active_infrastructure_updates() {
    local source_name="$1"
    local target_name="$2"
    local -n source="$source_name"
    local -n target="$target_name"
    local fields=()
    local record=""

    target=()
    for record in "${source[@]}"; do
        IFS='|' read -r -a fields <<< "$record"
        [ "${fields[11]:-}" = "update" ] && target+=("$record")
    done
}

# _print_infrastructure_update_choices
# Prints one numbered row for each compatible immutable refresh.
#
# Arguments:
#   $1 - Update record array variable.
_print_infrastructure_update_choices() {
    local source_name="$1"
    local -n source="$source_name"
    local fields=()
    local index=0

    echo ""
    echo "Compatible infrastructure refreshes"
    echo "===================================="
    for index in "${!source[@]}"; do
        IFS='|' read -r -a fields <<< "${source[$index]}"
        echo "  $((index + 1))) ${fields[1]} (${fields[5]} -> $(_short_infrastructure_digest "${fields[10]}"))"
    done
    echo "  0) Back"
}

# _choose_infrastructure_update
# Reads a numbered update choice into a caller-owned variable.
#
# Arguments:
#   $1 - Update record array variable.
#   $2 - Caller-owned selected-record variable.
#
# Returns:
#   0 for a valid update; otherwise 1 for cancel or invalid input.
_choose_infrastructure_update() {
    local source_name="$1"
    local target_name="$2"
    local -n source="$source_name"
    local choice=""

    _infrastructure_read "Your choice [1]: " choice
    choice="${choice:-1}"
    if ! [[ "$choice" =~ ^[0-9]+$ ]] || [ "$choice" -eq 0 ] ||
        [ "$choice" -gt "${#source[@]}" ]; then
        return 1
    fi
    printf -v "$target_name" '%s' "${source[$((choice - 1))]}"
}

# _apply_infrastructure_update_record
# Runs backup, broad-track, scan, deployment, health, and cache cleanup gates.
#
# Arguments:
#   $1 - Selected machine-readable update record.
#
# Returns:
#   0 after an accepted deployment; otherwise non-zero.
_apply_infrastructure_update_record() {
    local record="$1"
    local identifier label service environment_key current track state_kind
    local repository target_reference current_digest target_digest status docs
    local python_command=""

    IFS='|' read -r identifier label service environment_key current track \
        state_kind repository target_reference current_digest target_digest \
        status docs <<< "$record"
    if [ "$state_kind" = "database" ]; then
        _postgres_backup_checkpoint || return 1
    fi
    _confirm_broad_infrastructure_track "$track" "$state_kind" || return 1
    _preflight_infrastructure_target "$target_reference" || return 1
    if ! declare -F _operator_apply_infrastructure_image_update >/dev/null 2>&1; then
        echo "[ERROR] This repository cannot apply infrastructure image updates."
        return 1
    fi
    _operator_apply_infrastructure_image_update \
        "$identifier" "$label" "$environment_key" "$target_reference" || return 1
    python_command="$(_image_audit_python)" || return 1
    "$python_command" "$(_infrastructure_image_tool)" clear-ignore \
        --cache "$(_image_audit_cache)" --id "$identifier" >/dev/null 2>&1 || true
    run_registry_image_audit || true
}

# _review_infrastructure_update_record
# Displays one selected target and lets the operator apply or snooze it.
#
# Arguments:
#   $1 - Selected machine-readable update record.
#
# Returns:
#   Status of the selected action, or zero after cancellation.
_review_infrastructure_update_record() {
    local record="$1"
    local fields=()
    local action=""

    IFS='|' read -r -a fields <<< "$record"
    echo ""
    echo "Selected: ${fields[1]}"
    echo "  Current: ${fields[4]}"
    echo "  Track:   ${fields[7]}:${fields[5]}"
    echo "  Target:  ${fields[8]}"
    echo "  1) Scan, apply, deploy, and health-check this compatible refresh"
    echo "  2) Ignore this exact target digest until the channel changes"
    echo "  0) Cancel"
    _infrastructure_read "Your choice [1]: " action
    action="${action:-1}"
    if [ "$action" = "2" ]; then
        _ignore_infrastructure_candidate "${fields[0]}" "${fields[1]}" "${fields[10]}"
        return $?
    fi
    [ "$action" = "1" ] || return 0
    _apply_infrastructure_update_record "$record"
}

# manage_infrastructure_image_updates
# Selects one active same-track refresh and either applies or snoozes it.
manage_infrastructure_image_updates() {
    local candidates=()
    local updates=()
    local selected=""

    _load_infrastructure_candidates candidates || return 1
    _collect_active_infrastructure_updates candidates updates
    if [ "${#updates[@]}" -eq 0 ]; then
        echo "[OK] No active compatible infrastructure refresh is available."
        return 0
    fi
    _print_infrastructure_update_choices updates
    _choose_infrastructure_update updates selected || return 0
    _review_infrastructure_update_record "$selected"
}

# manage_ignored_infrastructure_updates
# Lists exact-digest snoozes and allows one reminder to be restored.
manage_ignored_infrastructure_updates() {
    local python_command=""
    local output=""
    local records=()
    local record=""
    local identifier label digest reason
    local choice=""
    local index=0

    python_command="$(_image_audit_python)" || return 1
    output="$("$python_command" "$(_infrastructure_image_tool)" list-ignores \
        --cache "$(_image_audit_cache)")" || return 1
    if [[ "$output" != *'|'* ]]; then
        printf '%s\n' "$output"
        return 0
    fi
    mapfile -t records <<< "$output"
    echo ""
    echo "Ignored infrastructure reminders"
    echo "================================"
    for index in "${!records[@]}"; do
        IFS='|' read -r identifier label digest reason <<< "${records[$index]}"
        echo "  $((index + 1))) ${label}: $(_short_infrastructure_digest "$digest")"
        echo "      Reason: ${reason}"
    done
    echo "  0) Back"
    _infrastructure_read "Restore which reminder [0]: " choice
    choice="${choice:-0}"
    if ! [[ "$choice" =~ ^[0-9]+$ ]] || [ "$choice" -eq 0 ] ||
        [ "$choice" -gt "${#records[@]}" ]; then
        return 0
    fi
    identifier="${records[$((choice - 1))]%%|*}"
    "$python_command" "$(_infrastructure_image_tool)" clear-ignore \
        --cache "$(_image_audit_cache)" --id "$identifier"
}

# run_infrastructure_image_menu
# Presents version inventory, safe updates, reminder management, and guidance.
run_infrastructure_image_menu() {
    local choice=""

    while true; do
        echo ""
        echo "Infrastructure Images"
        echo "====================="
        echo "  1) Show current, tracked, and available compatible versions"
        echo "  2) Apply or ignore a compatible immutable refresh"
        echo "  3) Review or restore ignored update reminders"
        echo "  h) Explain security, backup, and major-upgrade policy"
        echo "  0) Back"
        _infrastructure_read "Your choice: " choice
        case "$choice" in
            1) show_infrastructure_image_inventory || true ;;
            2) manage_infrastructure_image_updates || true ;;
            3) manage_ignored_infrastructure_updates || true ;;
            h|H) show_infrastructure_update_policy ;;
            0) return 0 ;;
            *) echo "[WARN] Choose 0-3 or h." ;;
        esac
    done
}
