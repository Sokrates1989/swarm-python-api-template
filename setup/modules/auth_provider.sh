#!/bin/bash
# =============================================================================
# auth_provider.sh - Authentication Provider Selection Module
# =============================================================================
#
# Purpose:
#   Handles selection and configuration of authentication providers.
#   Supports AWS Cognito and Keycloak as authentication backends.
#
# Usage:
#   Source this file and call setup_auth_provider
# =============================================================================

set -e

AUTH_PROVIDER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUTH_PROVIDER_SETUP_DIR="$(cd "${AUTH_PROVIDER_DIR}/.." && pwd)"
AUTH_PROVIDER_PROJECT_ROOT="$(cd "${AUTH_PROVIDER_SETUP_DIR}/.." && pwd)"

_auth_env_file="${AUTH_PROVIDER_PROJECT_ROOT}/.env"

# =============================================================================
# Constants
# =============================================================================

AUTH_PROVIDER_COGNITO="cognito"
AUTH_PROVIDER_KEYCLOAK="keycloak"
AUTH_PROVIDER_DUAL="dual"
AUTH_PROVIDER_NONE="none"

# =============================================================================
# Helper Functions
# =============================================================================

_auth_is_macos() {
    case "$(uname)" in
        Darwin*) return 0 ;;
        *) return 1 ;;
    esac
}

_auth_get_env() {
    local key="$1"
    if [ ! -f "${_auth_env_file}" ]; then
        echo ""
        return
    fi
    grep -E "^${key}=" "${_auth_env_file}" 2>/dev/null | head -n1 | cut -d'=' -f2- || echo ""
}

_auth_update_env() {
    local key="$1"
    local value="$2"
    
    if [ ! -f "${_auth_env_file}" ]; then
        echo "${key}=${value}" > "${_auth_env_file}"
        return
    fi
    
    if grep -qE "^${key}=" "${_auth_env_file}" 2>/dev/null; then
        if _auth_is_macos; then
            sed -i '' "s|^${key}=.*|${key}=${value}|" "${_auth_env_file}"
        else
            sed -i "s|^${key}=.*|${key}=${value}|" "${_auth_env_file}"
        fi
    else
        echo "${key}=${value}" >> "${_auth_env_file}"
    fi
}

# =============================================================================
# Provider Detection
# =============================================================================

get_current_auth_provider() {
    local provider
    provider=$(_auth_get_env "AUTH_PROVIDER")
    
    if [ -z "$provider" ]; then
        # Check for Cognito config as fallback
        local cognito_pool
        cognito_pool=$(_auth_get_env "COGNITO_USER_POOL_ID")
        if [ -n "$cognito_pool" ]; then
            echo "$AUTH_PROVIDER_COGNITO"
            return
        fi
        
        # Check for Keycloak config
        local keycloak_url
        keycloak_url=$(_auth_get_env "KEYCLOAK_SERVER_URL")
        if [ -n "$keycloak_url" ]; then
            echo "$AUTH_PROVIDER_KEYCLOAK"
            return
        fi
        
        echo "$AUTH_PROVIDER_NONE"
    else
        echo "$provider"
    fi
}

is_auth_configured() {
    local provider
    provider=$(get_current_auth_provider)
    [ "$provider" != "$AUTH_PROVIDER_NONE" ]
}

# =============================================================================
# Provider Selection UI
# =============================================================================

prompt_auth_provider() {
    echo ""
    echo "🔐 Authentication Provider Selection"
    echo "====================================="
    echo ""
    echo "Choose your authentication backend:"
    echo ""
    echo "  1) AWS Cognito"
    echo "     - Managed auth service from AWS"
    echo "     - Requires AWS account and Cognito User Pool"
    echo ""
    echo "  2) Keycloak"
    echo "     - Open-source identity management"
    echo "     - Self-hosted or cloud deployment"
    echo ""
    echo "  3) Dual (Keycloak + Cognito fallback)"
    echo "     - Tries Keycloak first, then Cognito"
    echo ""
    echo "  4) None (no authentication)"
    echo "     - Skip authentication setup"
    echo ""
    
    local choice
    read -r -p "Your choice (1-4) [1]: " choice
    choice="${choice:-1}"
    
    case "$choice" in
        1) echo "$AUTH_PROVIDER_COGNITO" ;;
        2) echo "$AUTH_PROVIDER_KEYCLOAK" ;;
        3) echo "$AUTH_PROVIDER_DUAL" ;;
        4) echo "$AUTH_PROVIDER_NONE" ;;
        *) echo "$AUTH_PROVIDER_COGNITO" ;;
    esac
}

# =============================================================================
# Cognito Configuration
# =============================================================================

setup_cognito_auth() {
    echo ""
    echo "☁️  AWS Cognito Configuration"
    echo "-----------------------------"
    echo ""
    echo "You'll need from your AWS Cognito User Pool:"
    echo "  - User Pool ID (e.g., us-east-1_xxxxxxxxx)"
    echo "  - App Client ID"
    echo "  - AWS Region"
    echo ""
    
    local current_region current_pool current_client
    current_region=$(_auth_get_env "AWS_REGION")
    current_pool=$(_auth_get_env "COGNITO_USER_POOL_ID")
    current_client=$(_auth_get_env "COGNITO_APP_CLIENT_ID")
    
    local region pool_id client_id
    
    read -r -p "AWS Region [${current_region:-us-east-1}]: " region
    region="${region:-${current_region:-us-east-1}}"
    
    read -r -p "User Pool ID [${current_pool}]: " pool_id
    pool_id="${pool_id:-$current_pool}"
    while [ -z "$pool_id" ]; do
        echo "❌ User Pool ID is required"
        read -r -p "User Pool ID: " pool_id
    done
    
    read -r -p "App Client ID [${current_client}]: " client_id
    client_id="${client_id:-$current_client}"
    
    # Update .env
    _auth_update_env "AUTH_PROVIDER" "$AUTH_PROVIDER_COGNITO"
    _auth_update_env "AWS_REGION" "$region"
    _auth_update_env "COGNITO_USER_POOL_ID" "$pool_id"
    _auth_update_env "COGNITO_APP_CLIENT_ID" "$client_id"
    
    # Optional: AWS credentials
    echo ""
    echo "AWS credentials (optional - for admin operations):"
    local current_key current_secret
    current_key=$(_auth_get_env "AWS_ACCESS_KEY_ID")
    current_secret=$(_auth_get_env "AWS_SECRET_ACCESS_KEY")
    
    read -r -p "AWS Access Key ID [${current_key:+****}]: " access_key
    if [ -n "$access_key" ]; then
        _auth_update_env "AWS_ACCESS_KEY_ID" "$access_key"
        
        read -r -s -p "AWS Secret Access Key: " secret_key
        echo ""
        if [ -n "$secret_key" ]; then
            _auth_update_env "AWS_SECRET_ACCESS_KEY" "$secret_key"
        fi
    fi
    
    echo ""
    echo "✅ AWS Cognito configured"
    echo "   Region: $region"
    echo "   User Pool: $pool_id"
    echo "   Client ID: ${client_id:0:10}..."
}

# =============================================================================
# Keycloak Configuration
# =============================================================================

setup_keycloak_auth() {
    echo ""
    echo "🔐 Keycloak Configuration"
    echo "-------------------------"
    echo ""
    echo "You'll need from your Keycloak server:"
    echo "  - Server URL (e.g., https://auth.example.com)"
    echo "  - Realm name"
    echo "  - Client ID"
    echo ""
    
    local current_url current_realm current_client current_internal
    current_url=$(_auth_get_env "KEYCLOAK_SERVER_URL")
    current_realm=$(_auth_get_env "KEYCLOAK_REALM")
    current_client=$(_auth_get_env "KEYCLOAK_CLIENT_ID")
    current_internal=$(_auth_get_env "KEYCLOAK_INTERNAL_URL")
    
    local server_url realm client_id internal_url
    
    read -r -p "Keycloak Server URL [${current_url:-http://localhost:9090}]: " server_url
    server_url="${server_url:-${current_url:-http://localhost:9090}}"
    
    read -r -p "Realm name [${current_realm:-my-app}]: " realm
    realm="${realm:-${current_realm:-my-app}}"
    
    local default_client="${realm}-backend"
    read -r -p "Client ID [${current_client:-$default_client}]: " client_id
    client_id="${client_id:-${current_client:-$default_client}}"

    read -r -p "Internal URL (optional) [${current_internal}]: " internal_url
    internal_url="${internal_url:-$current_internal}"
    
    # Update .env
    _auth_update_env "AUTH_PROVIDER" "$AUTH_PROVIDER_KEYCLOAK"
    _auth_update_env "KEYCLOAK_SERVER_URL" "$server_url"
    _auth_update_env "KEYCLOAK_INTERNAL_URL" "$internal_url"
    _auth_update_env "KEYCLOAK_REALM" "$realm"
    _auth_update_env "KEYCLOAK_CLIENT_ID" "$client_id"
    
    # Derive OIDC endpoints
    local issuer_url="${server_url}/realms/${realm}"
    _auth_update_env "KEYCLOAK_ISSUER_URL" "$issuer_url"
    _auth_update_env "KEYCLOAK_JWKS_URL" "${issuer_url}/protocol/openid-connect/certs"
    
    # Optional: Client secret (for confidential clients)
    echo ""
    echo "Client secret (optional - for confidential clients):"
    local current_secret
    current_secret=$(_auth_get_env "KEYCLOAK_CLIENT_SECRET")
    
    read -r -s -p "Client Secret [${current_secret:+****}]: " client_secret
    echo ""
    if [ -n "$client_secret" ]; then
        _auth_update_env "KEYCLOAK_CLIENT_SECRET" "$client_secret"
    fi
    
    echo ""
    echo "✅ Keycloak configured"
    echo "   Server: $server_url"
    if [ -n "$internal_url" ]; then
        echo "   Internal: $internal_url"
    fi
    echo "   Realm: $realm"
    echo "   Client: $client_id"
    echo "   Issuer: $issuer_url"
}

# =============================================================================
# Main Setup Function
# =============================================================================

setup_auth_provider() {
    echo ""
    echo "========================================"
    echo "  Authentication Provider Setup"
    echo "========================================"
    
    # Check existing configuration
    if is_auth_configured; then
        local current
        current=$(get_current_auth_provider)
        echo ""
        echo "Current provider: $current"
        echo ""
        
        read -r -p "Reconfigure authentication? (y/N): " reconfigure
        if [[ ! "$reconfigure" =~ ^[Yy]$ ]]; then
            echo "Keeping current configuration."
            return 0
        fi
    fi
    
    # Select provider
    local provider
    provider=$(prompt_auth_provider)
    
    echo ""
    echo "Selected: $provider"
    
    # Configure based on selection
    case "$provider" in
        "$AUTH_PROVIDER_COGNITO")
            setup_cognito_auth
            ;;
        "$AUTH_PROVIDER_KEYCLOAK")
            setup_keycloak_auth
            ;;
        "$AUTH_PROVIDER_DUAL")
            setup_keycloak_auth
            setup_cognito_auth
            _auth_update_env "AUTH_PROVIDER" "$AUTH_PROVIDER_DUAL"
            ;;
        "$AUTH_PROVIDER_NONE")
            _auth_update_env "AUTH_PROVIDER" "$AUTH_PROVIDER_NONE"
            echo ""
            echo "✅ Authentication disabled"
            ;;
    esac
    
    echo ""
    echo "🎉 Authentication provider setup complete!"
    echo ""
    
    # Show next steps
    if [ "$provider" = "$AUTH_PROVIDER_KEYCLOAK" ]; then
        echo "Next steps for Keycloak:"
        echo "  1. Ensure Keycloak server is running"
        echo "  2. Create realm and client in Keycloak admin"
        echo "  3. Configure social providers (optional)"
        echo "  4. Update CORS settings for your frontend"
    elif [ "$provider" = "$AUTH_PROVIDER_DUAL" ]; then
        echo "Next steps for Dual auth:"
        echo "  1. Ensure Keycloak server is running"
        echo "  2. Verify Cognito pool settings in AWS Console"
        echo "  3. Update CORS settings for your frontend"
    elif [ "$provider" = "$AUTH_PROVIDER_COGNITO" ]; then
        echo "Next steps for Cognito:"
        echo "  1. Verify User Pool settings in AWS Console"
        echo "  2. Configure social identity providers (optional)"
        echo "  3. Set up app client callback URLs"
    fi
    echo ""
}

show_auth_status() {
    local provider
    provider=$(get_current_auth_provider)
    
    echo ""
    echo "🔐 Authentication Status"
    echo "------------------------"
    
    case "$provider" in
        "$AUTH_PROVIDER_COGNITO")
            echo "Provider: AWS Cognito"
            echo "  Region: $(_auth_get_env "AWS_REGION")"
            echo "  Pool: $(_auth_get_env "COGNITO_USER_POOL_ID")"
            ;;
        "$AUTH_PROVIDER_KEYCLOAK")
            echo "Provider: Keycloak"
            echo "  Server: $(_auth_get_env "KEYCLOAK_SERVER_URL")"
            echo "  Realm: $(_auth_get_env "KEYCLOAK_REALM")"
            ;;
        "$AUTH_PROVIDER_DUAL")
            echo "Provider: Dual (Keycloak + Cognito)"
            echo "  Keycloak Server: $(_auth_get_env "KEYCLOAK_SERVER_URL")"
            echo "  Keycloak Realm: $(_auth_get_env "KEYCLOAK_REALM")"
            echo "  Cognito Region: $(_auth_get_env "AWS_REGION")"
            echo "  Cognito Pool: $(_auth_get_env "COGNITO_USER_POOL_ID")"
            ;;
        *)
            echo "Provider: Not configured"
            ;;
    esac
    echo ""
}
