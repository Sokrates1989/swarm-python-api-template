#!/bin/bash
# ==============================================================================
# deployment-field-help.sh - Shared deployment value guidance
# ==============================================================================
#
# Provides one source of operator guidance for both terminal prompts and the
# commented public .env editor. Site profiles own capabilities and defaults;
# this module documents the shared value shapes accepted by deployment tooling.
#
# Dependencies:
#   - setup/modules/deployment-memory-policy.sh for memory-limit guidance.
# ==============================================================================

# Guard against multiple sourcing.
if [ -n "${_DEPLOYMENT_FIELD_HELP_LOADED:-}" ]; then
    return 0 2>/dev/null || true
fi
_DEPLOYMENT_FIELD_HELP_LOADED=1

PUBLIC_DOMAIN_CREATE_INFO_URL="https://wiki.fe-wi.com/en/deployment/create-subdomain"

# ------------------------------------------------------------------------------
# deployment_field_validation_kind
# ------------------------------------------------------------------------------
# Maps a generated environment key to the shared value validator used by its
# guided equivalent. Unknown/profile-owned fields intentionally return `any`.
#
# Arguments:
#   $1 - Public deployment environment key.
#
# Outputs:
#   Validation-kind identifier.
# ------------------------------------------------------------------------------
deployment_field_validation_kind() {
    local key="$1"

    case "$key" in
        STACK_NAME|TRAEFIK_NETWORK|TRAEFIK_CONSTRAINT_LABEL|\
        TRAEFIK_CERT_RESOLVER|INTERNAL_NETWORK)
            echo "name"
            ;;
        DOMAIN|WEB_DOMAIN|PGADMIN_DOMAIN|MONGO_EXPRESS_URL)
            echo "domain"
            ;;
        API_BASE_URL|WEB_BASE_URL|KEYCLOAK_BASE_URL|KEYCLOAK_ISSUER_URL|\
        REDIRECT_TARGET_BASE_URL)
            echo "url"
            ;;
        DB_HOST)
            echo "host"
            ;;
        DB_NAME|DB_USER|KEYCLOAK_REALM|KEYCLOAK_AUDIENCE|\
        KEYCLOAK_FRONTEND_CLIENT_ID|KEYCLOAK_BACKEND_CLIENT_ID|\
        MONGO_EXPRESS_USERNAME)
            echo "identifier"
            ;;
        KEYCLOAK_REALM_DISPLAY_NAME)
            echo "nonempty"
            ;;
        IMAGE_NAME|WEB_IMAGE_NAME)
            echo "image"
            ;;
        IMAGE_VERSION|WEB_IMAGE_VERSION)
            echo "tag"
            ;;
        API_REPLICAS|WEB_REPLICAS|NGINX_REPLICAS)
            echo "positive"
            ;;
        PGADMIN_REPLICAS|MONGO_EXPRESS_REPLICAS|REDIS_REPLICAS)
            echo "integer"
            ;;
        MEMORY_LIMIT|WEB_MEMORY_LIMIT)
            echo "memory"
            ;;
        API_PUBLISHED_PORT|WEB_PUBLISHED_PORT|PGADMIN_PUBLISHED_PORT|\
        PUBLISHED_PORT|DB_PORT)
            echo "port"
            ;;
        DATA_ROOT)
            echo "path"
            ;;
        PGADMIN_EMAIL)
            echo "email"
            ;;
        *)
            echo "any"
            ;;
    esac
}

# ------------------------------------------------------------------------------
# _deployment_field_specific_help
# ------------------------------------------------------------------------------
# Returns guidance owned by a particular deployment environment field.
#
# Arguments:
#   $1 - Environment key or prompt target variable.
#
# Outputs:
#   Guidance for a recognized field.
#
# Returns:
#   0 for a recognized field; otherwise 1.
# ------------------------------------------------------------------------------
_deployment_field_specific_help() {
    local key="$1"

    case "$key" in
        DB_MODE)
            echo "Choose a database mode allowed by the selected site profile: local, external, or none."
            return 0
            ;;
        PROXY_TYPE)
            echo "Use traefik for reverse-proxy routing/HTTPS or none for direct published ports."
            return 0
            ;;
        SSL_MODE)
            echo "Use letsencrypt when Traefik obtains certificates, or proxy when TLS terminates upstream."
            return 0
            ;;
        PGADMIN_ENABLED|WEB_ENABLED|KEYCLOAK_REALM_ENABLED|\
        KEYCLOAK_REGISTRATION_ALLOWED|KEYCLOAK_RESET_PASSWORD_ALLOWED|\
        KEYCLOAK_REMEMBER_ME|KEYCLOAK_VERIFY_EMAIL|\
        KEYCLOAK_LOGIN_WITH_EMAIL_ALLOWED|\
        KEYCLOAK_BOOTSTRAP_TEST_USERS_ENABLED)
            echo "Use true or false. Keep dependent replica/domain fields consistent when enabling a service."
            return 0
            ;;
        DEPLOYMENT_PROFILE_ID|PROFILE_SCHEMA_VERSION|APP_ID|APP_ENVIRONMENT|\
        APP_PROFILE|BACKEND_APP_ID|BACKEND_DATA_PROFILE|AUTH_PROVIDER|\
        STACK_FAMILY|STACK_ROLE|PRIMARY_SERVICE|DB_TYPE)
            echo "Profile-owned identity value; keep the generated value unchanged."
            return 0
            ;;
        CORS_ORIGINS)
            echo "Comma-separated allowed browser origins, each including its http:// or https:// scheme."
            return 0
            ;;
        KEYCLOAK_REALM_DISPLAY_NAME)
            echo "Human-readable realm name shown on Keycloak login and administration screens."
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

# ------------------------------------------------------------------------------
# _deployment_validation_help
# ------------------------------------------------------------------------------
# Returns shared accepted-value guidance for one validation kind.
#
# Arguments:
#   $1 - Validation-kind identifier.
#
# Outputs:
#   Guidance for the validation kind, when available.
#
# Returns:
#   0 after recognizing the validation kind; otherwise 1.
# ------------------------------------------------------------------------------
_deployment_validation_help() {
    local validation_kind="$1"

    case "$validation_kind" in
        domain)
            echo "Public DNS name without a scheme. Creation guide: ${PUBLIC_DOMAIN_CREATE_INFO_URL}"
            ;;
        memory)
            print_deployment_memory_limit_help
            ;;
        name)
            echo "Use lowercase letters, digits, dots, underscores, or hyphens; start with a letter or digit."
            ;;
        host)
            echo "Use a resolvable hostname, IP address, or Docker service name without a URL scheme."
            ;;
        identifier)
            echo "Use letters, digits, dots, underscores, or hyphens; start with a letter or digit."
            ;;
        tag)
            echo "Use a Docker tag such as 1.2.3; mutable tags are rejected when the profile forbids them."
            ;;
        url)
            echo "Use a complete http:// or https:// URL without spaces."
            ;;
        integer)
            echo "Use a whole number of zero or greater."
            ;;
        positive)
            echo "Use a whole number of one or greater."
            ;;
        port)
            echo "Use a TCP port number from 1 through 65535."
            ;;
        image)
            echo "Use a Docker repository without a tag, for example username/image-name."
            ;;
        path)
            echo "Use a specific absolute host path; never use / as the data root."
            ;;
        email)
            echo "Use a complete email address such as admin@example.com."
            ;;
        nonempty)
            echo "A non-empty value is required."
            ;;
        any)
            echo "Site-profile deployment setting; preserve the generated default unless you intentionally change it."
            ;;
        *)
            return 1
            ;;
    esac
}

# ------------------------------------------------------------------------------
# deployment_field_help_text
# ------------------------------------------------------------------------------
# Returns concise shared guidance for one environment key and validation kind.
# Field-specific guidance takes precedence over generic value-shape help.
#
# Arguments:
#   $1 - Environment key or prompt target variable.
#   $2 - Validation kind.
#
# Outputs:
#   Zero or more guidance lines.
#
# Returns:
#   0 after emitting available guidance; unknown fields emit nothing.
# ------------------------------------------------------------------------------
deployment_field_help_text() {
    local key="$1"
    local validation_kind="$2"

    if _deployment_field_specific_help "$key"; then
        return 0
    fi
    _deployment_validation_help "$validation_kind" || true
    return 0
}

# ------------------------------------------------------------------------------
# print_deployment_field_help
# ------------------------------------------------------------------------------
# Prints shared prompt guidance. Domain prompts already include the shared Wiki
# link in their question label, so prompt context suppresses a duplicate line.
#
# Arguments:
#   $1 - Environment key or prompt target variable.
#   $2 - Validation kind.
#   $3 - Context: prompt or file.
# ------------------------------------------------------------------------------
print_deployment_field_help() {
    local key="$1"
    local validation_kind="$2"
    local context="${3:-prompt}"

    if [ "$context" = "prompt" ] && [ "$validation_kind" = "domain" ]; then
        return 0
    fi
    deployment_field_help_text "$key" "$validation_kind"
}

# ------------------------------------------------------------------------------
# annotate_deployment_environment_file
# ------------------------------------------------------------------------------
# Adds shared field guidance before every assignment in a freshly generated
# public environment without changing values or evaluating dotenv content.
#
# Arguments:
#   $1 - Existing generated public environment file.
#
# Returns:
#   0 after atomic replacement; otherwise 1.
# ------------------------------------------------------------------------------
annotate_deployment_environment_file() {
    local environment_file="$1"
    local temporary=""
    local line=""
    local key=""
    local validation_kind=""
    local help_text=""
    local help_line=""

    [ -f "$environment_file" ] || {
        echo "[ERROR] Public environment is missing: ${environment_file}" >&2
        return 1
    }
    temporary="$(mktemp "${environment_file}.help.XXXXXX")" || return 1
    while IFS= read -r line || [ -n "$line" ]; do
        if [[ "$line" =~ ^([A-Z][A-Z0-9_]*)= ]]; then
            key="${BASH_REMATCH[1]}"
            validation_kind="$(deployment_field_validation_kind "$key")"
            help_text="$(deployment_field_help_text "$key" "$validation_kind")"
            if [ -n "$help_text" ]; then
                while IFS= read -r help_line; do
                    echo "# ${help_line}" >> "$temporary"
                done <<< "$help_text"
            fi
        fi
        echo "$line" >> "$temporary"
    done < "$environment_file"
    chmod 600 "$temporary"
    mv -f "$temporary" "$environment_file"
}
