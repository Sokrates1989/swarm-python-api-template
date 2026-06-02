#!/bin/bash
#
# quick-start.sh
#
# Main entry point for Swarm Python API Template deployment management.
#
# In this model, each git clone of this repo IS one deployment instance.
# The .env, swarm-stack.yml, and data directories live at PROJECT ROOT.
#
# Flow:
#   1. Validate Docker and jq prerequisites.
#   2. Check if root .env exists (i.e. setup has been run).
#   3. If not, offer to run the setup wizard.
#   4. Load root .env and show deployment overview.
#   5. Open the operations menu.

set -e

# Get script directory (repository root)
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ===========================================================================
# Source modules
# ===========================================================================

source "${PROJECT_ROOT}/setup/modules/site_helpers.sh"
source "${PROJECT_ROOT}/setup/modules/secret-manager.sh"
source "${PROJECT_ROOT}/setup/modules/health-check.sh"
source "${PROJECT_ROOT}/setup/modules/stack-conflict-check.sh"
source "${PROJECT_ROOT}/setup/modules/deploy-stack.sh"
source "${PROJECT_ROOT}/setup/modules/config-builder.sh"
source "${PROJECT_ROOT}/setup/modules/ci-cd-github.sh"
source "${PROJECT_ROOT}/setup/modules/menu_handlers.sh"

# Source Cognito setup script if available
cognito_script="${PROJECT_ROOT}/setup/modules/cognito_setup.sh"
if [ -f "$cognito_script" ]; then
    # shellcheck disable=SC1091
    source "$cognito_script"
fi

echo "🚀 Swarm Python API Template - Quick Start"
echo "==========================================="
echo ""

# ===========================================================================
# Docker prerequisite checks
# ===========================================================================

echo "🔍 Checking Docker installation..."
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed!"
    echo "📥 Please install Docker from: https://www.docker.com/get-started"
    exit 1
fi

if ! docker info &> /dev/null; then
    echo "❌ Docker daemon is not running!"
    echo "🔄 Please start Docker Desktop or the Docker service"
    exit 1
fi

if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "❌ Docker Compose is not available!"
    echo "📥 Please install Docker Compose v1 (docker-compose) or a current Docker version with the Compose plugin"
    exit 1
fi

echo "✅ Docker is installed and running"
echo ""

# ===========================================================================
# jq dependency check
# ===========================================================================

if ! command -v jq &> /dev/null; then
    echo "❌ jq is not installed!"
    echo "📥 Install it with:  sudo apt-get install jq  (Debian/Ubuntu)"
    echo "   or:               sudo yum install jq      (RHEL/CentOS)"
    echo "   or:               brew install jq           (macOS)"
    exit 1
fi

# ===========================================================================
# Check for existing deployment (.env at root)
# ===========================================================================

if [ ! -f "${PROJECT_ROOT}/.env" ]; then
    echo "ℹ️  No .env found — this deployment has not been configured yet."
    echo ""

    while true; do
        echo "  1) Run setup wizard"
        echo "  2) Exit"
        echo ""
        read -r -p "Your choice [1]: " INIT_CHOICE
        INIT_CHOICE="${INIT_CHOICE:-1}"

        case "$INIT_CHOICE" in
            1)
                "${PROJECT_ROOT}/setup/setup-wizard.sh"
                echo ""
                # Re-check after wizard
                if [ ! -f "${PROJECT_ROOT}/.env" ]; then
                    echo "⚠️  Setup wizard did not create .env."
                    echo ""
                    # Loop back to menu instead of exiting
                else
                    break
                fi
                ;;
            2)
                echo "👋 Goodbye!"
                exit 0
                ;;
            *)
                echo "❌ Invalid choice: '$INIT_CHOICE'. Please enter 1 or 2."
                echo ""
                ;;
        esac
    done
fi

# ===========================================================================
# Load root .env
# ===========================================================================

load_root_env "$PROJECT_ROOT"

# ===========================================================================
# Show deployment overview and open the operations menu
# ===========================================================================

echo ""
echo "📋 Deployment Overview"
echo "========================"
echo "Stack Name:     ${STACK_NAME:-not set}"
echo "Profile:        ${DEPLOYMENT_PROFILE_ID:-${BACKEND_APP_ID:-not set}}"
echo "Domain:         ${DOMAIN:-not set}"
echo "Database:       ${DB_TYPE:-not set} (${DB_MODE:-not set})"
echo "Proxy:          ${PROXY_TYPE:-not set}"
echo "Image:          ${IMAGE_NAME:-not set}:${IMAGE_VERSION:-latest}"
echo ""

# Main menu
show_main_menu
