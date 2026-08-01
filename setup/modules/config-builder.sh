#!/bin/bash
# ==============================================================================
# config-builder.sh - Configuration file builder module
# ==============================================================================
#
# This module assembles .env and swarm-stack.yml from modular templates based
# on user selections (database type, database mode, proxy type, SSL mode).
#
# Functions:
#   build_env_file        - Assemble .env from base + db + proxy templates
#   build_stack_file      - Assemble swarm-stack.yml with snippet injection
#   update_env_values     - Update a key=value pair in .env
#   update_stack_secrets  - Replace secret placeholders in stack file
#   update_stack_network  - Replace Traefik network placeholder
#   add_cognito_to_stack  - Inject AWS Cognito secret references
#   backup_existing_files - Backup .env and swarm-stack.yml before changes
#
# Dependencies:
#   - Template files in setup/env-templates/ and setup/compose-modules/
#   - sed (GNU or BSD), python3 (for Cognito placeholder injection)
#
# ==============================================================================

_config_builder_sed_inplace() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "$@"
    else
        sed -i "$@"
    fi
}

# Shared capability adapters used by every compose-module renderer.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/admin-ui-compose.sh"
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/deployment-memory-policy.sh"

# ------------------------------------------------------------------------------
# build_env_file
# ------------------------------------------------------------------------------
# Concatenates environment variable templates to produce .env. Selects
# database and proxy snippets based on db_type, db_mode, and proxy_type.
#
# Arguments:
#   $1 - db_type: "postgresql" or "neo4j"
#   $2 - db_mode: "local" or "external"
#   $3 - proxy_type: "traefik" or "none"
#   $4 - project_root: absolute path to project root
# ------------------------------------------------------------------------------
build_env_file() {
    local db_type="$1"
    local db_mode="$2"
    local proxy_type="$3"
    local project_root="$4"
    
    echo "Building .env file..."
    
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
    
    echo " .env file created"
}

# ------------------------------------------------------------------------------
# build_profile_compose_stack_file
# ------------------------------------------------------------------------------
# Assembles swarm-stack.yml from two complete compose modules declared by the
# selected site profile. This supports specialized service/network/secret
# topology without teaching shared orchestration an application identity.
#
# The dedicated compose modules already contain the complete services, networks,
# and secrets definitions, so no snippet injection or placeholder substitution
# is required. The API module begins with its own "services:" header and the
# footer provides the top-level "networks:" and "secrets:" sections.
#
# Arguments:
#   $1 - project_root: absolute path to the repository root.
#   $2 - API/service module path relative to the repository root.
#   $3 - Footer module path relative to the repository root.
#
# Returns:
#   0 on success, 1 when a required compose module is missing.
# ------------------------------------------------------------------------------
build_profile_compose_stack_file() {
    local project_root="$1"
    local api_relative="$2"
    local footer_relative="$3"
    local api_module=""
    local footer_module=""

    if [ -z "$api_relative" ] || [ -z "$footer_relative" ] ||
        [[ "$api_relative" = /* ]] || [[ "$footer_relative" = /* ]] ||
        [[ "$api_relative" = *".."* ]] || [[ "$footer_relative" = *".."* ]]; then
        echo "Profile compose-module paths are missing or unsafe." >&2
        return 1
    fi
    api_module="${project_root}/${api_relative}"
    footer_module="${project_root}/${footer_relative}"
    echo "Building swarm-stack.yml (profile-declared compose modules)..."

    if [ ! -f "$api_module" ] || [ ! -f "$footer_module" ]; then
        echo "Profile-declared compose modules not found:" >&2
        [ -f "$api_module" ] || echo "  missing: $api_module" >&2
        [ -f "$footer_module" ] || echo "  missing: $footer_module" >&2
        return 1
    fi

    {
        cat "$api_module"
        echo ""
        cat "$footer_module"
    } > "${project_root}/swarm-stack.yml"
    apply_deployment_memory_limit_template \
        "${project_root}/swarm-stack.yml" \
        "${MEMORY_LIMIT:-unlimited}" || return 1

    echo "swarm-stack.yml created"
}

# ------------------------------------------------------------------------------
# build_stack_file
# ------------------------------------------------------------------------------
# Assembles swarm-stack.yml from the service header, profile-enabled Redis,
# api.template.yml (with database/proxy snippet injection), optional database
# and management services, and footer.yml.
#
# Arguments:
#   $1 - db_type: "postgresql" or "neo4j"
#   $2 - db_mode: "local" or "external"
#   $3 - proxy_type: "traefik" or "none"
#   $4 - project_root: absolute path to project root
#   $5 - ssl_mode: letsencrypt/direct or proxy for Traefik labels.
# ------------------------------------------------------------------------------
build_stack_file() {
    if [ "${STACK_FAMILY:-api}" = "nginx" ]; then
        build_nginx_stack_file "$3" "$4" "${5:-direct}"
        return $?
    fi

    if [ -n "${PROFILE_API_TEMPLATE:-}" ] ||
        [ -n "${PROFILE_FOOTER_TEMPLATE:-}" ]; then
        build_profile_compose_stack_file \
            "$4" \
            "${PROFILE_API_TEMPLATE:-}" \
            "${PROFILE_FOOTER_TEMPLATE:-}"
        return $?
    fi

    local db_type="$1"
    local db_mode="$2"
    local proxy_type="$3"
    local project_root="$4"
    local ssl_mode="${5:-direct}"  # Default to direct SSL if not specified
    local label_mode="direct"
    
    echo "Building swarm-stack.yml..."
    
    # Start with base
    cat "${project_root}/setup/compose-modules/base.yml" > "${project_root}/swarm-stack.yml"
    if [ "${APP_REQUIRES_REDIS:-true}" = "true" ]; then
        cat "${project_root}/setup/compose-modules/redis.yml" >> \
            "${project_root}/swarm-stack.yml"
    fi
    
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
    if [ "$db_type" = "none" ]; then
        _config_builder_sed_inplace '/###DATABASE_ENV###/d' "$temp_api"
    elif [ -f "$db_env_snippet" ]; then
        _config_builder_sed_inplace "/###DATABASE_ENV###/r $db_env_snippet" "$temp_api"
        _config_builder_sed_inplace '/###DATABASE_ENV###/d' "$temp_api"
    else
        echo "Database environment module is missing: ${db_env_snippet}" >&2
        rm -f "$temp_api"
        return 1
    fi
    
    # Inject proxy network snippet (only for Traefik)
    if [ "$proxy_type" = "traefik" ]; then
        local proxy_network_snippet="${project_root}/setup/compose-modules/snippets/proxy-traefik.network.yml"
        if [ ! -f "$proxy_network_snippet" ]; then
            echo "Traefik network module is missing: ${proxy_network_snippet}" >&2
            rm -f "$temp_api"
            return 1
        fi
        _config_builder_sed_inplace "/###PROXY_NETWORK###/r $proxy_network_snippet" "$temp_api"
    fi
    _config_builder_sed_inplace '/###PROXY_NETWORK###/d' "$temp_api"
    
    # Inject proxy configuration snippet
    if [ "$proxy_type" = "traefik" ]; then
        # Inject Traefik labels at ###PROXY_LABELS### based on SSL mode
        if [ "$ssl_mode" = "proxy" ]; then
            label_mode="proxy"
        elif [ "$ssl_mode" != "direct" ] &&
            [ "$ssl_mode" != "letsencrypt" ]; then
            echo "Unsupported Traefik SSL mode: ${ssl_mode}" >&2
            rm -f "$temp_api"
            return 1
        fi
        local proxy_labels_snippet="${project_root}/setup/compose-modules/snippets/proxy-traefik-${label_mode}-ssl.labels.yml"
        if [ ! -f "$proxy_labels_snippet" ]; then
            echo "Traefik label module is missing: ${proxy_labels_snippet}" >&2
            rm -f "$temp_api"
            return 1
        fi
        _config_builder_sed_inplace "/###PROXY_LABELS###/r $proxy_labels_snippet" "$temp_api"
        _config_builder_sed_inplace '/###PROXY_LABELS###/d' "$temp_api"
        # Remove ###PROXY_PORTS### placeholder (not used for Traefik)
        _config_builder_sed_inplace '/###PROXY_PORTS###/d' "$temp_api"
    else
        # Inject ports at ###PROXY_PORTS###
        local proxy_ports_snippet="${project_root}/setup/compose-modules/snippets/proxy-none.ports.yml"
        if [ ! -f "$proxy_ports_snippet" ]; then
            echo "Direct-port module is missing: ${proxy_ports_snippet}" >&2
            rm -f "$temp_api"
            return 1
        fi
        _config_builder_sed_inplace "/###PROXY_PORTS###/r $proxy_ports_snippet" "$temp_api"
        _config_builder_sed_inplace '/###PROXY_PORTS###/d' "$temp_api"
        # Remove ###PROXY_LABELS### placeholder (not used for direct ports)
        _config_builder_sed_inplace '/###PROXY_LABELS###/d' "$temp_api"
    fi
    
    apply_deployment_memory_limit_template \
        "$temp_api" \
        "${MEMORY_LIMIT:-unlimited}" || return 1

    # Append API service to stack
    cat "$temp_api" >> "${project_root}/swarm-stack.yml"
    rm -f "$temp_api"
    
    # Add database service if local deployment and database type is not "none"
    if [ "$db_mode" = "local" ] && [ "$db_type" != "none" ]; then
        # Map postgresql -> postgres for file names
        local db_file_name="$db_type"
        if [ "$db_type" = "postgresql" ]; then
            db_file_name="postgres"
        fi
        local database_service_module="${project_root}/setup/compose-modules/${db_file_name}-local.yml"
        if [ ! -f "$database_service_module" ]; then
            echo "Local database service module is missing: ${database_service_module}" >&2
            return 1
        fi
        cat "$database_service_module" >> "${project_root}/swarm-stack.yml"
    fi
    
    # Add database management only when the selected profile declares it.
    if [ "$db_mode" = "local" ] &&
        [ "${PROFILE_ADMIN_UI_ENABLED:-false}" = "true" ] &&
        [ -n "${PROFILE_ADMIN_UI_TYPE:-}" ]; then
        append_admin_ui_service \
            "$project_root" \
            "$PROFILE_ADMIN_UI_TYPE" \
            "$proxy_type" \
            "$ssl_mode" ||
            return 1
    fi
    
    # Add footer (networks and secrets)
    cat "${project_root}/setup/compose-modules/footer.yml" >> "${project_root}/swarm-stack.yml"
    
    echo "swarm-stack.yml created"
}

# ------------------------------------------------------------------------------
# update_env_values
# ------------------------------------------------------------------------------
# Updates a single key=value line in the given .env file using sed.
#
# Arguments:
#   $1 - env_file: path to .env
#   $2 - key: variable name
#   $3 - value: new value
# ------------------------------------------------------------------------------
update_env_values() {
    local env_file="$1"
    local key="$2"
    local value="$3"

    local quoted_value
    quoted_value="$value"
    quoted_value="${quoted_value//\\/\\\\}"
    quoted_value="${quoted_value//\"/\\\"}"
    quoted_value="${quoted_value//\$/\\$}"
    quoted_value="${quoted_value//\`/\\\`}" 
    quoted_value="\"${quoted_value}\""

    local line_replacement
    line_replacement="${key}=${quoted_value}"

    local sed_replacement
    sed_replacement=$(printf '%s' "$line_replacement" | sed 's/[\\&|]/\\\\&/g')

    if grep -q "^${key}=" "$env_file" 2>/dev/null; then
        if [[ "$OSTYPE" == "darwin"* ]]; then
            sed -i '' "s|^${key}=.*|${sed_replacement}|" "$env_file"
        else
            sed -i "s|^${key}=.*|${sed_replacement}|" "$env_file"
        fi
    else
        printf '%s\n' "$line_replacement" >> "$env_file"
    fi
}

# ------------------------------------------------------------------------------
# update_stack_secrets
# ------------------------------------------------------------------------------
# Replaces XXX_CHANGE_ME_*_XXX placeholders in swarm-stack.yml with actual
# secret names derived from the stack name.
#
# Arguments:
#   $1 - stack_file: path to swarm-stack.yml
#   $2 - db_password_secret
#   $3 - admin_api_key_secret
#   $4 - backup_restore_api_key_secret
#   $5 - backup_delete_api_key_secret
#   $6 - db_ui_admin_password_secret (optional, used for pgAdmin or Mongo Express)
#   $7 - include_db_ui_secret: true only when the management service is rendered
# ------------------------------------------------------------------------------
update_stack_secrets() {
    local stack_file="$1"
    local db_password_secret="$2"
    local admin_api_key_secret="$3"
    local backup_restore_api_key_secret="$4"
    local backup_delete_api_key_secret="$5"
    local db_ui_admin_password_secret="${6:-}"
    local include_db_ui_secret="${7:-true}"

    if [ "$include_db_ui_secret" != "true" ]; then
        _config_builder_sed_inplace \
            '/"XXX_CHANGE_ME_DB_UI_ADMIN_PASSWORD_XXX":/{N;d;}' \
            "$stack_file"
    fi
    
    # Use different sed syntax based on OS
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        sed -i '' "s|XXX_CHANGE_ME_DB_PASSWORD_XXX|$db_password_secret|g" "$stack_file"
        sed -i '' "s|XXX_CHANGE_ME_ADMIN_API_KEY_XXX|$admin_api_key_secret|g" "$stack_file"
        sed -i '' "s|XXX_CHANGE_ME_BACKUP_RESTORE_API_KEY_XXX|$backup_restore_api_key_secret|g" "$stack_file"
        sed -i '' "s|XXX_CHANGE_ME_BACKUP_DELETE_API_KEY_XXX|$backup_delete_api_key_secret|g" "$stack_file"
        if [ -n "$db_ui_admin_password_secret" ]; then
            sed -i '' "s|XXX_CHANGE_ME_DB_UI_ADMIN_PASSWORD_XXX|$db_ui_admin_password_secret|g" "$stack_file"
            sed -i '' "s|XXX_CHANGE_ME_PGADMIN_PASSWORD_XXX|$db_ui_admin_password_secret|g" "$stack_file"
        fi
        if [ -n "$db_ui_admin_password_secret" ]; then
            sed -i '' "s|XXX_CHANGE_ME_MONGO_EXPRESS_PASSWORD_XXX|$db_ui_admin_password_secret|g" "$stack_file"
        fi
    else
        # Linux
        sed -i "s|XXX_CHANGE_ME_DB_PASSWORD_XXX|$db_password_secret|g" "$stack_file"
        sed -i "s|XXX_CHANGE_ME_ADMIN_API_KEY_XXX|$admin_api_key_secret|g" "$stack_file"
        sed -i "s|XXX_CHANGE_ME_BACKUP_RESTORE_API_KEY_XXX|$backup_restore_api_key_secret|g" "$stack_file"
        sed -i "s|XXX_CHANGE_ME_BACKUP_DELETE_API_KEY_XXX|$backup_delete_api_key_secret|g" "$stack_file"
        if [ -n "$db_ui_admin_password_secret" ]; then
            sed -i "s|XXX_CHANGE_ME_DB_UI_ADMIN_PASSWORD_XXX|$db_ui_admin_password_secret|g" "$stack_file"
            sed -i "s|XXX_CHANGE_ME_PGADMIN_PASSWORD_XXX|$db_ui_admin_password_secret|g" "$stack_file"
            sed -i "s|XXX_CHANGE_ME_MONGO_EXPRESS_PASSWORD_XXX|$db_ui_admin_password_secret|g" "$stack_file"
        fi
    fi
}

# ------------------------------------------------------------------------------
# update_stack_network
# ------------------------------------------------------------------------------
# Replaces the Traefik network placeholder in swarm-stack.yml.
#
# Arguments:
#   $1 - stack_file: path to swarm-stack.yml
#   $2 - traefik_network: external Traefik network name
# ------------------------------------------------------------------------------
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

# ------------------------------------------------------------------------------
# update_stack_name
# ------------------------------------------------------------------------------
# Replaces the stack name placeholder in swarm-stack.yml.
#
# Arguments:
#   $1 - stack_file: path to swarm-stack.yml
#   $2 - stack_name: the stack name (e.g., myapp)
# ------------------------------------------------------------------------------
update_stack_name() {
    local stack_file="$1"
    local stack_name="$2"

    # Use different sed syntax based on OS
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        sed -i '' "s|XXX_CHANGE_ME_STACK_NAME_XXX|$stack_name|g" "$stack_file"
    else
        # Linux
        sed -i "s|XXX_CHANGE_ME_STACK_NAME_XXX|$stack_name|g" "$stack_file"
    fi
}

# ------------------------------------------------------------------------------
# add_cognito_to_stack
# ------------------------------------------------------------------------------
# Injects AWS Cognito secret references into swarm-stack.yml by replacing
# ###COGNITO_*### placeholders. Uses python3 for reliable multi-line replace.
#
# Arguments:
#   $1 - stack_file: path to swarm-stack.yml
#   $2 - project_root: absolute path to project root
#   $3 - stack_name_upper: uppercase stack name for secret naming
#
# Environment:
#   COGNITO_CREATED_SECRETS - space-separated list of created secret names
#
# Returns:
#   0 on success, 1 on failure
# ------------------------------------------------------------------------------
add_cognito_to_stack() {
    local stack_file="$1"
    local project_root="$2"
    local stack_name_upper="$3"
    
    # Check if COGNITO_CREATED_SECRETS is set
    if [ -z "${COGNITO_CREATED_SECRETS}" ]; then
        echo "No Cognito secrets were created, skipping stack update"
        return 0
    fi
    
    # Check if Cognito configuration already exists
    if grep -q "COGNITO_USER_POOL_ID_FILE" "$stack_file"; then
        echo "Cognito configuration already present in stack file"
        return 0
    fi
    
    echo "Adding Cognito secrets to stack file..."
    
    # Get AWS_REGION from .env
    local aws_region=""
    if [ -f "${project_root}/.env" ]; then
        aws_region=$(grep -E "^AWS_REGION=" "${project_root}/.env" | head -n1 | cut -d'=' -f2-)
    fi
    
    # Initialize all placeholders as empty (will be replaced individually)
    local pool_id_secret="" pool_id_env="" pool_id_footer=""
    local client_id_secret="" client_id_env="" client_id_footer=""
    local access_key_secret="" access_key_env="" access_key_footer=""
    local secret_key_secret="" secret_key_env="" secret_key_footer=""
    local aws_region_env=""
    
    # Add AWS_REGION if found
    if [ -n "$aws_region" ]; then
        aws_region_env="      AWS_REGION: ${aws_region}"
    fi
    
    # Build content for each created secret
    for secret_name in $COGNITO_CREATED_SECRETS; do
        if echo "$secret_name" | grep -q "COGNITO_USER_POOL_ID"; then
            pool_id_secret="      - \"${secret_name}\""
            pool_id_env="      COGNITO_USER_POOL_ID_FILE: /run/secrets/${secret_name}"
            pool_id_footer="  \"${secret_name}\":
    external: true"
        elif echo "$secret_name" | grep -q "COGNITO_APP_CLIENT_ID"; then
            client_id_secret="      - \"${secret_name}\""
            client_id_env="      COGNITO_APP_CLIENT_ID_FILE: /run/secrets/${secret_name}"
            client_id_footer="  \"${secret_name}\":
    external: true"
        elif echo "$secret_name" | grep -q "AWS_ACCESS_KEY_ID"; then
            access_key_secret="      - \"${secret_name}\""
            access_key_env="      AWS_ACCESS_KEY_ID_FILE: /run/secrets/${secret_name}"
            access_key_footer="  \"${secret_name}\":
    external: true"
        elif echo "$secret_name" | grep -q "AWS_SECRET_ACCESS_KEY"; then
            secret_key_secret="      - \"${secret_name}\""
            secret_key_env="      AWS_SECRET_ACCESS_KEY_FILE: /run/secrets/${secret_name}"
            secret_key_footer="  \"${secret_name}\":
    external: true"
        fi
    done
    
    # Replace individual placeholders in stack file using Python (works everywhere, handles multi-line)
    # Only replace placeholders for secrets that were actually created (non-empty)
    python3 -c "
import sys
content = open('$stack_file', 'r').read()

# Only replace if value is not empty (secret was created)
if '''${aws_region_env}''':
    content = content.replace('###AWS_REGION_ENV###', '''${aws_region_env}''')
if '''${pool_id_secret}''':
    content = content.replace('###COGNITO_USER_POOL_ID_SECRET###', '''${pool_id_secret}''')
if '''${pool_id_env}''':
    content = content.replace('###COGNITO_USER_POOL_ID_ENV###', '''${pool_id_env}''')
if '''${pool_id_footer}''':
    content = content.replace('###COGNITO_USER_POOL_ID_FOOTER###', '''${pool_id_footer}''')
if '''${client_id_secret}''':
    content = content.replace('###COGNITO_APP_CLIENT_ID_SECRET###', '''${client_id_secret}''')
if '''${client_id_env}''':
    content = content.replace('###COGNITO_APP_CLIENT_ID_ENV###', '''${client_id_env}''')
if '''${client_id_footer}''':
    content = content.replace('###COGNITO_APP_CLIENT_ID_FOOTER###', '''${client_id_footer}''')
if '''${access_key_secret}''':
    content = content.replace('###AWS_ACCESS_KEY_ID_SECRET###', '''${access_key_secret}''')
if '''${access_key_env}''':
    content = content.replace('###AWS_ACCESS_KEY_ID_ENV###', '''${access_key_env}''')
if '''${access_key_footer}''':
    content = content.replace('###AWS_ACCESS_KEY_ID_FOOTER###', '''${access_key_footer}''')
if '''${secret_key_secret}''':
    content = content.replace('###AWS_SECRET_ACCESS_KEY_SECRET###', '''${secret_key_secret}''')
if '''${secret_key_env}''':
    content = content.replace('###AWS_SECRET_ACCESS_KEY_ENV###', '''${secret_key_env}''')
if '''${secret_key_footer}''':
    content = content.replace('###AWS_SECRET_ACCESS_KEY_FOOTER###', '''${secret_key_footer}''')

open('$stack_file', 'w').write(content)
"
    
    if [ $? -ne 0 ]; then
        echo "Failed to update stack file with Cognito configuration"
        return 1
    fi
    
    echo "Cognito secrets added to stack file"
    return 0
}

# ------------------------------------------------------------------------------
# backup_existing_files
# ------------------------------------------------------------------------------
# Creates timestamped backups of .env and swarm-stack.yml before modifying them.
#
# Arguments:
#   $1 - project_root: absolute path to project root
# ------------------------------------------------------------------------------
backup_existing_files() {
    local project_root="$1"
    local timestamp=$(date +%Y_%m_%d__%H_%M_%S)
    
    # Create backup directories
    mkdir -p "${project_root}/backup/env"
    mkdir -p "${project_root}/backup/swarm-stack-yml"
    
    if [ -f "${project_root}/.env" ]; then
        local backup_file="${project_root}/backup/env/.env.${timestamp}"
        cp "${project_root}/.env" "$backup_file"
        echo "Backed up .env to backup/env/.env.${timestamp}"
    fi
    
    if [ -f "${project_root}/swarm-stack.yml" ]; then
        local backup_file="${project_root}/backup/swarm-stack-yml/swarm-stack.yml.${timestamp}"
        cp "${project_root}/swarm-stack.yml" "$backup_file"
        echo "Backed up swarm-stack.yml to backup/swarm-stack-yml/swarm-stack.yml.${timestamp}"
    fi
}
# ------------------------------------------------------------------------------
# write_nginx_redirector_template
# ------------------------------------------------------------------------------
# Writes the nginx template consumed by the official nginx image for redirector
# profiles. Values stay in environment variables so server operators can change
# redirect targets and status codes from .env without rebuilding an image.
#
# Arguments:
#   $1 - project_root: absolute path to project root
# ------------------------------------------------------------------------------
write_nginx_redirector_template() {
    local project_root="$1"
    local generated_dir="${project_root}/generated/nginx"
    local template_file="${generated_dir}/default.conf.template"

    mkdir -p "$generated_dir"
    cat > "$template_file" <<'NGINX_REDIRECTOR_TEMPLATE'
server {
    listen 80;
    server_name _;

    location = /health {
        add_header Content-Type text/plain;
        return 200 'ok';
    }

    location / {
        return ${REDIRECT_STATUS_CODE} ${REDIRECT_TARGET_BASE_URL}${DOLLAR}request_uri;
    }
}
NGINX_REDIRECTOR_TEMPLATE
}
# ------------------------------------------------------------------------------
# build_nginx_stack_file
# ------------------------------------------------------------------------------
# Assembles an nginx-only swarm-stack.yml for deployment profiles that serve
# static content and do not need API, Redis, database, or Docker secrets.
#
# Arguments:
#   $1 - proxy_type: "traefik" or "none"
#   $2 - project_root: absolute path to project root
#   $3 - ssl_mode: "direct" or "proxy" for Traefik labels
# ------------------------------------------------------------------------------
build_nginx_stack_file() {
    local proxy_type="$1"
    local project_root="$2"
    local ssl_mode="${3:-direct}"
    local stack_role="${STACK_ROLE:-}"
    local modules_dir="${project_root}/setup/compose-modules/nginx"
    local snippets_dir="${modules_dir}/snippets"
    local output_file="${project_root}/swarm-stack.yml"
    local temp_nginx="${modules_dir}/nginx.temp.yml"
    local temp_footer="${modules_dir}/footer.temp.yml"

    echo "Building nginx-only swarm-stack.yml..."

    echo "# Generated by setup wizard - DO NOT EDIT MANUALLY" > "$output_file"
    echo "# Re-run setup wizard to regenerate" >> "$output_file"
    echo "" >> "$output_file"
    echo "services:" >> "$output_file"

    cp "${modules_dir}/nginx.template.yml" "$temp_nginx"

    if [ "$stack_role" = "redirector" ]; then
        write_nginx_redirector_template "$project_root"

        local redirector_env_snippet="${snippets_dir}/redirector.environment.yml"
        local redirector_configs_snippet="${snippets_dir}/redirector.configs.yml"
        _config_builder_sed_inplace "/###NGINX_ENV###/r $redirector_env_snippet" "$temp_nginx"
        _config_builder_sed_inplace "/###NGINX_CONFIGS###/r $redirector_configs_snippet" "$temp_nginx"
    fi
    _config_builder_sed_inplace '/###NGINX_ENV###/d' "$temp_nginx"
    _config_builder_sed_inplace '/###NGINX_CONFIGS###/d' "$temp_nginx"

    if [ "$proxy_type" = "traefik" ]; then
        local proxy_labels_snippet="${snippets_dir}/proxy-traefik-${ssl_mode}-ssl.labels.yml"
        if [ ! -f "$proxy_labels_snippet" ]; then
            proxy_labels_snippet="${snippets_dir}/proxy-traefik-direct-ssl.labels.yml"
        fi

        _config_builder_sed_inplace 's|###PROXY_NETWORK###|      - ${TRAEFIK_NETWORK}|' "$temp_nginx"
        _config_builder_sed_inplace "/###PROXY_LABELS###/r $proxy_labels_snippet" "$temp_nginx"
        _config_builder_sed_inplace '/###PROXY_LABELS###/d' "$temp_nginx"
        _config_builder_sed_inplace '/###PROXY_PORTS###/d' "$temp_nginx"
    else
        local proxy_ports_snippet="${snippets_dir}/proxy-none.ports.yml"
        _config_builder_sed_inplace "/###PROXY_PORTS###/r $proxy_ports_snippet" "$temp_nginx"
        _config_builder_sed_inplace '/###PROXY_PORTS###/d' "$temp_nginx"
        _config_builder_sed_inplace '/###PROXY_NETWORK###/d' "$temp_nginx"
        _config_builder_sed_inplace '/###PROXY_LABELS###/d' "$temp_nginx"
    fi

    apply_deployment_memory_limit_template \
        "$temp_nginx" \
        "${MEMORY_LIMIT:-unlimited}" || return 1
    cat "$temp_nginx" >> "$output_file"
    rm -f "$temp_nginx"

    cp "${modules_dir}/footer.yml" "$temp_footer"
    if [ "$stack_role" = "redirector" ]; then
        local redirector_footer_configs_snippet="${snippets_dir}/redirector.footer-configs.yml"
        _config_builder_sed_inplace "/###NGINX_CONFIG_DEFINITIONS###/r $redirector_footer_configs_snippet" "$temp_footer"
    fi
    _config_builder_sed_inplace '/###NGINX_CONFIG_DEFINITIONS###/d' "$temp_footer"
    if [ "$proxy_type" = "traefik" ]; then
        local traefik_network="${TRAEFIK_NETWORK:-traefik-public}"
        local traefik_network_block="${modules_dir}/traefik-network.temp.yml"
        printf '  %s:\n    external: true\n' "$traefik_network" > "$traefik_network_block"
        _config_builder_sed_inplace "/###TRAEFIK_NETWORK###/r $traefik_network_block" "$temp_footer"
        rm -f "$traefik_network_block"
    fi
    _config_builder_sed_inplace '/###TRAEFIK_NETWORK###/d' "$temp_footer"
    cat "$temp_footer" >> "$output_file"
    rm -f "$temp_footer"

    echo "nginx-only swarm-stack.yml created"
}
