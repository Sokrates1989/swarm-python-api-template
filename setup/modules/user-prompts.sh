#!/bin/bash
# ==============================================================================
# user-prompts.sh - Interactive user input collection module
# ==============================================================================
#
# This module provides functions for gathering user input during the setup
# wizard. Each prompt function handles a specific configuration aspect and
# returns the user's selection via stdout.
#
# Functions:
#   prompt_database_type   - Ask for PostgreSQL or Neo4j
#   prompt_proxy_type      - Ask for Traefik or no proxy
#   prompt_ssl_mode        - Ask for direct or proxy SSL termination
#   prompt_database_mode   - Ask for local or external database
#   prompt_stack_name      - Ask for Docker stack name
#   prompt_data_root       - Ask for data directory path
#   prompt_traefik_network - Select or create Traefik overlay network
#   prompt_api_domain      - Ask for API domain (required for Traefik)
#   prompt_published_port  - Ask for port when not using Traefik
#   prompt_docker_image    - Ask for image name/version and verify pull
#   prompt_replicas        - Ask for service replica count
#   prompt_secret_names    - Ask for Docker secret names
#   prompt_yes_no          - Generic yes/no prompt helper
#
# Dependencies:
#   - Docker (for network listing, image pull verification)
#
# ==============================================================================

# ------------------------------------------------------------------------------
# prompt_database_type
# ------------------------------------------------------------------------------
# Prompts the user to choose between PostgreSQL and Neo4j.
#
# Returns (stdout):
#   "postgresql" or "neo4j"
# ------------------------------------------------------------------------------
prompt_database_type() {
    echo "🗄️  Database Configuration" >&2
    echo "-------------------------" >&2
    echo "1) PostgreSQL (relational data)" >&2
    echo "2) Neo4j (graph data)" >&2
    echo "" >&2
    read -p "Your choice (1-2) [1]: " DB_CHOICE
    DB_CHOICE="${DB_CHOICE:-1}"
    
    case $DB_CHOICE in
        1) echo "postgresql" ;;
        2) echo "neo4j" ;;
        *) echo "postgresql" ;;
    esac
}

prompt_proxy_type() {
    echo "🌐 Proxy Configuration" >&2
    echo "---------------------" >&2
    echo "1) Traefik (automatic HTTPS)" >&2
    echo "2) No proxy (direct port)" >&2
    echo "" >&2
    read -p "Your choice (1-2) [1]: " PROXY_CHOICE
    PROXY_CHOICE="${PROXY_CHOICE:-1}"
    
    case $PROXY_CHOICE in
        1) echo "traefik" ;;
        2) echo "none" ;;
        *) echo "traefik" ;;
    esac
}

prompt_ssl_mode() {
    echo "🔒 SSL/TLS Configuration" >&2
    echo "-----------------------" >&2
    echo "1) Direct SSL (Traefik handles SSL with Let's Encrypt)" >&2
    echo "2) Proxy SSL (SSL terminated at upstream proxy, e.g., Cloudflare)" >&2
    echo "" >&2
    echo "Choose option 1 if Traefik directly faces the internet." >&2
    echo "Choose option 2 if there's another proxy/CDN in front of Traefik." >&2
    echo "" >&2
    read -p "Your choice (1-2) [1]: " SSL_CHOICE
    SSL_CHOICE="${SSL_CHOICE:-1}"
    
    case $SSL_CHOICE in
        1) echo "direct" ;;
        2) echo "proxy" ;;
        *) echo "direct" ;;
    esac
}

prompt_database_mode() {
    echo "📍 Database Mode" >&2
    echo "---------------" >&2
    echo "1) Local (deploy in swarm)" >&2
    echo "2) External (existing server)" >&2
    echo "" >&2
    read -p "Your choice (1-2) [1]: " DB_MODE_CHOICE
    DB_MODE_CHOICE="${DB_MODE_CHOICE:-1}"
    
    case $DB_MODE_CHOICE in
        1) echo "local" ;;
        2) echo "external" ;;
        *) echo "local" ;;
    esac
}

prompt_stack_name() {
    read -p "Stack name [python-api-template]: " STACK_NAME
    echo "${STACK_NAME:-python-api-template}"
}

prompt_data_root() {
    local default_path="$1"
    read -p "Data root directory [$default_path]: " DATA_ROOT
    echo "${DATA_ROOT:-$default_path}"
}

prompt_traefik_network() {
    local network_name=""
    local network_selected=false
    
    while [ "$network_selected" = false ]; do
        echo "" >&2
        echo "🌐 Available Docker Networks (overlay)" >&2
        echo "------------------------------------" >&2
        
        # Get overlay networks
        local networks=($(docker network ls --filter driver=overlay --format "{{.Name}}" 2>/dev/null))
        
        if [ ${#networks[@]} -eq 0 ]; then
            echo "❌ No overlay networks found" >&2
            echo "" >&2
            echo "1) Create 'traefik' network now" >&2
            echo "2) Enter custom network name" >&2
            echo "3) Cancel setup" >&2
            read -p "Your choice (1-3): " CHOICE
            
            case $CHOICE in
                1)
                    docker network create --driver=overlay traefik
                    if [ $? -eq 0 ]; then
                        echo "✅ Created network 'traefik'" >&2
                        network_name="traefik"
                        network_selected=true
                    else
                        echo "❌ Failed to create network" >&2
                    fi
                    ;;
                2)
                    read -p "Network name: " network_name
                    if [ -n "$network_name" ]; then
                        network_selected=true
                    fi
                    ;;
                3) return 1 ;;
            esac
        else
            # Auto-detect common Traefik network names and set a better default selection.
            local default_selection="1"
            local detected_network=""
            local preferred_networks=("traefik-public" "traefik_public" "traefik")
            for preferred in "${preferred_networks[@]}"; do
                local idx=0
                for net in "${networks[@]}"; do
                    if [ "$net" = "$preferred" ]; then
                        detected_network="$net"
                        default_selection="$((idx+1))"
                        break 2
                    fi
                    idx=$((idx+1))
                done
            done

            if [ -n "$detected_network" ]; then
                echo "✅ Auto-detected common Traefik network: $detected_network (recommended)" >&2
            fi

            # Display networks with numbers (highlight recommended one)
            local i=1
            for net in "${networks[@]}"; do
                if [ -n "$detected_network" ] && [ "$net" = "$detected_network" ]; then
                    echo "$i) ✅ $net (recommended)" >&2
                else
                    echo "$i) $net" >&2
                fi
                ((i++))
            done
            echo "" >&2
            echo "0) Create new network" >&2
            echo "" >&2
            
            read -p "Select network (number or name) [${default_selection}]: " SELECTION
            SELECTION="${SELECTION:-${default_selection}}"
            
            # Check if it's a number
            if [[ "$SELECTION" =~ ^[0-9]+$ ]]; then
                if [ "$SELECTION" -eq 0 ]; then
                    read -p "New network name: " network_name
                    if [ -n "$network_name" ]; then
                        docker network create --driver=overlay "$network_name"
                        if [ $? -eq 0 ]; then
                            echo "✅ Created network '$network_name'" >&2
                            network_selected=true
                        else
                            echo "❌ Failed to create network" >&2
                        fi
                    fi
                elif [ "$SELECTION" -ge 1 ] && [ "$SELECTION" -le ${#networks[@]} ]; then
                    network_name="${networks[$((SELECTION-1))]}"
                    echo "✅ Selected: $network_name" >&2
                    network_selected=true
                else
                    echo "❌ Invalid selection" >&2
                fi
            else
                # Treat as network name
                if docker network inspect "$SELECTION" &>/dev/null; then
                    network_name="$SELECTION"
                    echo "✅ Selected: $network_name" >&2
                    network_selected=true
                else
                    echo "❌ Network '$SELECTION' not found" >&2
                fi
            fi
        fi
    done
    
    echo "$network_name"
}

prompt_api_domain() {
    local api_url=""
    while [ -z "$api_url" ]; do
        read -p "API domain (e.g., api.example.com): " api_url
        if [ -z "$api_url" ]; then
            echo "⚠️  Domain is required for Traefik"
        fi
    done
    echo "$api_url"
}

prompt_published_port() {
    read -p "Published port [8000]: " PUBLISHED_PORT
    echo "${PUBLISHED_PORT:-8000}"
}

prompt_docker_image() {
    local image_verified=false
    local image_name=""
    local image_version=""
    
    echo "" >&2
    echo "🐳 Docker Image Configuration" >&2
    echo "----------------------------" >&2
    
    while [ "$image_verified" = false ]; do
        read -p "Docker image name [sokrates1989/python-api-template]: " image_name
        image_name="${image_name:-sokrates1989/python-api-template}"
        read -p "Image version [latest]: " image_version
        image_version="${image_version:-latest}"
        
        echo "Verifying image: ${image_name}:${image_version}" >&2
        docker pull "${image_name}:${image_version}" >/dev/null 2>&1
        
        if [ $? -eq 0 ]; then
            echo "✅ Image verified" >&2
            image_verified=true
        else
            echo "" >&2
            echo "❌ Failed to pull image" >&2
            echo "1) Login to Docker registry" >&2
            echo "2) Re-enter image info" >&2
            echo "3) Skip verification" >&2
            echo "4) Cancel setup" >&2
            read -p "Your choice (1-4): " IMAGE_CHOICE
            
            case $IMAGE_CHOICE in
                1) docker login ;;
                2) continue ;;
                3) image_verified=true ;;
                4) return 1 ;;
            esac
        fi
    done
    
    echo "${image_name}:${image_version}"
    return 0
}

prompt_replicas() {
    local service_name="$1"
    local default_count="${2:-1}"
    read -p "${service_name} replicas [$default_count]: " REPLICAS
    echo "${REPLICAS:-$default_count}"
}

prompt_secret_names() {
    local stack_name="$1"
    local stack_name_upper=$(echo "$stack_name" | tr '[:lower:]' '[:upper:]' | sed 's/[^A-Z0-9]/_/g')
    
    read -p "Database password secret [${stack_name_upper}_DB_PASSWORD]: " DB_PASSWORD_SECRET
    DB_PASSWORD_SECRET="${DB_PASSWORD_SECRET:-${stack_name_upper}_DB_PASSWORD}"
    
    read -p "Admin API key secret [${stack_name_upper}_ADMIN_API_KEY]: " ADMIN_API_KEY_SECRET
    ADMIN_API_KEY_SECRET="${ADMIN_API_KEY_SECRET:-${stack_name_upper}_ADMIN_API_KEY}"
    
    read -p "Backup restore API key secret [${stack_name_upper}_BACKUP_RESTORE_API_KEY]: " BACKUP_RESTORE_API_KEY_SECRET
    BACKUP_RESTORE_API_KEY_SECRET="${BACKUP_RESTORE_API_KEY_SECRET:-${stack_name_upper}_BACKUP_RESTORE_API_KEY}"
    
    read -p "Backup delete API key secret [${stack_name_upper}_BACKUP_DELETE_API_KEY]: " BACKUP_DELETE_API_KEY_SECRET
    BACKUP_DELETE_API_KEY_SECRET="${BACKUP_DELETE_API_KEY_SECRET:-${stack_name_upper}_BACKUP_DELETE_API_KEY}"
    
    echo "${DB_PASSWORD_SECRET}:${ADMIN_API_KEY_SECRET}:${BACKUP_RESTORE_API_KEY_SECRET}:${BACKUP_DELETE_API_KEY_SECRET}"
}

prompt_yes_no() {
    local prompt_text="$1"
    local default="${2:-Y}"
    
    if [ "$default" = "Y" ] || [ "$default" = "y" ]; then
        read -p "$prompt_text (Y/n): " RESPONSE
        if [[ "$RESPONSE" =~ ^[Nn]$ ]]; then
            return 1
        else
            return 0
        fi
    else
        read -p "$prompt_text (y/N): " RESPONSE
        if [[ "$RESPONSE" =~ ^[Yy]$ ]]; then
            return 0
        else
            return 1
        fi
    fi
}
