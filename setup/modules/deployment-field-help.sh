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
        DOMAIN|WEB_DOMAIN|API_URL|INTERNAL_URL|PGADMIN_DOMAIN|PGADMIN_URL|\
        MONGO_EXPRESS_URL)
            echo "domain"
            ;;
        API_BASE_URL|WEB_BASE_URL|KEYCLOAK_BASE_URL|KEYCLOAK_ISSUER_URL|\
        KEYCLOAK_SERVER_URL|KEYCLOAK_JWKS_URL|REDIRECT_TARGET_BASE_URL|\
        REDIS_URL)
            echo "url"
            ;;
        DB_HOST|POSTGRES_HOST|MONGODB_HOST|NEO4J_HOST|REDIS_HOST|\
        KEYCLOAK_SMTP_HOST)
            echo "host"
            ;;
        DB_NAME|DB_USER|POSTGRES_DB|POSTGRES_USER|MONGODB_DB|MONGODB_USER|\
        KEYCLOAK_REALM|KEYCLOAK_AUDIENCE|\
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
        API_REPLICAS|WEB_REPLICAS|NGINX_REPLICAS|POSTGRES_REPLICAS|\
        REDIS_REPLICAS)
            echo "positive"
            ;;
        PGADMIN_REPLICAS|MONGO_EXPRESS_REPLICAS)
            echo "integer"
            ;;
        MEMORY_LIMIT|WEB_MEMORY_LIMIT)
            echo "memory"
            ;;
        API_PUBLISHED_PORT|WEB_PUBLISHED_PORT|PGADMIN_PUBLISHED_PORT|\
        PUBLISHED_PORT|PORT|DB_PORT|POSTGRES_PORT|MONGODB_PORT|NEO4J_PORT|\
        REDIS_PORT|KEYCLOAK_SMTP_PORT)
            echo "port"
            ;;
        DATA_ROOT)
            echo "path"
            ;;
        PGADMIN_EMAIL|KEYCLOAK_SMTP_FROM|KEYCLOAK_SMTP_REPLY_TO|\
        KEYCLOAK_SMTP_ENVELOPE_FROM)
            echo "email"
            ;;
        *)
            echo "any"
            ;;
    esac
}

# ------------------------------------------------------------------------------
# _deployment_field_specific_help_id
# ------------------------------------------------------------------------------
# Classifies fields whose guidance is more specific than their value shape.
#
# Arguments:
#   $1 - Environment key or prompt target variable.
#
# Outputs:
#   Stable help identifier for a recognized field group.
#
# Returns:
#   0 for a recognized field; otherwise 1.
# ------------------------------------------------------------------------------
_deployment_field_specific_help_id() {
    local key="$1"

    case "$key" in
        DB_MODE)
            echo "database-mode"
            ;;
        PROXY_TYPE)
            echo "proxy-type"
            ;;
        SSL_MODE)
            echo "ssl-mode"
            ;;
        PGADMIN_ENABLED|WEB_ENABLED|KEYCLOAK_REALM_ENABLED|\
        KEYCLOAK_REGISTRATION_ALLOWED|KEYCLOAK_RESET_PASSWORD_ALLOWED|\
        KEYCLOAK_REMEMBER_ME|KEYCLOAK_VERIFY_EMAIL|\
        KEYCLOAK_LOGIN_WITH_EMAIL_ALLOWED|\
        KEYCLOAK_INTERNATIONALIZATION_ENABLED|\
        KEYCLOAK_EMAIL_SENDER_ENABLED|KEYCLOAK_SMTP_STARTTLS|\
        KEYCLOAK_SMTP_SSL|KEYCLOAK_SMTP_AUTH|\
        KEYCLOAK_BOOTSTRAP_TEST_USERS_ENABLED)
            echo "boolean-toggle"
            ;;
        KEYCLOAK_BOOTSTRAP_USERS_CLEANUP_PENDING|\
        KEYCLOAK_BOOTSTRAP_USERS_CLEANUP_NAMES)
            echo "operator-cleanup-state"
            ;;
        DEPLOYMENT_PROFILE_ID|PROFILE_SCHEMA_VERSION|APP_ID|APP_ENVIRONMENT|\
        APP_PROFILE|BACKEND_APP_ID|BACKEND_DATA_PROFILE|AUTH_PROVIDER|\
        STACK_FAMILY|STACK_ROLE|PRIMARY_SERVICE|DB_TYPE)
            echo "profile-owned"
            ;;
        *_PASSWORD_FILE|*_SECRET_FILE|*_TOKEN_FILE|*_KEY_FILE|*_AUTH_FILE)
            echo "secret-file-reference"
            ;;
        SECRETS_PREFIX|SECRET_PREFIX)
            echo "secret-prefix"
            ;;
        CORS_ORIGINS)
            echo "cors-origins"
            ;;
        KEYCLOAK_REALM_DISPLAY_NAME)
            echo "realm-display-name"
            ;;
        KEYCLOAK_LOGIN_THEME|KEYCLOAK_ACCOUNT_THEME|KEYCLOAK_ADMIN_THEME|\
        KEYCLOAK_EMAIL_THEME)
            echo "keycloak-theme"
            ;;
        KEYCLOAK_SUPPORTED_LOCALES|KEYCLOAK_DEFAULT_LOCALE)
            echo "keycloak-locales"
            ;;
        KEYCLOAK_SMTP_FROM_DISPLAY_NAME|KEYCLOAK_SMTP_REPLY_TO|\
        KEYCLOAK_SMTP_REPLY_TO_DISPLAY_NAME|KEYCLOAK_SMTP_ENVELOPE_FROM|\
        KEYCLOAK_SMTP_USERNAME)
            echo "keycloak-smtp-public"
            ;;
        *)
            return 1
            ;;
    esac
}

# ------------------------------------------------------------------------------
# _deployment_field_specific_help
# ------------------------------------------------------------------------------
# Returns guidance owned by a particular deployment field group.
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
    local help_id=""

    help_id="$(_deployment_field_specific_help_id "$key")" || return 1
    case "$help_id" in
        database-mode)
            echo "Choose a database mode allowed by the selected site profile: local, external, or none."
            ;;
        proxy-type)
            echo "Use traefik for reverse-proxy routing/HTTPS or none for direct published ports."
            ;;
        ssl-mode)
            echo "Use letsencrypt when Traefik obtains certificates, or proxy when TLS terminates upstream."
            ;;
        boolean-toggle)
            echo "Use true or false. Keep dependent replica/domain fields consistent when enabling a service."
            ;;
        operator-cleanup-state)
            echo "Tool-managed reminder state for temporary users created by bootstrap; acknowledge cleanup through the main menu instead of editing this value."
            ;;
        profile-owned)
            echo "Profile-owned identity value; keep the generated value unchanged."
            ;;
        secret-file-reference)
            echo "Docker secret mount path only; keep the generated reference and never enter the secret value here."
            ;;
        secret-prefix)
            echo "Docker secret naming prefix; use only letters, digits, and underscores."
            ;;
        cors-origins)
            echo "Comma-separated allowed browser origins, each including its http:// or https:// scheme."
            ;;
        realm-display-name)
            echo "Human-readable realm name shown on Keycloak login and administration screens."
            ;;
        keycloak-theme)
            echo "Installed Keycloak theme name, or default to inherit the server default; live bootstrap verifies custom names."
            ;;
        keycloak-locales)
            echo "Supported locales are comma-separated language tags; the default locale must appear in that list."
            ;;
        keycloak-smtp-public)
            echo "Public realm SMTP metadata only; <empty> explicitly clears an optional profile default. Never put the SMTP password here; bootstrap requests it without echo."
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
# deployment_field_help_id
# ------------------------------------------------------------------------------
# Returns a stable identifier used to consolidate repeated field guidance in
# generated environment sections.
#
# Arguments:
#   $1 - Environment key or prompt target variable.
#   $2 - Validation kind.
#
# Outputs:
#   Field-specific or validation-kind help identifier.
# ------------------------------------------------------------------------------
deployment_field_help_id() {
    local key="$1"
    local validation_kind="$2"
    local specific_id=""

    if specific_id="$(_deployment_field_specific_help_id "$key")"; then
        echo "field:${specific_id}"
    else
        echo "validation:${validation_kind}"
    fi
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
