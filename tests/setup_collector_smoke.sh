#!/bin/bash
# ==============================================================================
# setup_collector_smoke.sh - Interactive shared-collector smoke harness
# ==============================================================================
#
# Sources the real setup modules for one profile, runs only the shared input
# collector, and prints normalized public values. It intentionally stops before
# environment writing, stack rendering, secret mutation, or deployment.
#
# Usage:
#   bash tests/setup_collector_smoke.sh <repository-root> <profile-id> [render]
# ==============================================================================

set -e

PROJECT_ROOT="$1"
APP_CONFIG_ID="$2"
SMOKE_ACTION="${3:-collect}"
SCRIPT_DIR="${PROJECT_ROOT}/setup"

#
# The harness mirrors setup-wizard source order so missing dependencies fail in
# the same place without invoking any renderer or external mutation.
#
source "${SCRIPT_DIR}/modules/site_helpers.sh"
source "${SCRIPT_DIR}/modules/user-prompts.sh"
source "${SCRIPT_DIR}/modules/deployment-profile-prompts.sh"
source "${SCRIPT_DIR}/modules/deployment-profile-routing.sh"
source "${SCRIPT_DIR}/modules/deployment-profile-services.sh"
source "${SCRIPT_DIR}/modules/deployment-profile-inputs.sh"
source "${SCRIPT_DIR}/modules/legacy-profile-environment.sh"
source "${SCRIPT_DIR}/modules/executable-profile-wizard.sh"

load_app_config "$PROJECT_ROOT" "$APP_CONFIG_ID"
initialize_deployment_profile_context
show_selected_deployment_profile
SETUP_MODE="interactive"
collect_deployment_configuration

if [ "$SMOKE_ACTION" = "render" ]; then
    if [ "${APP_RENDERER_TYPE:-generic}" = "executable" ]; then
        write_executable_profile_environment
        python3 "${PROJECT_ROOT}/scripts/site_profile.py" \
            --root "$PROJECT_ROOT" \
            render
    else
        write_legacy_profile_environment
        bash "${PROJECT_ROOT}/scripts/build-site-stack.sh"
    fi
fi

printf '%s\n' \
    "RESULT profile=${APP_CONFIG_ID}" \
    "RESULT stack=${STACK_NAME}" \
    "RESULT api_domain=${DOMAIN}" \
    "RESULT web_domain=${WEB_DOMAIN}" \
    "RESULT database=${DB_TYPE}/${DB_MODE}" \
    "RESULT proxy=${PROXY_TYPE}/${SSL_MODE}" \
    "RESULT traefik=${TRAEFIK_NETWORK}/${TRAEFIK_CONSTRAINT_LABEL}" \
    "RESULT api_image=${IMAGE_NAME}:${IMAGE_VERSION}" \
    "RESULT web_image=${WEB_IMAGE_NAME}:${WEB_IMAGE_VERSION}" \
    "RESULT replicas=${API_REPLICAS}/${WEB_REPLICAS}" \
    "RESULT data_root=${DATA_ROOT}" \
    "RESULT pgadmin=${PGADMIN_ENABLED}"
