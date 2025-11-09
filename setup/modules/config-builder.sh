#!/bin/bash
# Configuration builder module
# Builds .env and swarm-stack.yml from templates

build_env_file() {
    local db_type="$1"
    local db_mode="$2"
    local proxy_type="$3"
    local project_root="$4"
    
    echo "⚙️  Building .env file..."
    
    # Start with base template
    cat "${project_root}/setup/env-templates/.env.base.template" > "${project_root}/.env"
    
    # Add database configuration
    if [ "$db_type" = "postgresql" ]; then
        if [ "$db_mode" = "local" ]; then
            cat "${project_root}/setup/env-templates/.env.postgres-local.template" >> "${project_root}/.env"
        else
            cat "${project_root}/setup/env-templates/.env.postgres-external.template" >> "${project_root}/.env"
        fi
    elif [ "$db_type" = "neo4j" ]; then
        if [ "$db_mode" = "local" ]; then
            cat "${project_root}/setup/env-templates/.env.neo4j-local.template" >> "${project_root}/.env"
        else
            cat "${project_root}/setup/env-templates/.env.neo4j-external.template" >> "${project_root}/.env"
        fi
    fi
    
    # Add proxy configuration
    if [ "$proxy_type" = "traefik" ]; then
        cat "${project_root}/setup/env-templates/.env.proxy-traefik.template" >> "${project_root}/.env"
    else
        cat "${project_root}/setup/env-templates/.env.proxy-none.template" >> "${project_root}/.env"
    fi
    
    echo "✅ .env file created"
}

build_stack_file() {
    local db_type="$1"
    local db_mode="$2"
    local proxy_type="$3"
    local project_root="$4"
    
    echo "⚙️  Building swarm-stack.yml..."
    
    # Start with base
    cat "${project_root}/setup/compose-modules/base.yml" > "${project_root}/swarm-stack.yml"
    
    # Build API service from template with snippet injection
    local temp_api="${project_root}/setup/compose-modules/api.temp.yml"
    cp "${project_root}/setup/compose-modules/api.template.yml" "$temp_api"
    
    # Inject database environment snippet
    local db_env_snippet="${project_root}/setup/compose-modules/snippets/db-${db_type}-${db_mode}.env.yml"
    if [ -f "$db_env_snippet" ]; then
        sed -i "/###DATABASE_ENV###/r $db_env_snippet" "$temp_api"
        sed -i '/###DATABASE_ENV###/d' "$temp_api"
    fi
    
    # Inject proxy network snippet (only for Traefik)
    if [ "$proxy_type" = "traefik" ]; then
        local proxy_network_snippet="${project_root}/setup/compose-modules/snippets/proxy-traefik.network.yml"
        if [ -f "$proxy_network_snippet" ]; then
            sed -i "/###PROXY_NETWORK###/r $proxy_network_snippet" "$temp_api"
        fi
    fi
    sed -i '/###PROXY_NETWORK###/d' "$temp_api"
    
    # Inject proxy configuration snippet
    if [ "$proxy_type" = "traefik" ]; then
        local proxy_labels_snippet="${project_root}/setup/compose-modules/snippets/proxy-traefik.labels.yml"
        if [ -f "$proxy_labels_snippet" ]; then
            sed -i "/###PROXY_CONFIG###/r $proxy_labels_snippet" "$temp_api"
        fi
    else
        local proxy_ports_snippet="${project_root}/setup/compose-modules/snippets/proxy-none.ports.yml"
        if [ -f "$proxy_ports_snippet" ]; then
            sed -i "/###PROXY_CONFIG###/r $proxy_ports_snippet" "$temp_api"
        fi
    fi
    sed -i '/###PROXY_CONFIG###/d' "$temp_api"
    
    # Append API service to stack
    cat "$temp_api" >> "${project_root}/swarm-stack.yml"
    rm -f "$temp_api"
    
    # Add database service if local deployment
    if [ "$db_mode" = "local" ]; then
        cat "${project_root}/setup/compose-modules/${db_type}-local.yml" >> "${project_root}/swarm-stack.yml"
    fi
    
    # Add footer (networks and secrets)
    cat "${project_root}/setup/compose-modules/footer.yml" >> "${project_root}/swarm-stack.yml"
    
    echo "✅ swarm-stack.yml created"
}

update_env_values() {
    local env_file="$1"
    local key="$2"
    local value="$3"
    
    # Use different sed syntax based on OS
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        sed -i '' "s|^${key}=.*|${key}=${value}|" "$env_file"
    else
        # Linux
        sed -i "s|^${key}=.*|${key}=${value}|" "$env_file"
    fi
}

update_stack_secrets() {
    local stack_file="$1"
    local db_password_secret="$2"
    local admin_api_key_secret="$3"
    
    # Use different sed syntax based on OS
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        sed -i '' "s|XXX_CHANGE_ME_DB_PASSWORD_XXX|$db_password_secret|g" "$stack_file"
        sed -i '' "s|XXX_CHANGE_ME_ADMIN_API_KEY_XXX|$admin_api_key_secret|g" "$stack_file"
    else
        # Linux
        sed -i "s|XXX_CHANGE_ME_DB_PASSWORD_XXX|$db_password_secret|g" "$stack_file"
        sed -i "s|XXX_CHANGE_ME_ADMIN_API_KEY_XXX|$admin_api_key_secret|g" "$stack_file"
    fi
}

backup_existing_files() {
    local project_root="$1"
    
    if [ -f "${project_root}/.env" ]; then
        local backup_file="${project_root}/.env.backup.$(date +%Y%m%d_%H%M%S)"
        cp "${project_root}/.env" "$backup_file"
        echo "📋 Backed up .env to $backup_file"
    fi
    
    if [ -f "${project_root}/swarm-stack.yml" ]; then
        local backup_file="${project_root}/swarm-stack.yml.backup.$(date +%Y%m%d_%H%M%S)"
        cp "${project_root}/swarm-stack.yml" "$backup_file"
        echo "📋 Backed up swarm-stack.yml to $backup_file"
    fi
}
