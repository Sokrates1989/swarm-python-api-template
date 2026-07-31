#!/bin/bash
# ==============================================================================
# keycloak-bootstrap.sh - Site-profile-driven Keycloak realm bootstrap
# ==============================================================================
#
# Offers Keycloak reconciliation only when the active site config declares
# auth.provider=keycloak. The site config provides safe defaults, protected
# identity policy, and the fixed credential destination. Validated realm,
# client, audience, and root choices persist in the deployment `.env`.
# ==============================================================================

# _profile_config_file
# Resolves the selected site's JSON profile from loaded setup or root env state.
#
# Arguments:
#   None.
#
# Outputs:
#   Absolute profile path.
#
# Returns:
#   0 when a profile exists; 1 otherwise.
_profile_config_file() {
    local root="${PROJECT_ROOT:-.}"
    local profile_id="${APP_CONFIG_ID:-${DEPLOYMENT_PROFILE_ID:-${BACKEND_APP_ID:-}}}"
    local candidate="${APP_CONFIG_FILE:-}"

    if [ -n "$candidate" ] && [ -f "$candidate" ]; then
        printf '%s\n' "$candidate"
        return 0
    fi
    if [ -n "$profile_id" ] &&
        [ -f "${root}/site-configs/${profile_id}.json" ]; then
        printf '%s\n' "${root}/site-configs/${profile_id}.json"
        return 0
    fi
    return 1
}

# _profile_json_value
# Reads one raw scalar from the selected site profile.
#
# Arguments:
#   $1 - jq expression.
#   $2 - optional fallback.
#
# Outputs:
#   Selected scalar or fallback.
#
# Returns:
#   0 when a profile and jq are available; 1 otherwise.
_profile_json_value() {
    local expression="$1"
    local fallback="${2:-}"
    local profile_file=""
    local value=""

    profile_file="$(_profile_config_file)" || return 1
    if ! command -v jq >/dev/null 2>&1; then
        return 1
    fi
    value=$(jq -r "${expression} // empty" "$profile_file" 2>/dev/null)
    printf '%s\n' "${value:-$fallback}"
}

# _profile_keycloak_active_value
# Reads an active deployment value and otherwise returns its profile default.
#
# Arguments:
#   $1 - Generated root environment key.
#   $2 - jq expression for the profile default.
#
# Outputs:
#   Active or default public value.
#
# Returns:
#   0 after printing a value; 1 when neither source is available.
_profile_keycloak_active_value() {
    local env_key="$1"
    local expression="$2"
    local env_file="${PROJECT_ROOT:-.}/.env"
    local value=""

    if [ -f "$env_file" ]; then
        value="$(_root_env_value "$env_file" "$env_key")"
    fi
    if [ -n "$value" ]; then
        printf '%s\n' "$value"
        return 0
    fi
    _profile_json_value "$expression"
}

# profile_uses_keycloak
# Checks the selected profile's authentication provider.
#
# Arguments:
#   None.
#
# Returns:
#   0 only when auth.provider is keycloak.
profile_uses_keycloak() {
    [ "$(_profile_json_value '.auth.provider' 'none')" = "keycloak" ]
}

# profile_uses_executable_renderer
# Checks whether the selected profile uses the shared executable renderer.
#
# Arguments:
#   None.
#
# Returns:
#   0 only when renderer.type is executable.
profile_uses_executable_renderer() {
    [ "$(_profile_json_value '.renderer.type' 'generic')" = "executable" ]
}

# profile_supports_keycloak_bootstrap
# Checks whether the selected profile declares both Keycloak identity and the
# strict profile contract consumed by the reconciliation adapter.
#
# Arguments:
#   None.
#
# Returns:
#   0 only when the shared bootstrap can execute for the selected profile.
profile_supports_keycloak_bootstrap() {
    profile_uses_keycloak && profile_uses_executable_renderer
}

# _profile_keycloak_python
# Resolves the Python 3 command required by the reconciliation adapter.
#
# Arguments:
#   None.
#
# Outputs:
#   Python command.
#
# Returns:
#   0 when Python is available; 1 otherwise.
_profile_keycloak_python() {
    if command -v python3 >/dev/null 2>&1; then
        printf '%s\n' "python3"
        return 0
    fi
    if command -v python >/dev/null 2>&1; then
        printf '%s\n' "python"
        return 0
    fi
    return 1
}

# _profile_keycloak_secret_name
# Resolves the declared confidential-client Docker secret.
#
# Arguments:
#   None.
#
# Outputs:
#   Exact Docker secret name, or nothing when no unique declaration exists.
#
# Returns:
#   0 when exactly one matching secret mount exists; 1 otherwise.
_profile_keycloak_secret_name() {
    local profile_file=""
    local names=""

    profile_file="$(_profile_config_file)" || return 1
    names=$(jq -r '
        [
          .secretMounts[]?,
          (.capabilities // {} | to_entries[] |
            select(.value.enabled == true) |
            .value.secretMounts[]?)
        ]
        | map(select(
            .envKey == "KEYCLOAK_ADMIN_CLIENT_SECRET_FILE" or
            .envKey == "KEYCLOAK_CLIENT_SECRET_FILE"
          ))
        | map(.name)
        | unique
        | if length == 1 then .[0] else empty end
    ' "$profile_file" 2>/dev/null)
    [ -n "$names" ] || return 1
    printf '%s\n' "$names"
}

# _profile_keycloak_summary
# Prints the public reconciliation target before any credentials are requested.
#
# Arguments:
#   None.
#
# Returns:
#   0 after printing public profile values.
_profile_keycloak_summary() {
    local secret_name=""

    secret_name="$(_profile_keycloak_secret_name 2>/dev/null || true)"
    echo ""
    echo "Keycloak realm bootstrap"
    echo "------------------------"
    echo "  Profile:         $(_profile_json_value '.appId')"
    echo "  Existing server: $(_profile_keycloak_active_value KEYCLOAK_BASE_URL '.auth.serverUrl')"
    echo "  Realm:           $(_profile_keycloak_active_value KEYCLOAK_REALM '.auth.realm')"
    echo "  Frontend client: $(_profile_keycloak_active_value KEYCLOAK_FRONTEND_CLIENT_ID '.auth.frontendClientId')"
    echo "  Backend client:  $(_profile_keycloak_active_value KEYCLOAK_BACKEND_CLIENT_ID '.auth.adminClientId')"
    echo "  Docker secret:   ${secret_name:-not declared}"
    echo ""
    echo "This updates the existing Keycloak deployment through its Admin API."
    echo "It does not deploy another Keycloak instance and does not change social"
    echo "identity providers or unrelated realm settings."
    echo "The guided review accepts active realm, clients, audience, and service"
    echo "roots using the selected deployment values as defaults. Changed values"
    echo "are validated, saved to root .env, and used to rebuild swarm-stack.yml."
    echo "The Keycloak server remains the tracked credential trust anchor."
    echo "WebApp/mobile builds must use the selected realm and client identity."
    echo "After login, a read-only live-state plan is shown before Enter-default"
    echo "approval. Success requires Admin API read-back, issuer/JWKS verification,"
    echo "client-credentials proof, and a capability-derived authorization check"
    echo "before a missing Docker secret is created."
    echo "No test user or example role is created. The client-secret value is"
    echo "never displayed or stored in a file."
    echo "Optional debug tracing prints only HTTP methods, Admin API paths,"
    echo "query-key names, and status codes; credentials and payloads stay hidden."
}

# _profile_keycloak_reconcile
# Invokes the Python adapter for one profile-driven reconciliation.
#
# Arguments:
#   $1 - Python command.
#   $2 - optional literal --replace-secret.
#
# Returns:
#   Python adapter status.
#
# Side effects:
#   May persist validated public deployment values, rebuild the generated
#   stack, create/update the selected realm and clients, and create or replace
#   the declared Docker secret. It never prints the secret value.
_profile_keycloak_reconcile() {
    local python_command="$1"
    local replace_flag="${2:-}"
    local arguments=(
        "${PROJECT_ROOT}/scripts/keycloak_profile_bootstrap.py"
        --root "$PROJECT_ROOT"
    )
    local status=0

    if [ "$replace_flag" = "--replace-secret" ]; then
        arguments+=(--replace-secret)
        arguments+=(--accept-profile-values)
    fi
    "$python_command" "${arguments[@]}"
    status=$?
    if [ -f "${PROJECT_ROOT}/.env" ]; then
        load_root_env "$PROJECT_ROOT" || true
    fi
    return "$status"
}

# run_profile_keycloak_bootstrap
# Runs the shared realm/client reconciliation for the selected Keycloak profile.
#
# Arguments:
#   None.
#
# Returns:
#   0 after successful reconciliation or explicit cancellation; 1 on
#   validation or API failure.
#
# Side effects:
#   Persists entered public deployment identity, authenticates, shows a
#   read-only plan, and mutates only profile-policy-authorized Keycloak state
#   and the declared missing Docker client secret after confirmation.
run_profile_keycloak_bootstrap() {
    local python_command=""

    if ! profile_supports_keycloak_bootstrap; then
        echo "[INFO] The selected profile does not declare supported Keycloak bootstrap."
        return 1
    fi
    python_command="$(_profile_keycloak_python)" || {
        echo "[ERROR] Python 3 is required for Keycloak bootstrap."
        return 1
    }
    _profile_keycloak_summary
    _profile_keycloak_reconcile "$python_command"
}

# run_profile_keycloak_secret_rotation
# Reconciles clients and deliberately replaces the declared Docker secret.
#
# Arguments:
#   None.
#
# Returns:
#   0 after success; 1 when the stack is running, confirmation is declined, or
#   reconciliation fails.
#
# Side effects:
#   Replaces the declared Docker client secret. The Python adapter refuses this
#   action while the selected stack is running.
run_profile_keycloak_secret_rotation() {
    local python_command=""
    local confirmation=""

    if ! profile_supports_keycloak_bootstrap; then
        echo "[ERROR] The selected profile has no executable Keycloak contract."
        return 1
    fi
    python_command="$(_profile_keycloak_python)" || {
        echo "[ERROR] Python 3 is required for Keycloak secret rotation."
        return 1
    }
    _profile_keycloak_summary
    echo "[WARN] This replaces the Docker secret and requires the stack to be stopped."
    read -r -p "Type 'rotate' to continue: " confirmation
    if [ "$confirmation" != "rotate" ]; then
        echo "Keycloak secret rotation cancelled."
        return 1
    fi
    _profile_keycloak_reconcile \
        "$python_command" \
        "--replace-secret"
}
