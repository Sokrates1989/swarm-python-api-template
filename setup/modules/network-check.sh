#!/bin/bash
# ==============================================================================
# network-check.sh - DNS and network verification module
# ==============================================================================
#
# This module verifies that the API domain resolves correctly before
# deployment. It uses nslookup, dig, or host (whichever is available) to
# resolve the domain and asks the user to confirm the IP is correct.
#
# Functions:
#   network_verify - Verify DNS resolution for the API domain
#
# Dependencies:
#   - nslookup, dig, or host (at least one required for DNS lookup)
#
# ==============================================================================

# ------------------------------------------------------------------------------
# network_verify
# ------------------------------------------------------------------------------
# Resolves the API domain and asks the user to confirm the IP address. Only
# runs verification when using Traefik (not needed for direct port exposure).
#
# Arguments:
#   $1 - api_url: the API domain to verify
#   $2 - proxy_type: "traefik" or "none"
#
# Returns:
#   0 if verified or skipped, 1 if user aborts due to DNS issues
# ------------------------------------------------------------------------------
network_verify() {
    local api_url="$1"
    local proxy_type="$2"
    
    if [ "$proxy_type" = "traefik" ]; then
        echo "🌐 Network Verification"
        echo "======================"
        echo ""
        echo "Checking DNS resolution for: $api_url"
        echo ""
        
        # Try to resolve the domain
        if command -v nslookup &> /dev/null; then
            RESOLVED_IP=$(nslookup "$api_url" 2>/dev/null | grep -A1 "Name:" | grep "Address:" | awk '{print $2}' | head -1)
            if [ -z "$RESOLVED_IP" ]; then
                RESOLVED_IP=$(nslookup "$api_url" 2>/dev/null | grep "Address:" | grep -v "#" | awk '{print $2}' | head -1)
            fi
        elif command -v dig &> /dev/null; then
            RESOLVED_IP=$(dig +short "$api_url" | head -1)
        elif command -v host &> /dev/null; then
            RESOLVED_IP=$(host "$api_url" | grep "has address" | awk '{print $4}' | head -1)
        else
            echo "⚠️  No DNS lookup tool found (nslookup, dig, or host)"
            RESOLVED_IP="Unable to resolve"
        fi
        
        if [ -n "$RESOLVED_IP" ] && [ "$RESOLVED_IP" != "Unable to resolve" ]; then
            echo "✅ Domain resolves to: $RESOLVED_IP"
            echo ""
            read -p "Is this the correct IP for your swarm manager? (Y/n): " CONFIRM_IP
            if [[ "$CONFIRM_IP" =~ ^[Nn]$ ]]; then
                echo ""
                echo "❌ DNS not configured correctly. Please update your DNS records:"
                echo "   Domain: $api_url"
                echo "   Should point to: <your-swarm-manager-ip>"
                echo ""
                echo "After updating DNS, wait for propagation (can take up to 48 hours)"
                echo "and re-run the setup wizard."
                return 1
            fi
        else
            echo "⚠️  Unable to resolve domain: $api_url"
            echo ""
            echo "Please ensure:"
            echo "  1. Domain is registered"
            echo "  2. DNS A record points to your swarm manager IP"
            echo "  3. DNS has propagated (can take up to 48 hours)"
            echo ""
            read -p "Continue anyway? (y/N): " CONTINUE_ANYWAY
            if [[ ! "$CONTINUE_ANYWAY" =~ ^[Yy]$ ]]; then
                return 1
            fi
        fi
        echo ""
    fi
    
    return 0
}
