#!/bin/bash
# ==============================================================================
# setup-wizard.sh - Shared site-config-driven deployment setup
# ==============================================================================
#
# Selects one deployment profile, collects normalized operator choices through
# one numbered dialogue, then delegates only persistence and rendering to the
# profile-declared adapter. Schema and renderer type never select a different
# user experience.
#
# Flow:
#   1. Select a site-config deployment profile.
#   2. Collect stack, routing, database, service, and resource choices once.
#   3. Persist through the legacy compatibility or executable adapter.
#   4. Render the stack through the selected adapter.
#   5. Offer one capability-driven final-action menu.
#
# Dependencies:
#   - jq and Docker
#   - Python 3 for executable schema-5 profiles
#   - setup/modules sourced below
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

#
# Shared discovery, dialogue, persistence, rendering, and action modules.
# Capability-specific modules remain adapters and never own the setup dialogue.
#
source "$SCRIPT_DIR/modules/site_helpers.sh"
source "$SCRIPT_DIR/modules/user-prompts.sh"
source "$SCRIPT_DIR/modules/deployment-profile-prompts.sh"
source "$SCRIPT_DIR/modules/deployment-profile-routing.sh"
source "$SCRIPT_DIR/modules/deployment-profile-services.sh"
source "$SCRIPT_DIR/modules/deployment-profile-inputs.sh"
source "$SCRIPT_DIR/modules/legacy-profile-environment.sh"
source "$SCRIPT_DIR/modules/executable-profile-wizard.sh"
source "$SCRIPT_DIR/modules/config-builder.sh"
source "$SCRIPT_DIR/modules/network-check.sh"
source "$SCRIPT_DIR/modules/data-dirs.sh"
source "$SCRIPT_DIR/modules/secret-manager.sh"
source "$SCRIPT_DIR/modules/secrets_template_sync.sh"
source "$SCRIPT_DIR/modules/stack-conflict-check.sh"
source "$SCRIPT_DIR/modules/deploy-stack.sh"
source "$SCRIPT_DIR/modules/health-check.sh"
source "$SCRIPT_DIR/modules/keycloak-bootstrap.sh"
source "$SCRIPT_DIR/modules/docker-secrets-menu.sh"
source "$SCRIPT_DIR/modules/deployment-setup-actions.sh"

# Cognito remains an optional provider adapter for profiles that declare it.
if [ -f "${SCRIPT_DIR}/modules/cognito_setup.sh" ]; then
    # shellcheck disable=SC1091
    source "${SCRIPT_DIR}/modules/cognito_setup.sh"
fi

# ------------------------------------------------------------------------------
# select_setup_mode
# ------------------------------------------------------------------------------
# Chooses guided questions, a generated public values file, or fast reuse of an
# existing environment after the deployment profile is known.
#
# Returns:
#   0 after setting SETUP_MODE.
# ------------------------------------------------------------------------------
select_setup_mode() {
    SETUP_MODE="interactive"
    echo ""
    if [ -f "${PROJECT_ROOT}/.env" ]; then
        echo "Existing .env file detected."
        prompt_deployment_choice \
            SETUP_MODE \
            "Configuration method" \
            "from_env" \
            "from_env|Use existing .env values unchanged (fast re-setup)" \
            "interactive|Guided setup questions" \
            "file|Edit a regenerated, commented .env using current values"
    else
        prompt_deployment_choice \
            SETUP_MODE \
            "Configuration method" \
            "interactive" \
            "interactive|Guided setup questions (recommended)" \
            "file|Edit a generated, commented .env file"
    fi
    case "$SETUP_MODE" in
        from_env) echo "Using existing .env values unchanged." ;;
        interactive) echo "Guided setup selected." ;;
        file) echo "File-based public configuration selected." ;;
    esac
    echo ""
}

# ------------------------------------------------------------------------------
# edit_generated_deployment_environment
# ------------------------------------------------------------------------------
# Opens the generated public environment and verifies that its selected profile
# identity was not changed. Runtime rendering performs complete value checks.
#
# Returns:
#   0 after a non-empty matching file is saved; otherwise 1.
# ------------------------------------------------------------------------------
edit_generated_deployment_environment() {
    local environment_file="${PROJECT_ROOT}/.env"
    local selected_profile=""

    choose_editor || {
        echo "[ERROR] Install nano, vim, or vi for file-based setup."
        return 1
    }
    echo ""
    echo "Edit public deployment values in: ${environment_file}"
    echo "Comments describe accepted values and profile-owned fields."
    echo "Do not add passwords, tokens, private keys, or client secrets."
    echo "Save and close ${SELECTED_EDITOR}; the same renderer validation used"
    echo "by guided setup runs before the final action menu is shown."
    echo ""
    read -r -p "Press Enter to open ${environment_file} in ${SELECTED_EDITOR}..." _
    "$SELECTED_EDITOR" "$environment_file"
    chmod 600 "$environment_file"
    if [ ! -s "$environment_file" ]; then
        echo "[ERROR] Public deployment environment is empty."
        return 1
    fi
    selected_profile="$(_root_env_value "$environment_file" DEPLOYMENT_PROFILE_ID)"
    if [ "$selected_profile" != "$APP_CONFIG_ID" ]; then
        echo "[ERROR] DEPLOYMENT_PROFILE_ID must remain '${APP_CONFIG_ID}'."
        return 1
    fi
    echo "[OK] Saved public deployment values: ${environment_file}"
}

# ------------------------------------------------------------------------------
# write_selected_profile_environment
# ------------------------------------------------------------------------------
# Persists normalized answers through the selected renderer's writer adapter.
#
# Returns:
#   Adapter status.
#
# Side effects:
#   Replaces root .env during guided or file-based setup and may open an editor.
# ------------------------------------------------------------------------------
write_selected_profile_environment() {
    if [ "${SETUP_MODE:-interactive}" = "from_env" ]; then
        echo "Existing public deployment environment retained."
        return 0
    fi

    echo ""
    echo "Validating and writing public deployment configuration..."
    if [ "${APP_RENDERER_TYPE:-generic}" = "executable" ]; then
        write_executable_profile_environment || return 1
    else
        write_legacy_profile_environment || return 1
    fi
    annotate_deployment_environment_file "${PROJECT_ROOT}/.env" || return 1
    if [ "${SETUP_MODE:-interactive}" = "file" ]; then
        edit_generated_deployment_environment
    fi
}

# ------------------------------------------------------------------------------
# render_selected_profile_stack
# ------------------------------------------------------------------------------
# Renders the selected profile after input collection and environment writing.
#
# Returns:
#   Renderer status.
#
# Side effects:
#   Replaces root swarm-stack.yml after successful validation.
# ------------------------------------------------------------------------------
render_selected_profile_stack() {
    echo ""
    echo "Building swarm-stack.yml..."
    if [ "${APP_RENDERER_TYPE:-generic}" = "executable" ]; then
        render_executable_profile_stack
        return $?
    fi
    bash "${PROJECT_ROOT}/scripts/build-site-stack.sh"
}

# ------------------------------------------------------------------------------
# run_setup_wizard
# ------------------------------------------------------------------------------
# Coordinates one complete profile-independent setup session.
#
# Returns:
#   0 after configuration and the selected final action; otherwise nonzero.
# ------------------------------------------------------------------------------
run_setup_wizard() {
    local selected_config=""

    if ! command -v jq >/dev/null 2>&1; then
        echo "jq is required but not installed."
        echo "Install it with: sudo apt-get install jq"
        return 1
    fi

    echo ""
    echo "Swarm Python API Template - Setup Wizard"
    echo "============================================="
    echo ""
    echo "This wizard configures this deployment instance."
    echo "Each clone of this repo IS one deployed app stack."
    echo ""
    echo "   .env and swarm-stack.yml are generated at the project root."
    echo "site-configs/ holds deployment profiles describing what this deployment needs."
    echo ""

    echo "Step 1: Select the deployment profile for this instance."
    echo ""
    selected_config="$(show_app_selector "$PROJECT_ROOT")"
    if [ "$selected_config" = "EXIT" ] || [ -z "$selected_config" ]; then
        echo "No deployment profile selected. Exiting."
        return 0
    fi

    load_app_config "$PROJECT_ROOT" "$selected_config"
    initialize_deployment_profile_context
    show_selected_deployment_profile
    select_setup_mode
    collect_deployment_configuration
    write_selected_profile_environment
    render_selected_profile_stack
    load_root_env "$PROJECT_ROOT"
    run_deployment_setup_actions

    echo ""
    echo "Setup wizard complete!"
    echo ""
}

run_setup_wizard
