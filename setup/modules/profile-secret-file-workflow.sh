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
# Checks whether saved/template-based batch entry is valid for this profile.
#
# Returns:
#   0 for prefixed profiles or exact-name profiles with an explicit template;
#   otherwise 1.
profile_supports_secret_file_workflow() {
    if _profile_secrets_use_exact_names; then
        _profile_declares_secret_template
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
#
# Returns:
#   Status from create_secrets_from_env_file.
#
# Side effects:
#   May open an editor and create or replace profile-declared Docker secrets.
create_profile_secrets_from_env_file() {
    local secrets_file="${1:-secrets.env}"
    local template_path=""
    local prefix=""
    local allowed_keys=""
    local enforce_allowlist="false"

    template_path="$(_profile_secrets_template_path)" || return 1
    if _profile_secrets_use_exact_names; then
        allowed_keys="$(_profile_batch_secret_names)" || return 1
        enforce_allowlist="true"
    else
        prefix="$(_generic_secret_prefix)"
    fi
    create_secrets_from_env_file \
        "$secrets_file" \
        "$template_path" \
        "$prefix" \
        "$allowed_keys" \
        "$enforce_allowlist"
}
