#!/bin/bash
# ===============================================================================
# secret-file-import.sh - Secure Docker secret-file import lifecycle
# ===============================================================================
#
# Validates, edits, imports, and cleans plaintext Docker secret value files.
# The `always` policy denotes an ephemeral file and removes it after success,
# validation/editor/Docker failure, or operator interruption.
#
# Dependencies:
#   - GNU/Coreutils `install` for mode-0600 file creation
#   - create_secret_from_value from secret-manager.sh
#   - choose_editor from user-prompts.sh at invocation time
#   - optional sync_missing_secret_template_entries
# ===============================================================================

# Guard against multiple sourcing.
if [ -n "${_SECRET_FILE_IMPORT_LOADED:-}" ]; then
    return 0 2>/dev/null || true
fi
_SECRET_FILE_IMPORT_LOADED=1

# ------------------------------------------------------------------------------
# _validate_secret_env_keys
# ------------------------------------------------------------------------------
# Validates every effective key in a saved secret-values file before any Docker
# mutation. Exact-name profiles pass a newline-separated profile allowlist;
# legacy prefixed workflows may omit enforcement but still receive safe-name
# validation. Enforcement is independent from allowlist contents so an exact
# profile with no batch-importable secrets rejects every effective key.
#
# Arguments:
#   $1 - secrets_file: values file to inspect.
#   $2 - allowed_keys: newline-separated exact-name allowlist (may be empty).
#   $3 - enforce_allowlist: true to require membership; false by default.
#
# Returns:
#   0 when every key is safe and, when enforced, allowed; otherwise 1.
#
# Errors:
#   Returns 1 for an invalid enforcement flag, unsafe key, or undeclared key.
# ------------------------------------------------------------------------------
_validate_secret_env_keys() {
    local secrets_file="$1"
    local allowed_keys="${2:-}"
    local enforce_allowlist="${3:-false}"
    local key=""
    local ignored_value=""

    case "$enforce_allowlist" in
        true|false) ;;
        *)
            echo "[ERROR] Invalid secret allowlist enforcement mode: ${enforce_allowlist}" >&2
            return 1
            ;;
    esac

    while IFS='=' read -r key ignored_value || [ -n "$key" ]; do
        key="${key%$'\r'}"
        key="${key#"${key%%[![:space:]]*}"}"
        key="${key%"${key##*[![:space:]]}"}"
        case "$key" in
            export\ *) key="${key#export }" ;;
            ""|\#*) continue ;;
        esac
        if [[ ! "$key" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]]; then
            echo "[ERROR] Unsafe Docker secret key in ${secrets_file}: ${key}" >&2
            return 1
        fi
        if [ "$enforce_allowlist" = "true" ] &&
            ! printf '%s\n' "$allowed_keys" | grep -Fxq -- "$key"; then
            echo "[ERROR] Undeclared Docker secret key in ${secrets_file}: ${key}" >&2
            echo "        Add it to the selected site profile before importing." >&2
            return 1
        fi
    done < "$secrets_file"
}

# ------------------------------------------------------------------------------
# _validate_required_secret_env_values
# ------------------------------------------------------------------------------
# Requires each profile-declared batch key to have a non-empty value before
# any Docker secret is created. Optional empty entries remain valid and are
# skipped by the importer.
#
# Arguments:
#   $1 - Secret values file.
#   $2 - Newline-separated required keys; empty disables this check.
#
# Returns:
#   0 when every required key has a value; otherwise 1.
# ------------------------------------------------------------------------------
_validate_required_secret_env_values() {
    local secrets_file="$1"
    local required_keys="${2:-}"
    local required_key=""
    local key=""
    local value=""
    local found="false"
    local missing=0

    while IFS= read -r required_key; do
        [ -n "$required_key" ] || continue
        found="false"
        while IFS='=' read -r key value || [ -n "$key" ]; do
            key="${key%$'\r'}"
            value="${value%$'\r'}"
            key="${key#"${key%%[![:space:]]*}"}"
            key="${key%"${key##*[![:space:]]}"}"
            case "$key" in
                export\ *) key="${key#export }" ;;
            esac
            [ "$key" = "$required_key" ] || continue
            value="${value#\"}"
            value="${value%\"}"
            value="${value#\'}"
            value="${value%\'}"
            if [ -n "$value" ]; then
                found="true"
            fi
            break
        done < "$secrets_file"
        if [ "$found" != "true" ]; then
            echo "[ERROR] Required Docker secret value is empty: ${required_key}" >&2
            missing=$((missing + 1))
        fi
    done <<< "$required_keys"
    [ "$missing" -eq 0 ]
}

# ------------------------------------------------------------------------------
# _delete_temporary_secret_values_file
# ------------------------------------------------------------------------------
# Removes one plaintext values file without depending on import success. The
# operation is idempotent so validation, editor, signal, and Docker failures can
# all share the same cleanup boundary.
#
# Arguments:
#   $1 - Secret values file.
#
# Returns:
#   0 when the file is absent or deleted; otherwise 1.
# ------------------------------------------------------------------------------
_delete_temporary_secret_values_file() {
    local secrets_file="$1"

    if [ ! -e "$secrets_file" ]; then
        return 0
    fi
    if rm -f -- "$secrets_file" 2>/dev/null; then
        echo "[OK] Deleted temporary secret values file: $secrets_file"
        return 0
    fi
    echo "[ERROR] Temporary secret values file could not be deleted:" >&2
    echo "        $secrets_file" >&2
    return 1
}

# ------------------------------------------------------------------------------
# _handle_failed_secret_values_file
# ------------------------------------------------------------------------------
# Applies the caller's plaintext policy when editing, validation, or Docker
# creation fails. Ephemeral `always` files are removed; restore inputs remain
# available under the explicit `prompt` and `keep` policies.
#
# Arguments:
#   $1 - Secret values file.
#   $2 - Deletion mode: prompt, always, or keep.
#
# Returns:
#   Cleanup status for ephemeral files; otherwise 0.
# ------------------------------------------------------------------------------
_handle_failed_secret_values_file() {
    local secrets_file="$1"
    local deletion_mode="$2"

    if [ "$deletion_mode" = "always" ]; then
        _delete_temporary_secret_values_file "$secrets_file"
        return $?
    fi
    if [ -e "$secrets_file" ]; then
        echo "[WARN] $secrets_file was retained for correction or restore retry."
        echo "       Delete it securely when it is no longer needed."
    fi
    return 0
}

# ------------------------------------------------------------------------------
# _abort_secret_values_file_workflow
# ------------------------------------------------------------------------------
# Deletes an ephemeral values file before terminating for an operator signal.
# Signal termination intentionally stops the quick-start process after cleanup.
#
# Arguments:
#   $1 - Secret values file.
#   $2 - Deletion mode.
#   $3 - Conventional signal exit status.
#
# Side effects:
#   May delete the values file and exits the current shell process.
# ------------------------------------------------------------------------------
_abort_secret_values_file_workflow() {
    local secrets_file="$1"
    local deletion_mode="$2"
    local exit_status="$3"

    echo "" >&2
    echo "[WARN] Secret-file workflow interrupted." >&2
    _handle_failed_secret_values_file \
        "$secrets_file" \
        "$deletion_mode" || true
    trap - HUP INT TERM
    exit "$exit_status"
}

# ------------------------------------------------------------------------------
# _restore_secret_values_file_trap
# ------------------------------------------------------------------------------
# Restores one caller-owned signal trap after an uninterrupted import.
#
# Arguments:
#   $1 - Signal name.
#   $2 - Prior `trap -p` declaration, or empty for the default handler.
# ------------------------------------------------------------------------------
_restore_secret_values_file_trap() {
    local signal_name="$1"
    local prior_declaration="$2"

    if [ -n "$prior_declaration" ]; then
        eval "$prior_declaration"
    else
        trap - "$signal_name"
    fi
}

# ------------------------------------------------------------------------------
# _finalize_secret_values_file
# ------------------------------------------------------------------------------
# Applies the caller-selected plaintext-file retention policy after every
# Docker secret has been created or retained successfully.
#
# Arguments:
#   $1 - Secret values file.
#   $2 - Deletion mode: prompt, always, or keep.
#
# Returns:
#   0 after applying the policy; otherwise 1.
# ------------------------------------------------------------------------------
_finalize_secret_values_file() {
    local secrets_file="$1"
    local deletion_mode="$2"
    local delete_file=""

    case "$deletion_mode" in
        always)
            _delete_temporary_secret_values_file "$secrets_file"
            ;;
        keep)
            echo "[WARN] $secrets_file still exists and may contain sensitive values."
            ;;
        prompt)
            echo ""
            read -p "Delete $secrets_file now? (recommended) (Y/n): " delete_file
            delete_file="${delete_file:-Y}"
            if [[ "$delete_file" =~ ^[Yy]$ ]]; then
                if rm -f "$secrets_file" 2>/dev/null; then
                    echo "✅ Deleted $secrets_file"
                else
                    echo "[ERROR] Could not delete $secrets_file" >&2
                    return 1
                fi
            else
                echo "⚠️  $secrets_file still exists and may contain sensitive values."
                echo "   Please delete it soon: rm -f \"$secrets_file\""
            fi
            ;;
        *)
            echo "[ERROR] Unknown secret values-file deletion mode: ${deletion_mode}" >&2
            return 1
            ;;
    esac
}

# ------------------------------------------------------------------------------
# _prepare_secret_values_file
# ------------------------------------------------------------------------------
# Creates or refreshes the private plaintext file used by one import attempt.
#
# Arguments:
#   $1 - Secret values file.
#   $2 - Source template file.
#
# Returns:
#   0 when the file is ready with mode 0600; otherwise 1.
#
# Side effects:
#   May copy the template and append newly declared template entries.
# ------------------------------------------------------------------------------
_prepare_secret_values_file() {
    local secrets_file="$1"
    local template_file="$2"

    if [ ! -f "$secrets_file" ]; then
        if [ ! -f "$template_file" ]; then
            echo "[ERROR] Template not found: $template_file" >&2
            return 1
        fi
        if ! install -m 600 -- "$template_file" "$secrets_file"; then
            echo "[ERROR] Could not create temporary values file: $secrets_file" >&2
            return 1
        fi
        echo "✅ Created $secrets_file from template"
    fi
    if ! chmod 600 "$secrets_file"; then
        echo "[ERROR] Could not restrict temporary values file permissions:" >&2
        echo "        $secrets_file" >&2
        return 1
    fi
    if declare -F sync_missing_secret_template_entries >/dev/null 2>&1 &&
        ! sync_missing_secret_template_entries "$secrets_file" "$template_file"; then
        echo "[ERROR] Could not synchronize the secret values template." >&2
        return 1
    fi
    return 0
}

# ------------------------------------------------------------------------------
# _edit_secret_values_file
# ------------------------------------------------------------------------------
# Lets the operator edit one prepared values file and reports editor failures.
#
# Arguments:
#   $1 - Secret values file.
#   $2 - Optional Docker secret-name prefix shown in guidance.
#
# Returns:
#   0 after the editor/manual confirmation completes; otherwise 1.
#
# Side effects:
#   Prompts the operator and may launch the selected terminal editor.
# ------------------------------------------------------------------------------
_edit_secret_values_file() {
    local secrets_file="$1"
    local prefix="$2"

    echo ""
    echo "📝 Please edit $secrets_file and fill in your secret values."
    if [ -n "$prefix" ]; then
        echo "   Secret names will be prefixed with: ${prefix}_"
    else
        echo "   Secret names will be used exactly as written in the file."
    fi
    echo ""
    if choose_editor; then
        if ! read -r -p "Press Enter to open $secrets_file in $SELECTED_EDITOR..."; then
            echo "[ERROR] Secret-file editing was cancelled before the editor opened." >&2
            return 1
        fi
        echo ""
        if ! "$SELECTED_EDITOR" "$secrets_file"; then
            echo "[ERROR] Editor exited before the secret values were accepted." >&2
            return 1
        fi
        echo ""
        echo "[OK] File saved: $secrets_file"
        echo ""
        return 0
    fi
    echo "⚠️  No editor found. Please edit $secrets_file manually, then continue."
    if ! read -r -p "Press Enter when ready to create secrets..."; then
        echo "[ERROR] Secret-file editing was cancelled." >&2
        return 1
    fi
    echo ""
    return 0
}

# ------------------------------------------------------------------------------
# _import_secret_values_file
# ------------------------------------------------------------------------------
# Parses validated values and creates or retains the corresponding Docker
# secrets without deciding whether the plaintext source file is retained.
#
# Arguments:
#   $1 - Validated secret values file.
#   $2 - Optional Docker secret-name prefix.
#
# Returns:
#   0 when every non-empty value was created or retained; otherwise 1.
#
# Side effects:
#   May create or replace Docker secrets and prints a secret-free summary.
# ------------------------------------------------------------------------------
_import_secret_values_file() {
    local secrets_file="$1"
    local prefix="$2"
    local key=""
    local value=""
    local full_name=""
    local created=0
    local skipped=0
    local kept=0
    local failed=0

    while IFS='=' read -r key value || [ -n "$key" ]; do
        key="${key%$'\r'}"
        value="${value%$'\r'}"
        key="${key#"${key%%[![:space:]]*}"}"
        key="${key%"${key##*[![:space:]]}"}"
        case "$key" in
            export\ *) key="${key#export }" ;;
            ""|\#*) continue ;;
        esac
        value="${value#\"}"
        value="${value%\"}"
        value="${value#\'}"
        value="${value%\'}"
        if [ -z "$value" ]; then
            skipped=$((skipped + 1))
            continue
        fi
        full_name="$key"
        if [ -n "$prefix" ]; then
            full_name="${prefix}_${key}"
        fi
        if create_secret_from_value "$full_name" "$value"; then
            case "${CREATE_SECRET_FROM_VALUE_ACTION:-created}" in
                created)
                    echo "✅ Secret created: $full_name"
                    created=$((created + 1))
                    ;;
                kept) kept=$((kept + 1)) ;;
                empty) skipped=$((skipped + 1)) ;;
            esac
        else
            failed=$((failed + 1))
        fi
    done < "$secrets_file"
    echo ""
    echo "✅ Created $created secret(s)"
    [ "$kept" -eq 0 ] || echo "   Kept $kept existing secret(s)"
    [ "$skipped" -eq 0 ] || echo "   Skipped $skipped empty value(s)"
    if [ "$failed" -gt 0 ]; then
        echo "[ERROR] Failed to create or replace $failed secret(s)."
        return 1
    fi
    return 0
}

# ------------------------------------------------------------------------------
# create_secrets_from_env_file
# ------------------------------------------------------------------------------
# Creates Docker secrets from a secrets.env file. This is the main workflow
# function that orchestrates the entire secrets.env lifecycle:
# - Creates secrets.env from template if it doesn't exist
# - Syncs missing keys from template to existing secrets.env
# - Allows user to edit the file with their chosen editor
# - Creates Docker secrets from the file values
# - Applies a caller-selected cleanup policy to the plaintext values file
#
# Arguments:
#   $1 - secrets_file: path to secrets.env (default: secrets.env)
#   $2 - template_file: path to template (default: setup/templates/secrets.env.template)
#   $3 - prefix: optional secret name prefix (for example, myapp)
#   $4 - allowed_keys: optional newline-separated exact-name allowlist
#   $5 - enforce_allowlist: true for exact-name profile enforcement; false by
#        default for legacy prefixed imports.
#   $6 - deletion mode: prompt (default), keep, or always. `always` marks the
#        file ephemeral and deletes it after success, failure, or interruption.
#   $7 - required_keys: optional newline-separated keys that must have values.
#
# Returns:
#   0 on success, 1 on failure
#
# Dependencies:
#   - choose_editor from user-prompts.sh
#   - sync_missing_secret_template_entries from secrets_template_sync.sh
# ------------------------------------------------------------------------------
create_secrets_from_env_file() {
    local secrets_file="${1:-secrets.env}"
    local template_file="${2:-setup/templates/secrets.env.template}"
    local prefix="${3:-}"
    local allowed_keys="${4:-}"
    local enforce_allowlist="${5:-false}"
    local deletion_mode="${6:-prompt}"
    local required_keys="${7:-}"
    local prior_hup_trap=""
    local prior_int_trap=""
    local prior_term_trap=""
    local status=0

    echo ""
    echo "🔐 Create Docker Secrets from File"
    echo "==================================="
    echo ""
    if [ "$deletion_mode" = "always" ]; then
        echo "[INFO] This temporary values file is deleted when the workflow ends,"
        echo "       including after validation/import errors or interruption."
        echo ""
    fi
    prior_hup_trap="$(trap -p HUP)"
    prior_int_trap="$(trap -p INT)"
    prior_term_trap="$(trap -p TERM)"
    trap '_abort_secret_values_file_workflow "$secrets_file" "$deletion_mode" 129' HUP
    trap '_abort_secret_values_file_workflow "$secrets_file" "$deletion_mode" 130' INT
    trap '_abort_secret_values_file_workflow "$secrets_file" "$deletion_mode" 143' TERM

    if ! _prepare_secret_values_file "$secrets_file" "$template_file"; then
        status=1
    elif ! _edit_secret_values_file "$secrets_file" "$prefix"; then
        status=1
    elif ! _validate_secret_env_keys \
        "$secrets_file" "$allowed_keys" "$enforce_allowlist"; then
        echo "[ERROR] No Docker secrets were changed."
        status=1
    elif ! _validate_required_secret_env_values \
        "$secrets_file" "$required_keys"; then
        echo "[ERROR] No Docker secrets were changed."
        status=1
    elif ! _import_secret_values_file "$secrets_file" "$prefix"; then
        status=1
    fi

    if [ "$status" -eq 0 ]; then
        _finalize_secret_values_file \
            "$secrets_file" "$deletion_mode" || status=1
    else
        _handle_failed_secret_values_file \
            "$secrets_file" "$deletion_mode" || true
    fi
    _restore_secret_values_file_trap HUP "$prior_hup_trap"
    _restore_secret_values_file_trap INT "$prior_int_trap"
    _restore_secret_values_file_trap TERM "$prior_term_trap"
    return "$status"
}
