#!/bin/bash
# User prompts module
# Handles all user input collection

prompt_database_type() {
    echo "🗄️  Database Configuration"
    echo "-------------------------"
    echo "1) PostgreSQL (relational data)"
    echo "2) Neo4j (graph data)"
    echo ""
    read -p "Your choice (1-2) [1]: " DB_CHOICE
    DB_CHOICE="${DB_CHOICE:-1}"
    
    case $DB_CHOICE in
        1) echo "postgresql" ;;
        2) echo "neo4j" ;;
        *) echo "postgresql" ;;
    esac
}

prompt_proxy_type() {
    echo "🌐 Proxy Configuration"
    echo "---------------------"
    echo "1) Traefik (automatic HTTPS)"
    echo "2) No proxy (direct port)"
    echo ""
    read -p "Your choice (1-2) [1]: " PROXY_CHOICE
    PROXY_CHOICE="${PROXY_CHOICE:-1}"
    
    case $PROXY_CHOICE in
        1) echo "traefik" ;;
        2) echo "none" ;;
        *) echo "traefik" ;;
    esac
}

prompt_database_mode() {
    echo "📍 Database Mode"
    echo "---------------"
    echo "1) Local (deploy in swarm)"
    echo "2) External (existing server)"
    echo ""
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
    
    echo ""
    echo "🐳 Docker Image Configuration"
    echo "----------------------------"
    
    while [ "$image_verified" = false ]; do
        read -p "Docker image name (e.g., sokrates1989/python-api-template): " image_name
        read -p "Image version [latest]: " image_version
        image_version="${image_version:-latest}"
        
        echo "Verifying image: ${image_name}:${image_version}"
        docker pull "${image_name}:${image_version}" 2>&1
        
        if [ $? -eq 0 ]; then
            echo "✅ Image verified"
            image_verified=true
        else
            echo ""
            echo "❌ Failed to pull image"
            echo "1) Login to Docker registry"
            echo "2) Re-enter image info"
            echo "3) Skip verification"
            echo "4) Cancel setup"
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
    
    echo "${DB_PASSWORD_SECRET}:${ADMIN_API_KEY_SECRET}"
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
