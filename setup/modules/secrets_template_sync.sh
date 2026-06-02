#!/bin/bash
# =============================================================================
# secrets_template_sync.sh - Secrets template synchronization module
# =============================================================================
#
# This module provides functions for syncing Docker secrets.env files with
# their templates, ensuring older deployments can pick up new optional secrets
# without losing user-defined values.
#
# Functions:
#   sync_missing_secret_template_entries - Append missing secret keys from
#                                            template to existing secrets.env
#
# Dependencies:
#   - bash (trim whitespace helpers)
#
# =============================================================================

# ------------------------------------------------------------------------------
# _secret_sync_trim
# ------------------------------------------------------------------------------
# Internal helper: trims leading and trailing whitespace from stdin.
#
# Returns (stdout):
#   Trimmed string
# ------------------------------------------------------------------------------
_secret_sync_trim() {
    local line
    while IFS= read -r line; do
        # Remove leading whitespace
        line="${line#"${line%%[![:space:]]*}"}"
        # Remove trailing whitespace
        line="${line%"${line##*[![:space:]]}"}"
        printf '%s\n' "$line"
    done
}

# ------------------------------------------------------------------------------
# _secret_sync_key_exists
# ------------------------------------------------------------------------------
# Internal helper: checks if a key already exists in a secrets.env file.
#
# Arguments:
#   $1 - secrets_file: path to the secrets.env file
#   $2 - key: the key to search for
#
# Returns:
#   0 if key exists, 1 otherwise
# ------------------------------------------------------------------------------
_secret_sync_key_exists() {
    local secrets_file="$1"
    local key="$2"

    local raw_line check_key
    while IFS= read -r raw_line || [ -n "$raw_line" ]; do
        raw_line="${raw_line%$'\r'}"
        check_key=$(printf '%s' "$raw_line" | cut -d'=' -f1 | _secret_sync_trim)
        [ -z "$check_key" ] && continue
        case "$check_key" in
            \#*) continue ;;
        esac
        if [ "$check_key" = "$key" ]; then
            return 0
        fi
    done < "$secrets_file"

    return 1
}

# ------------------------------------------------------------------------------
# sync_missing_secret_template_entries
# ------------------------------------------------------------------------------
# Appends missing secret keys from a template file to an existing secrets.env
# file. This allows older deployments to pick up new optional secrets added
# to the template without overwriting user-defined values.
#
# Arguments:
#   $1 - secrets_file: path to the existing secrets.env file
#   $2 - template_file: path to the secrets.env.template file
#
# Returns:
#   0 on success, 1 if files don't exist
#
# Outputs (stdout):
#   Status message about added keys
# ------------------------------------------------------------------------------
sync_missing_secret_template_entries() {
    local secrets_file="$1"
    local template_file="$2"

    if [ ! -f "$secrets_file" ] || [ ! -f "$template_file" ]; then
        return 0
    fi

    local missing_keys=()
    local raw_line key
    while IFS= read -r raw_line || [ -n "$raw_line" ]; do
        raw_line="${raw_line%$'\r'}"
        key=$(printf '%s' "$raw_line" | cut -d'=' -f1 | _secret_sync_trim)
        [ -z "$key" ] && continue
        case "$key" in
            \#*) continue ;;
        esac
        if ! _secret_sync_key_exists "$secrets_file" "$key"; then
            missing_keys+=("$key")
        fi
    done < "$template_file"

    if [ ${#missing_keys[@]} -eq 0 ]; then
        return 0
    fi

    {
        echo ""
        echo "# Added from current secrets template"
        for key in "${missing_keys[@]}"; do
            echo "${key}="
        done
    } >> "$secrets_file"

    echo "[OK] Added missing secret key(s) to $secrets_file: ${missing_keys[*]}"
}
