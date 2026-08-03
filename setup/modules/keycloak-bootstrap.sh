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

# profile_has_pending_bootstrap_user_cleanup
# Checks operator-tracked cleanup state for users this bootstrap created.
#
# Returns:
#   0 only when both a pending marker and at least one username are present.
profile_has_pending_bootstrap_user_cleanup() {
    [ "${KEYCLOAK_BOOTSTRAP_USERS_CLEANUP_PENDING:-}" = "true" ] &&
        [ -n "${KEYCLOAK_BOOTSTRAP_USERS_CLEANUP_NAMES:-}" ]
}

# acknowledge_profile_bootstrap_user_cleanup
# Records that the operator manually removed tracked temporary users.
#
# Returns:
#   0 after acknowledgement or cancellation; 1 on persistence failure.
#
# Side effects:
#   Updates only public reminder fields in root .env. It never authenticates to
#   Keycloak and never queries, changes, or deletes a live account.
acknowledge_profile_bootstrap_user_cleanup() {
    local python_command=""
    local answer=""
    local usernames="${KEYCLOAK_BOOTSTRAP_USERS_CLEANUP_NAMES:-}"

    if ! profile_has_pending_bootstrap_user_cleanup; then
        echo "[INFO] No bootstrap-created temporary-user cleanup is pending."
        return 0
    fi
    echo ""
    echo "Acknowledge manual Keycloak user cleanup"
    echo "========================================"
    echo ""
    echo "Tracked users created by the bootstrap:"
    printf '%s\n' "$usernames" | tr ',' '\n' | sed 's/^/  - /'
    echo ""
    echo "This action only clears the local reminder after you have manually"
    echo "deleted those exact temporary accounts in Keycloak Admin UI."
    echo "It performs no Keycloak request and never deletes a user."
    echo ""
    if [[ -r /dev/tty ]]; then
        read -r -p "Have you manually deleted every listed user? [Y/n]: " \
            answer < /dev/tty
    else
        read -r -p "Have you manually deleted every listed user? [Y/n]: " \
            answer
    fi
    if [[ "${answer:-y}" =~ ^[Yy]([Ee][Ss])?$ ]]; then
        python_command="$(_profile_keycloak_python)" || {
            echo "[ERROR] Python 3 is required to save the acknowledgement."
            return 1
        }
        "$python_command" \
            "${PROJECT_ROOT}/scripts/keycloak_profile_cleanup.py" \
            --root "$PROJECT_ROOT" \
            acknowledge || return 1
        load_root_env "$PROJECT_ROOT" || return 1
        return 0
    fi
    echo "[INFO] Cleanup reminder retained."
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
# Prints a concise, non-interactive explanation before credential verification.
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
    echo "========================"
    echo ""
    echo "Target"
    echo "  Profile:          $(_profile_json_value '.appId')"
    echo "  Existing server:  $(_profile_keycloak_active_value KEYCLOAK_BASE_URL '.auth.serverUrl')"
    echo "  Current realm:    $(_profile_keycloak_active_value KEYCLOAK_REALM '.auth.realm')"
    echo "  Docker secret:    ${secret_name:-not declared}"
    echo ""
    echo "Authentication first"
    echo "  The existing server is the fixed credential trust anchor."
    echo "  The next prompts request and verify a Keycloak administrator username"
    echo "  and password. No realm configuration question appears before a real"
    echo "  Admin API login succeeds. Enter q at the username prompt to skip this"
    echo "  bootstrap and return later."
    echo ""
    echo "What the guided bootstrap manages"
    echo "  - realm identity and managed realm settings"
    echo "  - installed themes and theme-supported locales"
    echo "  - optional realm email sender configuration"
    echo "  - frontend/backend clients, audience, roles, and selected users"
    echo "  - the missing or explicitly rotated backend-client Docker secret"
    echo ""
    echo "Safety boundaries"
    echo "  - it updates this existing server; it never deploys Keycloak"
    echo "  - unrelated realms, clients, and social providers stay unchanged"
    echo "  - no user is deleted or treated as disposable by this tool"
    echo "  - only users actually created here receive a cleanup reminder"
    echo "  - passwords and client secrets never enter .env, JSON, plans, or logs"
    echo "  - a sanitized live-state plan is shown before any mutation"
    echo "  - successful apply requires Admin API and public OIDC verification"
    echo ""
    echo "Public choices are saved to root .env and rebuild swarm-stack.yml."
    echo "WebApp/mobile builds must use the selected"
    echo "realm and client identity. A new secret may optionally be viewed through"
    echo "a private self-deleting temporary editor file after it is safely stored."
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
#   and the declared missing Docker client secret after confirmation. A newly
#   stored value may be opened in an opt-in self-deleting recovery view.
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
    _profile_keycloak_reconcile \
        "$python_command" \
        "--replace-secret"
}
