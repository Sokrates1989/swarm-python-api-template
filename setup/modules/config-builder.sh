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
    local ssl_mode="${5:-direct}"  # Default to direct SSL if not specified
    
    echo "⚙️  Building swarm-stack.yml..."
    
    # Start with base
    cat "${project_root}/setup/compose-modules/base.yml" > "${project_root}/swarm-stack.yml"
    
    # Build API service from template with snippet injection
    local temp_api="${project_root}/setup/compose-modules/api.temp.yml"
    cp "${project_root}/setup/compose-modules/api.template.yml" "$temp_api"
    
    # Inject database environment snippet
    # Map postgresql -> postgres for file names
    local db_file_name="$db_type"
    if [ "$db_type" = "postgresql" ]; then
        db_file_name="postgres"
    fi
    
    local db_env_snippet="${project_root}/setup/compose-modules/snippets/db-${db_file_name}-${db_mode}.env.yml"
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
        # Inject Traefik labels at ###PROXY_LABELS### based on SSL mode
        local proxy_labels_snippet="${project_root}/setup/compose-modules/snippets/proxy-traefik-${ssl_mode}-ssl.labels.yml"
        if [ -f "$proxy_labels_snippet" ]; then
            sed -i "/###PROXY_LABELS###/r $proxy_labels_snippet" "$temp_api"
        fi
        sed -i '/###PROXY_LABELS###/d' "$temp_api"
        # Remove ###PROXY_PORTS### placeholder (not used for Traefik)
        sed -i '/###PROXY_PORTS###/d' "$temp_api"
    else
        # Inject ports at ###PROXY_PORTS###
        local proxy_ports_snippet="${project_root}/setup/compose-modules/snippets/proxy-none.ports.yml"
        if [ -f "$proxy_ports_snippet" ]; then
            sed -i "/###PROXY_PORTS###/r $proxy_ports_snippet" "$temp_api"
        fi
        sed -i '/###PROXY_PORTS###/d' "$temp_api"
        # Remove ###PROXY_LABELS### placeholder (not used for direct ports)
        sed -i '/###PROXY_LABELS###/d' "$temp_api"
    fi
    
    # Append API service to stack
    cat "$temp_api" >> "${project_root}/swarm-stack.yml"
    rm -f "$temp_api"
    
    # Add database service if local deployment
    if [ "$db_mode" = "local" ]; then
        # Map postgresql -> postgres for file names
        local db_file_name="$db_type"
        if [ "$db_type" = "postgresql" ]; then
            db_file_name="postgres"
        fi
        cat "${project_root}/setup/compose-modules/${db_file_name}-local.yml" >> "${project_root}/swarm-stack.yml"
    fi
    
    # Add footer (networks and secrets)
    cat "${project_root}/setup/compose-modules/footer.yml" >> "${project_root}/swarm-stack.yml"
    
    echo "✅ swarm-stack.yml created"
}

update_env_values() {
    local env_file="$1"
    local key="$2"
    local value="$3"
    
    # Escape special characters in value for sed
    local escaped_value=$(printf '%s\n' "$value" | sed 's:[\\/&]:\\&:g;$!s/$/\\/')
    escaped_value=${escaped_value%\\}
    
    # Use different sed syntax based on OS
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        sed -i '' "s|^${key}=.*|${key}=${escaped_value}|" "$env_file"
    else
        # Linux
        sed -i "s|^${key}=.*|${key}=${escaped_value}|" "$env_file"
    fi
}

update_stack_secrets() {
    local stack_file="$1"
    local db_password_secret="$2"
    local admin_api_key_secret="$3"
    local backup_restore_api_key_secret="$4"
    local backup_delete_api_key_secret="$5"
    
    # Use different sed syntax based on OS
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        sed -i '' "s|XXX_CHANGE_ME_DB_PASSWORD_XXX|$db_password_secret|g" "$stack_file"
        sed -i '' "s|XXX_CHANGE_ME_ADMIN_API_KEY_XXX|$admin_api_key_secret|g" "$stack_file"
        sed -i '' "s|XXX_CHANGE_ME_BACKUP_RESTORE_API_KEY_XXX|$backup_restore_api_key_secret|g" "$stack_file"
        sed -i '' "s|XXX_CHANGE_ME_BACKUP_DELETE_API_KEY_XXX|$backup_delete_api_key_secret|g" "$stack_file"
    else
        # Linux
        sed -i "s|XXX_CHANGE_ME_DB_PASSWORD_XXX|$db_password_secret|g" "$stack_file"
        sed -i "s|XXX_CHANGE_ME_ADMIN_API_KEY_XXX|$admin_api_key_secret|g" "$stack_file"
        sed -i "s|XXX_CHANGE_ME_BACKUP_RESTORE_API_KEY_XXX|$backup_restore_api_key_secret|g" "$stack_file"
        sed -i "s|XXX_CHANGE_ME_BACKUP_DELETE_API_KEY_XXX|$backup_delete_api_key_secret|g" "$stack_file"
    fi
}

update_stack_network() {
    local stack_file="$1"
    local traefik_network="$2"
    
    # Use different sed syntax based on OS
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        sed -i '' "s|XXX_CHANGE_ME_TRAEFIK_NETWORK_NAME_XXX|$traefik_network|g" "$stack_file"
    else
        # Linux
        sed -i "s|XXX_CHANGE_ME_TRAEFIK_NETWORK_NAME_XXX|$traefik_network|g" "$stack_file"
    fi
}

add_cognito_to_stack() {
    local stack_file="$1"
    local project_root="$2"
    local stack_name_upper="$3"
    
    # Generate secret names
    local pool_id_secret="${stack_name_upper}_COGNITO_USER_POOL_ID"
    local client_id_secret="${stack_name_upper}_COGNITO_APP_CLIENT_ID"
    local access_key_secret="${stack_name_upper}_AWS_ACCESS_KEY_ID"
    local secret_key_secret="${stack_name_upper}_AWS_SECRET_ACCESS_KEY"
    
    # Read the stack file
    local content=$(cat "$stack_file")
    
    # Check if Cognito secrets are already added
    if echo "$content" | grep -q "AWS_ACCESS_KEY_ID_FILE"; then
        echo "ℹ️  Cognito configuration already present in stack file"
        return 0
    fi
    
    echo "⚙️  Adding AWS Cognito secrets to stack file..."
    
    # Add Cognito secrets to API service secrets section
    # Find the line with the last secret and add Cognito secrets after it
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        sed -i '' "/- \".*_BACKUP_DELETE_API_KEY.*\"/a\\
      - \"$pool_id_secret\"\\
      - \"$client_id_secret\"\\
      - \"$access_key_secret\"\\
      - \"$secret_key_secret\"
" "$stack_file"
        
        # Add Cognito environment variables after BACKUP_DELETE_API_KEY_FILE
        local cognito_env_snippet="${project_root}/setup/compose-modules/snippets/cognito-env.yml"
        if [ -f "$cognito_env_snippet" ]; then
            # Replace placeholder secret names in snippet
            local temp_snippet="${project_root}/setup/compose-modules/cognito-env.temp.yml"
            sed "s|XXX_CHANGE_ME_COGNITO_USER_POOL_ID_XXX|$pool_id_secret|g; s|XXX_CHANGE_ME_COGNITO_APP_CLIENT_ID_XXX|$client_id_secret|g; s|XXX_CHANGE_ME_AWS_ACCESS_KEY_ID_XXX|$access_key_secret|g; s|XXX_CHANGE_ME_AWS_SECRET_ACCESS_KEY_XXX|$secret_key_secret|g" "$cognito_env_snippet" > "$temp_snippet"
            sed -i '' "/BACKUP_DELETE_API_KEY_FILE/r $temp_snippet" "$stack_file"
            rm -f "$temp_snippet"
        fi
        
        # Add Cognito secrets to footer secrets section
        sed -i '' "/\".*_BACKUP_DELETE_API_KEY.*\":/a\\
  \"$pool_id_secret\":\\
    external: true\\
  \"$client_id_secret\":\\
    external: true\\
  \"$access_key_secret\":\\
    external: true\\
  \"$secret_key_secret\":\\
    external: true
" "$stack_file"
    else
        # Linux
        sed -i "/- \".*_BACKUP_DELETE_API_KEY.*\"/a\\      - \"$pool_id_secret\"\n      - \"$client_id_secret\"\n      - \"$access_key_secret\"\n      - \"$secret_key_secret\"" "$stack_file"
        
        # Add Cognito environment variables after BACKUP_DELETE_API_KEY_FILE
        local cognito_env_snippet="${project_root}/setup/compose-modules/snippets/cognito-env.yml"
        if [ -f "$cognito_env_snippet" ]; then
            # Replace placeholder secret names in snippet
            local temp_snippet="${project_root}/setup/compose-modules/cognito-env.temp.yml"
            sed "s|XXX_CHANGE_ME_COGNITO_USER_POOL_ID_XXX|$pool_id_secret|g; s|XXX_CHANGE_ME_COGNITO_APP_CLIENT_ID_XXX|$client_id_secret|g; s|XXX_CHANGE_ME_AWS_ACCESS_KEY_ID_XXX|$access_key_secret|g; s|XXX_CHANGE_ME_AWS_SECRET_ACCESS_KEY_XXX|$secret_key_secret|g" "$cognito_env_snippet" > "$temp_snippet"
            sed -i "/BACKUP_DELETE_API_KEY_FILE/r $temp_snippet" "$stack_file"
            rm -f "$temp_snippet"
        fi
        
        # Add Cognito secrets to footer secrets section
        sed -i "/\".*_BACKUP_DELETE_API_KEY.*\":/a\\  \"$pool_id_secret\":\n    external: true\n  \"$client_id_secret\":\n    external: true\n  \"$access_key_secret\":\n    external: true\n  \"$secret_key_secret\":\n    external: true" "$stack_file"
    fi
    
    echo "✅ Cognito secrets added to stack file"
    return 0
}

backup_existing_files() {
    local project_root="$1"
    local timestamp=$(date +%Y_%m_%d__%H_%M_%S)
    
    # Create backup directories
    mkdir -p "${project_root}/backup/env"
    mkdir -p "${project_root}/backup/swarm-stack-yml"
    
    if [ -f "${project_root}/.env" ]; then
        local backup_file="${project_root}/backup/env/.env.${timestamp}"
        cp "${project_root}/.env" "$backup_file"
        echo "📋 Backed up .env to backup/env/.env.${timestamp}"
    fi
    
    if [ -f "${project_root}/swarm-stack.yml" ]; then
        local backup_file="${project_root}/backup/swarm-stack-yml/swarm-stack.yml.${timestamp}"
        cp "${project_root}/swarm-stack.yml" "$backup_file"
        echo "📋 Backed up swarm-stack.yml to backup/swarm-stack-yml/swarm-stack.yml.${timestamp}"
    fi
}
