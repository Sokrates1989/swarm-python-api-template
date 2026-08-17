#!/bin/bash
# ==============================================================================
# vapid-recovery.sh - Ephemeral VAPID recovery-view adapter
# ==============================================================================
#
# Hands a newly generated matching VAPID pair to the repository-wide temporary
# secret viewer. The protected source handoff is consumed before the opt-in
# prompt, values never appear in terminal output or command arguments, and the
# read-only editor file is deleted immediately when the editor closes.
#
# Dependencies:
#   - operator_menu_message from operator-menu-localization.sh
#   - scripts/temporary_secret_viewer.py
# ==============================================================================

# _offer_vapid_recovery_view
# Offers one optional, self-deleting editor view while the matching generated
# pair is still held in process memory.
#
# Arguments:
#   $1 - Public Docker-secret name.
#   $2 - Private Docker-secret name.
#   $3 - Public VAPID value.
#   $4 - Private VAPID value.
#
# Returns:
#   The shared viewer status.
#
# Side effects:
#   Creates a mode-0600 handoff, invokes the repository-wide viewer, and
#   deletes the handoff on every normal or interrupted exit path.
_offer_vapid_recovery_view() (
    local public_name="$1"
    local private_name="$2"
    local public_key="$3"
    local private_key="$4"
    local viewer_script="${_VAPID_SECRETS_DIR}/../../scripts/temporary_secret_viewer.py"
    local handoff_file=""

    cleanup_vapid_view_handoff() {
        if [ -n "$handoff_file" ]; then
            rm -f -- "$handoff_file"
        fi
    }
    trap cleanup_vapid_view_handoff EXIT HUP INT TERM

    if [[ ! "$public_name" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]] ||
        [[ ! "$private_name" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]]; then
        printf '%s\n' "$(operator_menu_message vapid.recovery_invalid_names)" >&2
        return 1
    fi
    if [ ! -f "$viewer_script" ] || ! command -v python3 >/dev/null 2>&1; then
        printf '%s\n' "$(operator_menu_message vapid.recovery_viewer_missing)" >&2
        return 1
    fi
    handoff_file="$(umask 077 && mktemp "${TMPDIR:-/tmp}/vapid-view.XXXXXX")" || {
        printf '%s\n' "$(operator_menu_message vapid.recovery_handoff_error)" >&2
        return 1
    }
    if ! {
        printf '# %s\n' "$(operator_menu_message vapid.recovery_file_header)"
        printf '# %s\n' "$(operator_menu_message vapid.recovery_file_restore)"
        printf '%s=%s\n' "$public_name" "$public_key"
        printf '%s=%s\n' "$private_name" "$private_key"
    } > "$handoff_file" || ! chmod 600 -- "$handoff_file"; then
        printf '%s\n' "$(operator_menu_message vapid.recovery_handoff_error)" >&2
        return 1
    fi

    python3 "$viewer_script" \
        --source-file "$handoff_file" \
        --file-name "vapid-secrets.env" \
        --heading "$(operator_menu_message vapid.recovery_heading)" \
        --notice "$(operator_menu_message vapid.recovery_notice)" \
        --notice "$(operator_menu_message vapid.recovery_copy_notice)" \
        --notice "$(operator_menu_message vapid.recovery_delete_notice)" \
        --prompt "$(operator_menu_message vapid.recovery_view_prompt)" \
        --skipped "$(operator_menu_message vapid.recovery_view_skipped)" \
        --copy-instruction "$(operator_menu_message vapid.recovery_copy_instruction)" \
        --deleted-message "$(operator_menu_message vapid.recovery_deleted)"
)

# Backward-compatible name for downstream templates that sourced the initial
# recovery module. It now delegates to the ephemeral viewer and never creates
# a persistent plaintext recovery file.
_offer_vapid_recovery_file() {
    _offer_vapid_recovery_view "$1" "$2" "$3" "$4"
}
