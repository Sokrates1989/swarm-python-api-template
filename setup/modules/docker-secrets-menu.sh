#!/bin/bash
# ==============================================================================
# docker-secrets-menu.sh - Site-profile-driven Docker secret management
# ==============================================================================
#
# Executable profiles declare exact required, optional, capability, pgAdmin,
# and Keycloak secret names in their site config. This module presents one
# shared workflow for all such profiles. Older profile schemas retain the
# historical prefixed-secret workflow while they are migrated.
# ==============================================================================

# _secret_status_line
# Prints one Docker secret existence result without reading its value.
#
# Arguments:
#   $1 - Exact Docker secret name.
#
# Returns:
#   0 when the secret exists; 1 otherwise.
_secret_status_line() {
    local secret_name="$1"

    if docker secret inspect "$secret_name" >/dev/null 2>&1; then
        echo "[OK]      ${secret_name}"
        return 0
    fi
    echo "[MISSING] ${secret_name}"
    return 1
}

# _secret_editor
# Selects the first installed supported terminal editor.
#
# Arguments:
#   None.
#
# Outputs:
#   Editor command.
#
# Returns:
#   0 when nano, vim, or vi is available; 1 otherwise.
_secret_editor() {
    local editor=""

    for editor in nano vim vi; do
        if command -v "$editor" >/dev/null 2>&1; then
            printf '%s\n' "$editor"
            return 0
        fi
    done
    return 1
}

# _generic_secret_prefix
# Resolves the historical uppercase prefix for legacy profile schemas.
#
# Arguments:
#   None.
#
# Outputs:
#   Uppercase identifier prefix.
#
# Returns:
#   0 always.
_generic_secret_prefix() {
    printf '%s' "${SECRET_PREFIX:-$STACK_NAME}" |
        tr '[:lower:]' '[:upper:]' |
        sed 's/[^A-Z0-9]/_/g'
}

# _require_stopped_stack_for_secret_change
# Requires an explicit choice before removing a stack that uses a secret.
#
# Arguments:
#   None. Reads STACK_NAME.
#
# Returns:
#   0 when no stack is running or confirmed removal completes; 1 otherwise.
#
# Side effects:
#   May remove the selected stack after explicit operator confirmation.
_require_stopped_stack_for_secret_change() {
    local remove_stack=""

    if ! docker stack ls --format "{{.Name}}" 2>/dev/null |
        grep -q "^${STACK_NAME}$"; then
        return 0
    fi
    echo "[WARN] Stack '${STACK_NAME}' is running and may use this secret."
    read -r -p "Remove the stack before replacing the secret? (y/N): " remove_stack
    if [[ ! "$remove_stack" =~ ^[Yy]$ ]]; then
        echo "[INFO] Secret replacement cancelled."
        return 1
    fi
    docker stack rm "$STACK_NAME"
    echo "Waiting for stack removal..."
    while docker stack ls --format "{{.Name}}" 2>/dev/null |
        grep -q "^${STACK_NAME}$"; do
        sleep 2
    done
    echo "[OK] Stack removed."
    return 0
}

# _active_profile_json
# Resolves the currently selected executable profile path.
#
# Arguments:
#   None.
#
# Outputs:
#   Absolute site-config path.
#
# Returns:
#   0 when the selected profile exists; 1 otherwise.
_active_profile_json() {
    if declare -F _profile_config_file >/dev/null 2>&1; then
        _profile_config_file
        return $?
    fi
    local profile_id="${DEPLOYMENT_PROFILE_ID:-${BACKEND_APP_ID:-}}"
    local path="${PROJECT_ROOT}/site-configs/${profile_id}.json"

    [ -n "$profile_id" ] && [ -f "$path" ] || return 1
    printf '%s\n' "$path"
}

# _profile_required_secret_names
# Lists every active required secret declared by the selected site profile.
#
# Base secrets, enabled-capability mounts, and enabled pgAdmin secrets are
# merged and deduplicated. Optional inactive secrets are not included.
#
# Arguments:
#   None.
#
# Outputs:
#   One exact Docker secret name per line.
#
# Returns:
#   jq status.
_profile_required_secret_names() {
    local profile_file=""

    profile_file="$(_active_profile_json)" || return 1
    jq -r --arg pgadmin "${PGADMIN_ENABLED:-false}" '
      [
        .secrets[]?,
        (.capabilities // {} | to_entries[] |
          select(.value.enabled == true) |
          .value.secretMounts[]?.name),
        (if $pgadmin == "true" then .database.pgadminSecret // empty else empty end)
      ]
      | map(select(type == "string" and length > 0))
      | unique[]
    ' "$profile_file"
}

# _profile_optional_secret_names
# Lists declared optional secrets that are not currently required.
#
# Arguments:
#   None.
#
# Outputs:
#   One exact Docker secret name per line.
#
# Returns:
#   jq status.
_profile_optional_secret_names() {
    local profile_file=""
    local required_json=""

    profile_file="$(_active_profile_json)" || return 1
    required_json=$(_profile_required_secret_names |
        jq -Rsc 'split("\n") | map(select(length > 0))')
    jq -r --argjson required "$required_json" '
      [ .optionalSecrets[]? ]
      | map(select(type == "string" and length > 0))
      | unique
      | map(select(. as $name | $required | index($name) | not))
      | .[]
    ' "$profile_file"
}

# _profile_secret_is_keycloak
# Checks whether one declared secret supplies a Keycloak client-secret file.
#
# Arguments:
#   $1 - Exact Docker secret name.
#
# Returns:
#   0 for the profile's Keycloak client secret; 1 otherwise.
_profile_secret_is_keycloak() {
    local secret_name="$1"
    local profile_file=""

    profile_file="$(_active_profile_json)" || return 1
    jq -e --arg name "$secret_name" '
      [
        .secretMounts[]?,
        (.capabilities // {} | to_entries[] |
          select(.value.enabled == true) |
          .value.secretMounts[]?)
      ]
      | any(
          .name == $name and
          (
            .envKey == "KEYCLOAK_ADMIN_CLIENT_SECRET_FILE" or
            .envKey == "KEYCLOAK_CLIENT_SECRET_FILE"
          )
        )
    ' "$profile_file" >/dev/null
}

# _show_profile_secret_status
# Displays required and optional secret metadata for an executable profile.
#
# Arguments:
#   None.
#
# Returns:
#   0 after querying Docker secret metadata.
_show_profile_secret_status() {
    local secret_name=""
    local had_required="false"
    local had_optional="false"

    echo ""
    echo "Profile Docker secrets"
    echo "----------------------"
    echo "Required now:"
    while IFS= read -r secret_name; do
        [ -n "$secret_name" ] || continue
        had_required="true"
        _secret_status_line "$secret_name" || true
    done < <(_profile_required_secret_names)
    if [ "$had_required" = "false" ]; then
        echo "  (none)"
    fi
    echo ""
    echo "Optional / inactive:"
    while IFS= read -r secret_name; do
        [ -n "$secret_name" ] || continue
        had_optional="true"
        _secret_status_line "$secret_name" || true
    done < <(_profile_optional_secret_names)
    if [ "$had_optional" = "false" ]; then
        echo "  (none)"
    fi
}

# _select_profile_secret
# Prompts for one secret from a newline-delimited declared-name list.
#
# Arguments:
#   $1 - Menu label.
#   $2 - Newline-delimited secret names.
#
# Outputs:
#   Selected exact secret name.
#
# Returns:
#   0 after a valid selection; 1 when the list is empty or selection is invalid.
_select_profile_secret() {
    local label="$1"
    local names="$2"
    local choice=""
    local index=1
    local -a secrets=()
    local secret_name=""

    while IFS= read -r secret_name; do
        [ -n "$secret_name" ] && secrets+=("$secret_name")
    done <<< "$names"
    if [ "${#secrets[@]}" -eq 0 ]; then
        echo "[INFO] No ${label} secrets are declared."
        return 1
    fi
    echo ""
    echo "Select ${label} secret:"
    for secret_name in "${secrets[@]}"; do
        echo "  ${index}) ${secret_name}"
        index=$((index + 1))
    done
    echo "  0) Cancel"
    read -r -p "Secret choice (0-$((index - 1))): " choice
    if [ "$choice" = "0" ]; then
        return 1
    fi
    if ! [[ "$choice" =~ ^[0-9]+$ ]] ||
        [ "$choice" -lt 1 ] ||
        [ "$choice" -ge "$index" ]; then
        echo "[WARN] Invalid secret selection."
        return 1
    fi
    printf '%s\n' "${secrets[$((choice - 1))]}"
}

# _create_profile_editor_secret
# Creates or replaces one allowlisted profile secret using a mode-0600 temp file.
#
# Arguments:
#   $1 - Exact site-config-declared secret name.
#
# Returns:
#   0 after creation or keeping an existing secret; 1 on cancellation/failure.
#
# Side effects:
#   Opens a terminal editor and may mutate Docker secret state.
_create_profile_editor_secret() {
    local secret_name="$1"
    local editor=""
    local temporary=""
    local replace=""

    if _profile_secret_is_keycloak "$secret_name"; then
        echo "[INFO] Keycloak client secrets are transferred only by the"
        echo "       profile-driven Keycloak bootstrap; manual entry is disabled."
        return 1
    fi
    editor="$(_secret_editor)" || {
        echo "[ERROR] Install nano, vim, or vi for protected secret entry."
        return 1
    }
    if docker secret inspect "$secret_name" >/dev/null 2>&1; then
        read -r -p "Secret exists. Replace it? (y/N): " replace
        if [[ ! "$replace" =~ ^[Yy]$ ]]; then
            echo "[INFO] Keeping existing secret."
            return 0
        fi
        _require_stopped_stack_for_secret_change || return 1
    fi
    temporary=$(mktemp)
    chmod 600 "$temporary"
    echo ""
    echo "Enter the value for ${secret_name}. Save and close the editor."
    "$editor" "$temporary"
    if [ ! -s "$temporary" ]; then
        echo "[WARN] Secret was empty; nothing changed."
        rm -f "$temporary"
        return 1
    fi
    if docker secret inspect "$secret_name" >/dev/null 2>&1; then
        docker secret rm "$secret_name" >/dev/null || {
            echo "[ERROR] Existing Docker secret could not be removed."
            rm -f "$temporary"
            return 1
        }
    fi
    if ! docker secret create "$secret_name" "$temporary" >/dev/null; then
        echo "[ERROR] Docker secret creation failed."
        rm -f "$temporary"
        return 1
    fi
    rm -f "$temporary"
    echo "[OK] Docker secret is ready: ${secret_name}"
    return 0
}

# _create_selected_profile_secret
# Selects and creates one required or optional profile secret.
#
# Arguments:
#   $1 - required or optional.
#
# Returns:
#   Selected creation flow status.
_create_selected_profile_secret() {
    local category="$1"
    local names=""
    local selected=""

    if [ "$category" = "required" ]; then
        names="$(_profile_required_secret_names)"
    else
        names="$(_profile_optional_secret_names)"
    fi
    selected="$(_select_profile_secret "$category" "$names")" || return 1
    _create_profile_editor_secret "$selected"
}

# _manage_profile_docker_secrets
# Runs the common exact-name secret menu for any executable site profile.
#
# Arguments:
#   None.
#
# Returns:
#   0 after returning to the caller.
#
# Side effects:
#   Depends on the explicitly selected secret or Keycloak action.
_manage_profile_docker_secrets() {
    local choice=""
    local keycloak_available="false"

    if declare -F profile_uses_keycloak >/dev/null 2>&1 &&
        profile_uses_keycloak; then
        keycloak_available="true"
    fi
    while true; do
        _show_profile_secret_status
        echo ""
        echo "  1) Create or replace a required secret"
        echo "  2) Create or replace an optional secret"
        if [ "$keycloak_available" = "true" ]; then
            echo "  3) Bootstrap/update Keycloak and create a missing client secret"
            echo "  4) Rotate the Keycloak client Docker secret"
        else
            echo "  3) Keycloak bootstrap (not declared by this profile)"
            echo "  4) Keycloak secret rotation (not declared by this profile)"
        fi
        echo "  5) List all Docker secrets"
        echo "  0) Back"
        read -r -p "Secret choice (0-5): " choice
        case "$choice" in
            1) _create_selected_profile_secret required || true ;;
            2) _create_selected_profile_secret optional || true ;;
            3)
                if [ "$keycloak_available" = "true" ]; then
                    run_profile_keycloak_bootstrap || true
                else
                    echo "[INFO] The selected profile does not use Keycloak."
                fi
                ;;
            4)
                if [ "$keycloak_available" = "true" ]; then
                    run_profile_keycloak_secret_rotation || true
                else
                    echo "[INFO] The selected profile does not use Keycloak."
                fi
                ;;
            5) list_docker_secrets ;;
            0) return 0 ;;
            *) echo "[WARN] Enter a value from 0 through 5." ;;
        esac
    done
}

# _manage_legacy_docker_secrets
# Preserves the historical prefixed workflow for profiles not yet on schema 5.
#
# Arguments:
#   None.
#
# Returns:
#   0 after one action.
#
# Side effects:
#   May create legacy prefixed Docker secrets or remove a confirmed stack.
_manage_legacy_docker_secrets() {
    local prefix_upper=""
    local choice=""
    local db_password_secret=""
    local admin_api_key_secret=""
    local backup_restore_api_key_secret=""
    local backup_delete_api_key_secret=""

    prefix_upper="$(_generic_secret_prefix)"
    db_password_secret="${prefix_upper}_DB_PASSWORD"
    admin_api_key_secret="${prefix_upper}_ADMIN_API_KEY"
    backup_restore_api_key_secret="${prefix_upper}_BACKUP_RESTORE_API_KEY"
    backup_delete_api_key_secret="${prefix_upper}_BACKUP_DELETE_API_KEY"
    echo ""
    echo "Legacy prefixed Docker secrets (${prefix_upper}*)"
    _secret_status_line "$db_password_secret" || true
    _secret_status_line "$admin_api_key_secret" || true
    _secret_status_line "$backup_restore_api_key_secret" || true
    _secret_status_line "$backup_delete_api_key_secret" || true
    echo ""
    echo "  1) Create secrets from secrets.env file"
    echo "  2) Create secrets interactively"
    echo "  3) List all Docker secrets"
    echo "  0) Back"
    read -r -p "Secret choice (0-3): " choice
    case "$choice" in
        1)
            _require_stopped_stack_for_secret_change || return 0
            create_secrets_from_env_file \
                "secrets.env" \
                "${PROJECT_ROOT}/setup/templates/secrets.env.template" \
                "$prefix_upper"
            ;;
        2)
            _require_stopped_stack_for_secret_change || return 0
            create_docker_secrets \
                "$db_password_secret" \
                "$admin_api_key_secret" \
                "$backup_restore_api_key_secret" \
                "$backup_delete_api_key_secret"
            ;;
        3) list_docker_secrets ;;
        0) ;;
        *) echo "[WARN] Enter a value from 0 through 3." ;;
    esac
    return 0
}

# manage_docker_secrets_menu
# Routes by profile schema capability, never by application identity.
#
# Arguments:
#   None.
#
# Returns:
#   0 after the selected shared workflow returns.
manage_docker_secrets_menu() {
    echo ""
    echo "Manage Docker secrets"
    echo "====================="

    if declare -F profile_uses_executable_renderer >/dev/null 2>&1 &&
        profile_uses_executable_renderer; then
        _manage_profile_docker_secrets
        return $?
    fi
    _manage_legacy_docker_secrets
}
