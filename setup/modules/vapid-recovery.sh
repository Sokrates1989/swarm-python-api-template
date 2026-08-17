#!/bin/bash
# ==============================================================================
# vapid-recovery.sh - Protected VAPID recovery-file lifecycle
# ==============================================================================
#
# Persists a newly generated matching VAPID pair only after an explicit
# operator decision. Values use the existing secrets.env restore contract,
# never appear in terminal output, and are written below a mode-0700 directory
# to a new mode-0600 file.
#
# Dependencies:
#   - operator_menu_message from operator-menu-localization.sh
# ==============================================================================

# _write_vapid_recovery_file
# Writes one matching pair in the existing secrets.env restore format without
# exposing either value to terminal output or command arguments.
#
# Arguments:
#   $1 - Caller variable receiving the created recovery-file path.
#   $2 - Protected recovery directory.
#   $3 - Public Docker-secret name.
#   $4 - Private Docker-secret name.
#   $5 - Public VAPID value.
#   $6 - Private VAPID value.
#
# Returns:
#   0 after creating a new mode-0600 file; otherwise 1.
#
# Side effects:
#   Creates the recovery directory with mode 0700 and a persistent plaintext
#   recovery file that the operator explicitly requested.
_write_vapid_recovery_file() {
    local target_name="$1"
    local recovery_directory="$2"
    local public_name="$3"
    local private_name="$4"
    local public_key="$5"
    local private_key="$6"
    local timestamp=""
    local recovery_file=""

    if [[ ! "$public_name" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]] ||
        [[ ! "$private_name" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]]; then
        printf '%s\n' "$(operator_menu_message vapid.recovery_invalid_names)" >&2
        return 1
    fi
    if ! (umask 077 && mkdir -p -- "$recovery_directory" &&
        chmod 700 -- "$recovery_directory"); then
        printf '%s\n' \
            "$(operator_menu_message vapid.recovery_directory_error \
                "$recovery_directory")" >&2
        return 1
    fi
    timestamp="$(date '+%Y_%m_%d__%H_%M_%S')"
    recovery_file="$(
        umask 077
        mktemp "${recovery_directory}/vapid-secrets.${timestamp}.env.XXXXXX"
    )" || {
        printf '%s\n' \
            "$(operator_menu_message vapid.recovery_file_error \
                "$recovery_directory")" >&2
        return 1
    }
    if ! {
        printf '# %s\n' \
            "$(operator_menu_message vapid.recovery_file_header)"
        printf '# %s\n' \
            "$(operator_menu_message vapid.recovery_file_restore)"
        printf '%s=%s\n' "$public_name" "$public_key"
        printf '%s=%s\n' "$private_name" "$private_key"
    } > "$recovery_file"; then
        rm -f -- "$recovery_file"
        printf '%s\n' \
            "$(operator_menu_message vapid.recovery_file_error \
                "$recovery_directory")" >&2
        return 1
    fi
    if ! chmod 600 -- "$recovery_file"; then
        rm -f -- "$recovery_file"
        printf '%s\n' \
            "$(operator_menu_message vapid.recovery_permissions_error)" >&2
        return 1
    fi
    printf -v "$target_name" '%s' "$recovery_file"
}

# _offer_vapid_recovery_file
# Offers the only automatic recovery opportunity while the generated plaintext
# pair is still available in process memory.
#
# Arguments:
#   $1 - Public Docker-secret name.
#   $2 - Private Docker-secret name.
#   $3 - Public VAPID value.
#   $4 - Private VAPID value.
#   $5 - Optional recovery directory override, primarily for tests.
#
# Returns:
#   0 after saving or an explicit skip; 1 when requested persistence fails.
#
# Side effects:
#   Prompts and may create a persistent, mode-0600 secrets.env fragment.
_offer_vapid_recovery_file() {
    local public_name="$1"
    local private_name="$2"
    local public_key="$3"
    local private_key="$4"
    local recovery_directory="${5:-${PROJECT_ROOT:-$(pwd)}/backup/secrets}"
    local save_copy=""
    local recovery_file=""

    printf '\n%s\n' "$(operator_menu_message vapid.recovery_heading)"
    printf '%s\n' "$(operator_menu_message vapid.recovery_divider)"
    printf '%s\n' "$(operator_menu_message vapid.recovery_notice)"
    printf '%s\n' "$(operator_menu_message vapid.recovery_restore_notice)"
    while true; do
        if ! read -r -p \
            "$(operator_menu_message vapid.recovery_prompt)" save_copy; then
            save_copy="n"
        fi
        case "${save_copy,,}" in
            ""|y|yes|j|ja) break ;;
            n|no|nein)
                printf '%s\n' \
                    "$(operator_menu_message vapid.recovery_skipped)"
                return 0
                ;;
            *)
                printf '%s\n' \
                    "$(operator_menu_message vapid.recovery_invalid_choice)"
                ;;
        esac
    done
    if ! _write_vapid_recovery_file \
        recovery_file \
        "$recovery_directory" \
        "$public_name" \
        "$private_name" \
        "$public_key" \
        "$private_key"; then
        return 1
    fi
    printf '%s\n' \
        "$(operator_menu_message vapid.recovery_saved "$recovery_file")"
    printf '%s\n' "$(operator_menu_message vapid.recovery_off_server)"
}
