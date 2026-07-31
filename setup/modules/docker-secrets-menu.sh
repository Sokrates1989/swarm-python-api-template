#!/bin/bash
# ==============================================================================
# docker-secrets-menu.sh - Site-profile-driven Docker secret management
# ==============================================================================
#
# Profiles declare required, optional, capability, pgAdmin, and Keycloak secret
# names plus their exact/prefixed naming policy in site config. This module
# routes only on that declared policy; renderer type and application identity
# never select a secret workflow.
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

# _rendered_required_secret_names
# Lists exact top-level Docker secret identifiers from the rendered stack.
#
# The rendered stack is the final capability-normalized contract: disabled
# optional services have already been removed and both renderer families have
# resolved their secret-name strategy. Reading only the top-level `secrets`
# mapping avoids confusing service-level secret mounts with declarations.
#
# Arguments:
#   $1 - Rendered Swarm stack path.
#
# Outputs:
#   One exact Docker secret identifier per line.
#
# Returns:
#   0 when the stack can be inspected; 1 when it is missing.
_rendered_required_secret_names() {
    local stack_file="$1"

    if [ ! -f "$stack_file" ]; then
        echo "[ERROR] Rendered stack is missing: ${stack_file}" >&2
        return 1
    fi
    awk '
      /^secrets:[[:space:]]*$/ {
        in_secrets = 1
        next
      }
      in_secrets && /^[^[:space:]#]/ {
        exit
      }
      in_secrets && /^  [^[:space:]][^:]*:[[:space:]]*$/ {
        name = $0
        sub(/^[[:space:]]+/, "", name)
        sub(/:[[:space:]]*$/, "", name)
        gsub(/^"|"$/, "", name)
        print name
      }
    ' "$stack_file"
}

# verify_required_docker_secrets
# Fails closed unless every external secret declared by the rendered stack
# exists in Docker Swarm.
#
# Arguments:
#   $1 - Rendered Swarm stack path.
#
# Returns:
#   0 when all declared secrets exist (or none are declared); otherwise 1.
verify_required_docker_secrets() {
    local stack_file="$1"
    local secret_name=""
    local secret_count=0
    local missing_count=0

    if [ ! -f "$stack_file" ]; then
        echo "[ERROR] Rendered stack is missing: ${stack_file}"
        return 1
    fi
    echo ""
    echo "Required Docker secret verification"
    echo "-----------------------------------"
    while IFS= read -r secret_name; do
        [ -n "$secret_name" ] || continue
        secret_count=$((secret_count + 1))
        if ! _secret_status_line "$secret_name"; then
            missing_count=$((missing_count + 1))
        fi
    done < <(_rendered_required_secret_names "$stack_file")

    if [ "$secret_count" -eq 0 ]; then
        echo "[OK] This rendered stack declares no Docker secrets."
        return 0
    fi
    if [ "$missing_count" -gt 0 ]; then
        echo "[ERROR] ${missing_count} required Docker secret(s) are missing."
        echo "        Open the secret menu or Keycloak bootstrap, then retry."
        return 1
    fi
    echo "[OK] All ${secret_count} required Docker secret(s) exist."
    return 0
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

# _legacy_admin_ui_secret_name
# Resolves the enabled database-management secret from profile data.
#
# The legacy renderer prefixes site-config secret suffixes with the selected
# deployment prefix. Disabled admin UIs intentionally return no secret name.
#
# Arguments:
#   $1 - Normalized uppercase legacy secret prefix.
#
# Outputs:
#   Exact Docker secret name, or empty text when the capability is disabled.
#
# Returns:
#   0 when disabled or valid; 1 when enabled without a safe declared suffix.
_legacy_admin_ui_secret_name() {
    local prefix_upper="$1"
    local secret_suffix="${APP_ADMIN_UI_SECRET:-}"

    if [ "${PGADMIN_ENABLED:-false}" != "true" ]; then
        return 0
    fi
    if [ -z "$secret_suffix" ] &&
        [ -n "${APP_CONFIG_FILE:-}" ] &&
        [ -f "$APP_CONFIG_FILE" ] &&
        command -v jq >/dev/null 2>&1; then
        secret_suffix="$(jq -r '.adminUI.secret // empty' "$APP_CONFIG_FILE")"
    fi
    if [[ ! "$secret_suffix" =~ ^[A-Z0-9_]+$ ]]; then
        echo "[ERROR] Enabled admin UI requires a safe adminUI.secret suffix." >&2
        return 1
    fi
    printf '%s_%s' "$prefix_upper" "$secret_suffix"
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

# _profile_secrets_use_exact_names
# Checks whether the selected profile owns literal Docker secret identifiers.
#
# Returns:
#   0 only when secretsConfig.prefixed is explicitly false.
_profile_secrets_use_exact_names() {
    local profile_file=""

    profile_file="$(_active_profile_json)" || return 1
    jq -e '.secretsConfig.prefixed == false' "$profile_file" >/dev/null
}

# Batch file import is a separate profile-policy adapter.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/profile-secret-file-workflow.sh"

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
# Runs the common exact-name secret menu for any profile declaring literal names.
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
    local next_choice=3
    local template_choice=""
    local keycloak_bootstrap_choice=""
    local keycloak_rotation_choice=""
    local list_choice=""
    local max_choice=""
    local keycloak_status=0

    if declare -F profile_supports_keycloak_bootstrap >/dev/null 2>&1 &&
        profile_supports_keycloak_bootstrap; then
        keycloak_available="true"
    fi
    if _profile_declares_secret_template; then
        template_choice="$next_choice"
        next_choice=$((next_choice + 1))
    fi
    if [ "$keycloak_available" = "true" ]; then
        keycloak_bootstrap_choice="$next_choice"
        next_choice=$((next_choice + 1))
        keycloak_rotation_choice="$next_choice"
        next_choice=$((next_choice + 1))
    fi
    list_choice="$next_choice"
    max_choice="$next_choice"

    while true; do
        _show_profile_secret_status
        echo ""
        echo "  1) Create or replace a required secret"
        echo "  2) Create or replace an optional secret"
        if [ -n "$template_choice" ]; then
            echo "  ${template_choice}) Create secrets from the profile template"
        fi
        if [ -n "$keycloak_bootstrap_choice" ]; then
            echo "  ${keycloak_bootstrap_choice}) Bootstrap/update Keycloak and create a missing client secret"
            echo "  ${keycloak_rotation_choice}) Rotate the Keycloak client Docker secret"
        fi
        echo "  ${list_choice}) List all Docker secrets"
        echo "  0) Back"
        read -r -p "Secret choice (0-${max_choice}): " choice
        if [ "$choice" = "0" ]; then
            return "$keycloak_status"
        elif [ "$choice" = "1" ]; then
            _create_selected_profile_secret required || true
        elif [ "$choice" = "2" ]; then
            _create_selected_profile_secret optional || true
        elif [ -n "$template_choice" ] &&
            [ "$choice" = "$template_choice" ]; then
            create_profile_secrets_from_env_file \
                "${PROJECT_ROOT}/secrets.env" || true
        elif [ -n "$keycloak_bootstrap_choice" ] &&
            [ "$choice" = "$keycloak_bootstrap_choice" ]; then
            if run_profile_keycloak_bootstrap; then
                keycloak_status=0
            else
                keycloak_status=$?
                echo "[ERROR] Keycloak bootstrap did not complete."
            fi
        elif [ -n "$keycloak_rotation_choice" ] &&
            [ "$choice" = "$keycloak_rotation_choice" ]; then
            if run_profile_keycloak_secret_rotation; then
                keycloak_status=0
            else
                keycloak_status=$?
                echo "[ERROR] Keycloak secret rotation did not complete."
            fi
        elif [ "$choice" = "$list_choice" ]; then
            list_docker_secrets
        else
            echo "[WARN] Enter a displayed menu value."
        fi
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
    local db_ui_admin_password_secret=""

    prefix_upper="$(_generic_secret_prefix)"
    db_password_secret="${prefix_upper}_DB_PASSWORD"
    admin_api_key_secret="${prefix_upper}_ADMIN_API_KEY"
    backup_restore_api_key_secret="${prefix_upper}_BACKUP_RESTORE_API_KEY"
    backup_delete_api_key_secret="${prefix_upper}_BACKUP_DELETE_API_KEY"
    db_ui_admin_password_secret="$(
        _legacy_admin_ui_secret_name "$prefix_upper"
    )" || return 1
    echo ""
    echo "Legacy prefixed Docker secrets (${prefix_upper}*)"
    _secret_status_line "$db_password_secret" || true
    _secret_status_line "$admin_api_key_secret" || true
    _secret_status_line "$backup_restore_api_key_secret" || true
    _secret_status_line "$backup_delete_api_key_secret" || true
    if [ -n "$db_ui_admin_password_secret" ]; then
        _secret_status_line "$db_ui_admin_password_secret" || true
    fi
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
                "$backup_delete_api_key_secret" \
                "$db_ui_admin_password_secret"
            ;;
        3) list_docker_secrets ;;
        0) ;;
        *) echo "[WARN] Enter a value from 0 through 3." ;;
    esac
    return 0
}

# manage_docker_secrets_menu
# Routes by the profile-declared naming policy, never by schema or app identity.
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

    if _profile_secrets_use_exact_names; then
        _manage_profile_docker_secrets
        return $?
    fi
    _manage_legacy_docker_secrets
}
