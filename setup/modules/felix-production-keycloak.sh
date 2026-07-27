#!/bin/bash
# ==============================================================================
# felix-production-keycloak.sh - Existing production Keycloak ownership handoff
# ==============================================================================
#
# This module never provisions Keycloak and never reads a client-secret value.
# It directs Felix operators to the already deployed swarm-keycloak checkout,
# which owns realm/client maintenance, social providers, and the future
# secret-safe Docker handoff.
# ==============================================================================

FELIX_PRODUCTION_KEYCLOAK_PATH="/swarm/administration/keycloak"
FELIX_PRODUCTION_KEYCLOAK_REPOSITORY="https://github.com/Sokrates1989/swarm-keycloak.git"
FELIX_PRODUCTION_KEYCLOAK_REALM="felix-new"
FELIX_PRODUCTION_KEYCLOAK_FRONTEND_CLIENT="felix-new-frontend"
FELIX_PRODUCTION_KEYCLOAK_BACKEND_CLIENT="felix-new-backend"
FELIX_PRODUCTION_KEYCLOAK_DOCKER_SECRET="FELIX_NEW_KEYCLOAK_ADMIN_CLIENT_SECRET"

# show_felix_production_keycloak_handoff
# Displays the non-secret ownership boundary for Felix production Keycloak.
#
# Arguments:
#   None.
#
# Returns:
#   0 after printing the operator guidance.
#
# Side effects:
#   Writes public repository, path, realm, client, and Docker-secret names.
#   It never invokes another repository or mutates Keycloak/Docker state.
show_felix_production_keycloak_handoff() {
    echo ""
    echo "Felix production Keycloak ownership"
    echo "------------------------------------"
    echo "  Existing deployment: ${FELIX_PRODUCTION_KEYCLOAK_PATH}"
    echo "  Repository:          ${FELIX_PRODUCTION_KEYCLOAK_REPOSITORY}"
    echo "  Realm:               ${FELIX_PRODUCTION_KEYCLOAK_REALM}"
    echo "  Frontend client:     ${FELIX_PRODUCTION_KEYCLOAK_FRONTEND_CLIENT}"
    echo "  Backend client:      ${FELIX_PRODUCTION_KEYCLOAK_BACKEND_CLIENT}"
    echo "  Felix Docker secret: ${FELIX_PRODUCTION_KEYCLOAK_DOCKER_SECRET}"
    echo ""
    echo "This Felix checkout consumes the existing realm and Docker secret."
    echo "It does not deploy or reconcile Keycloak and never requires /swarm/keycloak."
    echo "Use the quick-start menu in the existing production checkout for realm,"
    echo "social-provider, and client-secret maintenance."
    echo ""
}
