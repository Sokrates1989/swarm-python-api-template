#!/bin/bash
#
# quick-start.sh
#
# Quick start tool for Swarm Python API Template:
# 1. Checks Docker installation
# 2. Runs interactive setup if needed
# 3. Provides deployment and management options

set -e

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source modules
source "${SCRIPT_DIR}/setup/modules/secret-manager.sh"
source "${SCRIPT_DIR}/setup/modules/health-check.sh"
source "${SCRIPT_DIR}/setup/modules/stack-conflict-check.sh"
source "${SCRIPT_DIR}/setup/modules/deploy-stack.sh"
source "${SCRIPT_DIR}/setup/modules/config-builder.sh"
source "${SCRIPT_DIR}/setup/modules/ci-cd-github.sh"
source "${SCRIPT_DIR}/setup/modules/menu_handlers.sh"

# Source Cognito setup script if available
cognito_script="${SCRIPT_DIR}/setup/modules/cognito_setup.sh"
if [ -f "$cognito_script" ]; then
    # shellcheck disable=SC1091
    source "$cognito_script"
fi

echo "🚀 Swarm Python API Template - Quick Start"
echo "==========================================="
echo ""

# Docker availability check
echo "🔍 Checking Docker installation..."
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed!"
    echo "📥 Please install Docker from: https://www.docker.com/get-started"
    exit 1
fi

# Docker daemon check
if ! docker info &> /dev/null; then
    echo "❌ Docker daemon is not running!"
    echo "🔄 Please start Docker Desktop or the Docker service"
    exit 1
fi

# Docker Compose check
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "❌ Docker Compose is not available!"
    echo "📥 Please install Docker Compose v1 (docker-compose) or a current Docker version with the Compose plugin"
    exit 1
fi

echo "✅ Docker is installed and running"
echo ""

# Check if initial setup is needed (same logic as setup wizard)
SETUP_DONE=false
if [ -f .setup-complete ]; then
    SETUP_DONE=true
elif [ -f .env ] && [ -f swarm-stack.yml ]; then
    SETUP_DONE=true
fi

if [ "$SETUP_DONE" = false ]; then
    echo "🚀 First-time setup detected!"
    echo ""
    echo "This appears to be your first time setting up this deployment."
    echo "Would you like to run the interactive setup wizard?"
    echo ""
    echo "The setup wizard will help you configure:"
    echo "  - Database type (PostgreSQL or Neo4j)"
    echo "  - Proxy type (Traefik or no-proxy)"
    echo "  - Database mode (local or external)"
    echo "  - Docker image and version"
    echo "  - Domain/port configuration"
    echo "  - Swarm stack settings"
    echo ""
    
    read -p "Run setup wizard now? (Y/n): " runSetup
    if [[ ! "$runSetup" =~ ^[Nn]$ ]]; then
        echo ""
        echo "Starting setup wizard..."
        ./setup/setup-wizard.sh
        echo ""
    else
        echo ""
        echo "⚠️  Setup wizard skipped."
        echo "You'll need to manually configure .env and swarm-stack.yml"
        echo "See README.md for manual setup instructions."
        echo ""
        exit 0
    fi
    echo ""
fi

# Check if configuration files exist
if [ ! -f .env ]; then
    echo "❌ .env file not found!"
    echo "Please run the setup wizard or create .env manually."
    exit 1
fi

if [ ! -f swarm-stack.yml ]; then
    echo "❌ swarm-stack.yml not found!"
    echo "Please run the setup wizard or create swarm-stack.yml manually."
    exit 1
fi

# Read configuration from .env
STACK_NAME=$(grep "^STACK_NAME=" .env 2>/dev/null | cut -d'=' -f2 | tr -d ' "' || echo "api_production")
API_URL=$(grep "^API_URL=" .env 2>/dev/null | cut -d'=' -f2 | tr -d ' "' || echo "api.example.com")
DB_TYPE=$(grep "^DB_TYPE=" .env 2>/dev/null | cut -d'=' -f2 | tr -d ' "' || echo "postgresql")
PROXY_TYPE=$(grep "^PROXY_TYPE=" .env 2>/dev/null | cut -d'=' -f2 | tr -d ' "' || echo "none")
IMAGE_NAME=$(grep "^IMAGE_NAME=" .env 2>/dev/null | cut -d'=' -f2 | tr -d ' "' || echo "")
IMAGE_VERSION=$(grep "^IMAGE_VERSION=" .env 2>/dev/null | cut -d'=' -f2 | tr -d ' "' || echo "")

echo "📋 Current Configuration"
echo "========================"
echo "Stack Name:     $STACK_NAME"
echo "API Domain:     $API_URL"
echo "Database Type:  $DB_TYPE"
echo "Docker Image:   $IMAGE_NAME:$IMAGE_VERSION"
echo ""

# Main menu
show_main_menu
