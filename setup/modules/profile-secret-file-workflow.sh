#!/bin/bash
# ==============================================================================
# profile-secret-file-workflow.sh - Profile-constrained batch secret import
# ==============================================================================
#
# Resolves a site-config-declared secret template and imports its values through
# the shared secret manager. Exact-name profiles receive an allowlist derived
# from their active capabilities so an edited values file cannot create an
# undeclared Docker secret.
#
# Dependencies:
#   - _active_profile_json, _profile_secrets_use_exact_names, and
#     _generic_secret_prefix from docker-secrets-menu.sh
#   - create_secrets_from_env_file from secret-manager.sh
# ==============================================================================

# Guard against multiple sourcing.
if [ -n "${_PROFILE_SECRET_FILE_WORKFLOW_LOADED:-}" ]; then
    return 0 2>/dev/null || true
fi
_PROFILE_SECRET_FILE_WORKFLOW_LOADED=1

# _profile_declares_secret_template
# Checks whether the selected profile explicitly provides a batch-entry file.
#
# Returns:
#   0 only when secretsConfig.template is a non-empty string.
_profile_declares_secret_template() {
    local profile_file=""

    profile_file="$(_active_profile_json)" || return 1
    jq -e '
      .secretsConfig.template
      | type == "string" and length > 0
    ' "$profile_file" >/dev/null
}

# profile_supports_secret_file_workflow
# Checks whether template-based batch entry is valid for this profile.
#
# Returns:
#   0 for prefixed profiles or exact-name profiles with at least one declared
#   importable secret; otherwise 1. A static template cannot make a
#   reconciliation-owned Keycloak credential manually editable.
profile_supports_secret_file_workflow() {
    if _profile_secrets_use_exact_names; then
        [ -n "$(_profile_batch_secret_names)" ]
        return $?
    fi
    return 0
}

# _profile_secrets_template_path
# Resolves the profile-declared secrets template or the shared legacy template.
#
# Outputs:
#   Absolute template path.
#
# Returns:
#   0 when the declared/default template exists and stays inside the repository;
#   otherwise 1.
_profile_secrets_template_path() {
    local profile_file=""
    local relative_path=""
    local template_path=""

    profile_file="$(_active_profile_json)" || return 1
    relative_path="$(jq -r '.secretsConfig.template // empty' "$profile_file")"
    if [ -z "$relative_path" ]; then
        if _profile_secrets_use_exact_names; then
            echo "[ERROR] Exact-name profile has no secrets template." >&2
            return 1
        fi
        relative_path="setup/templates/secrets.env.template"
    fi
    case "$relative_path" in
        ""|/*|*..*)
            echo "[ERROR] Profile secrets template path is unsafe." >&2
            return 1
            ;;
    esac
    template_path="${PROJECT_ROOT}/${relative_path}"
    if [ ! -f "$template_path" ]; then
        echo "[ERROR] Profile secrets template is missing: ${template_path}" >&2
        return 1
    fi
    printf '%s\n' "$template_path"
}

# _profile_batch_secret_names
# Lists every exact Docker secret identifier that the selected profile allows a
# batch values file to create. Disabled capabilities and inactive pgAdmin are
# excluded so adding a key to the values file cannot enable a service.
#
# Outputs:
#   One allowed exact secret name per line.
#
# Returns:
#   jq status.
_profile_batch_secret_names() {
    local profile_file=""

    profile_file="$(_active_profile_json)" || return 1
    jq -r --arg pgadmin "${PGADMIN_ENABLED:-false}" '
      (
        [
          .secretMounts[]?,
          (
            (.capabilities // {})
            | to_entries[]
            | select(.value.enabled == true)
            | .value.secretMounts[]?
          )
        ]
        | map(select(
            .envKey == "KEYCLOAK_ADMIN_CLIENT_SECRET_FILE" or
            .envKey == "KEYCLOAK_CLIENT_SECRET_FILE"
          ))
        | map(.name)
        | unique
      ) as $keycloakSecrets
      |
      [
        .secrets[]?,
        .optionalSecrets[]?,
        (
          (.capabilities // {})
          | to_entries[]
          | select(.value.enabled == true)
          | .value.secretMounts[]?.name
        ),
        (
          if $pgadmin == "true"
          then .database.pgadminSecret // empty
          else empty
          end
        )
      ]
      | map(select(type == "string" and length > 0))
      | unique
      | map(select(. as $name | $keycloakSecrets | index($name) | not))
      | .[]
    ' "$profile_file"
}

# _profile_batch_required_secret_names
# Lists active required exact-name secrets accepted by the batch importer.
# Reconciliation-owned Keycloak client secrets are deliberately omitted.
#
# Outputs:
#   One required exact Docker secret name per line.
#
# Returns:
#   Status from the active-profile helpers.
_profile_batch_required_secret_names() {
    local secret_name=""
    local required_names=""

    required_names="$(_profile_required_secret_names)" || return 1
    while IFS= read -r secret_name; do
        [ -n "$secret_name" ] || continue
        if ! _profile_secret_is_keycloak "$secret_name"; then
            printf '%s\n' "$secret_name"
        fi
    done <<< "$required_names"
}

# _profile_secret_value_help
# Reads profile-owned guidance for one editable secret value.
#
# Arguments:
#   $1 - Exact Docker secret identifier.
#
# Outputs:
#   Concise operator guidance with a safe generic fallback.
#
# Returns:
#   jq status.
_profile_secret_value_help() {
    local secret_name="$1"
    local profile_file=""

    profile_file="$(_active_profile_json)" || return 1
    jq -r --arg name "$secret_name" '
      .secretsConfig.valueHelp[$name] //
      "Enter the single-line value stored in this Docker secret."
    ' "$profile_file"
}

# _write_generated_profile_secrets_template
# Generates a mode-safe, commented values template entirely from site-profile
# declarations. Required and optional values remain distinguishable, while
# Keycloak client credentials stay excluded from manual entry.
#
# Arguments:
#   $1 - Destination template path.
#
# Returns:
#   0 after writing at least one editable secret; otherwise 1.
_write_generated_profile_secrets_template() {
    local destination="$1"
    local required_names=""
    local all_names=""
    local secret_name=""
    local help_text=""
    local count=0

    required_names="$(_profile_batch_required_secret_names)" || return 1
    all_names="$(_profile_batch_secret_names)" || return 1
    [ -n "$all_names" ] || {
        echo "[INFO] This profile has no manually importable secrets."
        return 1
    }
    {
        echo "# Temporary Docker secret values generated from the selected site profile."
        echo "# Fill required values and any optional values you want to create."
        echo "# Empty optional values are skipped. This temporary file is always deleted."
        echo "# Cleanup also runs after validation/import errors or operator interruption."
        echo "# Keycloak client secrets are transferred only by verified bootstrap/rotation."
        echo ""
        while IFS= read -r secret_name; do
            [ -n "$secret_name" ] || continue
            help_text="$(_profile_secret_value_help "$secret_name")" || return 1
            if printf '%s\n' "$required_names" | grep -Fxq -- "$secret_name"; then
                echo "# Required: ${help_text}"
            else
                echo "# Optional: ${help_text}"
            fi
            echo "${secret_name}="
            echo ""
            count=$((count + 1))
        done <<< "$all_names"
    } > "$destination"
    chmod 600 "$destination"
    [ "$count" -gt 0 ]
}

# validate_profile_secret_values_file
# Validates a saved values file against the active profile before a caller
# stops services or otherwise mutates runtime state.
#
# Arguments:
#   $1 - Existing secret values file.
#
# Returns:
#   0 when every key is safe and allowed; otherwise 1.
validate_profile_secret_values_file() {
    local secrets_file="$1"
    local allowed_keys=""
    local enforce_allowlist="false"

    [ -f "$secrets_file" ] || return 1
    if _profile_secrets_use_exact_names; then
        allowed_keys="$(_profile_batch_secret_names)" || return 1
        enforce_allowlist="true"
    fi
    _validate_secret_env_keys \
        "$secrets_file" \
        "$allowed_keys" \
        "$enforce_allowlist"
}

# create_profile_secrets_from_env_file
# Creates Docker secrets from one saved or editable values file using only the
# selected profile's naming and template policy.
#
# Arguments:
#   $1 - Values file path. A missing file is created from the profile template.
#   $2 - Plaintext cleanup policy. Defaults to `always` for generated
#        temporary files; saved restore inputs explicitly pass `keep`.
#
# Returns:
#   Status from create_secrets_from_env_file.
#
# Side effects:
#   May open an editor and create or replace profile-declared Docker secrets.
create_profile_secrets_from_env_file() {
    local secrets_file="${1:-secrets.env}"
    local deletion_mode="${2:-always}"
    local template_path=""
    local generated_template=""
    local prefix=""
    local allowed_keys=""
    local required_keys=""
    local enforce_allowlist="false"
    local status=0

    if _profile_declares_secret_template; then
        template_path="$(_profile_secrets_template_path)" || return 1
    elif _profile_secrets_use_exact_names; then
        generated_template="$(mktemp)" || return 1
        if ! _write_generated_profile_secrets_template "$generated_template"; then
            rm -f "$generated_template"
            return 1
        fi
        template_path="$generated_template"
    else
        template_path="$(_profile_secrets_template_path)" || return 1
    fi
    if _profile_secrets_use_exact_names; then
        if ! allowed_keys="$(_profile_batch_secret_names)"; then
            [ -z "$generated_template" ] || rm -f "$generated_template"
            return 1
        fi
        if ! required_keys="$(_profile_batch_required_secret_names)"; then
            [ -z "$generated_template" ] || rm -f "$generated_template"
            return 1
        fi
        enforce_allowlist="true"
    else
        prefix="$(_generic_secret_prefix)"
        required_keys="$(_profile_required_secret_names)" || return 1
    fi
    create_secrets_from_env_file \
        "$secrets_file" \
        "$template_path" \
        "$prefix" \
        "$allowed_keys" \
        "$enforce_allowlist" \
        "$deletion_mode" \
        "$required_keys" || status=$?
    if [ -n "$generated_template" ]; then
        rm -f "$generated_template"
    fi
    return "$status"
}
