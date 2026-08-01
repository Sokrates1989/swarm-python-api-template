#!/bin/bash
# ==============================================================================
# deployment-environment-format.sh - Human-readable public .env formatting
# ==============================================================================
#
# Rewrites a freshly generated deployment environment into stable sections
# matching the shared site-profile concepts. Assignment values are never
# evaluated or changed. Repeated field guidance is consolidated per section so
# guided prompts and the editable file continue to use the same help catalog.
#
# Dependencies:
#   - deployment-memory-policy.sh for memory guidance.
#   - deployment-field-help.sh for accepted-value guidance.
# ==============================================================================

# Guard against multiple sourcing.
if [ -n "${_DEPLOYMENT_ENVIRONMENT_FORMAT_LOADED:-}" ]; then
    return 0 2>/dev/null || true
fi
_DEPLOYMENT_ENVIRONMENT_FORMAT_LOADED=1

DEPLOYMENT_ENVIRONMENT_FORMAT_DIR="$(
    cd "$(dirname "${BASH_SOURCE[0]}")" && pwd
)"
source "${DEPLOYMENT_ENVIRONMENT_FORMAT_DIR}/deployment-memory-policy.sh"
source "${DEPLOYMENT_ENVIRONMENT_FORMAT_DIR}/deployment-field-help.sh"

#
# Canonical section order.
# The names correspond to site-profile responsibilities rather than any app.
#
DEPLOYMENT_ENVIRONMENT_SECTION_ORDER="
profile
stack
routing
authentication
database
networking
ports
backend
storage
database_admin
web
redirector
secrets
advanced
"

# ------------------------------------------------------------------------------
# deployment_environment_section_id
# ------------------------------------------------------------------------------
# Maps one public environment key to its site-profile responsibility.
#
# Arguments:
#   $1 - Uppercase dotenv assignment key.
#
# Outputs:
#   Canonical section identifier.
# ------------------------------------------------------------------------------
deployment_environment_section_id() {
    local key="$1"

    case "$key" in
        *_PASSWORD_FILE|*_SECRET_FILE|*_TOKEN_FILE|*_KEY_FILE|*_AUTH_FILE|\
        SECRETS_PREFIX|SECRET_PREFIX)
            echo "secrets"
            ;;
        PROFILE_SCHEMA_VERSION|DEPLOYMENT_PROFILE_ID|APP_ID|APP_ENVIRONMENT|\
        APP_PROFILE|BACKEND_APP_ID|BACKEND_DATA_PROFILE)
            echo "profile"
            ;;
        STACK_NAME|STACK_FAMILY|STACK_ROLE|PRIMARY_SERVICE)
            echo "stack"
            ;;
        AUTH_PROVIDER|KEYCLOAK_*|COGNITO_*)
            echo "authentication"
            ;;
        API_BASE_URL|API_URL|DOMAIN|WEB_BASE_URL|WEB_DOMAIN|CORS_ORIGINS|\
        INTERNAL_URL)
            echo "routing"
            ;;
        DB_*|POSTGRES_*|MONGODB_*|NEO4J_*)
            echo "database"
            ;;
        PROXY_TYPE|SSL_MODE|TRAEFIK_*|INTERNAL_NETWORK)
            echo "networking"
            ;;
        API_PUBLISHED_PORT|WEB_PUBLISHED_PORT|PGADMIN_PUBLISHED_PORT|\
        PUBLISHED_PORT)
            echo "ports"
            ;;
        IMAGE_NAME|IMAGE_VERSION|API_REPLICAS|NGINX_REPLICAS|MEMORY_LIMIT|\
        PORT|PYTHON_VERSION|DEBUG|DEBUG_ENABLED)
            echo "backend"
            ;;
        DATA_ROOT|REDIS_*)
            echo "storage"
            ;;
        PGADMIN_*|MONGO_EXPRESS_*)
            echo "database_admin"
            ;;
        WEB_*)
            echo "web"
            ;;
        REDIRECT_*)
            echo "redirector"
            ;;
        *)
            echo "advanced"
            ;;
    esac
}

# ------------------------------------------------------------------------------
# deployment_environment_section_title
# ------------------------------------------------------------------------------
# Returns the human-readable title for one canonical section.
#
# Arguments:
#   $1 - Canonical section identifier.
#
# Outputs:
#   Section title.
# ------------------------------------------------------------------------------
deployment_environment_section_title() {
    case "$1" in
        profile) echo "Deployment identity" ;;
        stack) echo "Docker Swarm topology" ;;
        routing) echo "Routing and browser access" ;;
        authentication) echo "Authentication" ;;
        database) echo "Database" ;;
        networking) echo "Proxy, TLS, and networking" ;;
        ports) echo "Published ports" ;;
        backend) echo "Backend service" ;;
        storage) echo "Storage and data services" ;;
        database_admin) echo "Database management" ;;
        web) echo "WebApp service" ;;
        redirector) echo "Redirector service" ;;
        secrets) echo "Docker secret references" ;;
        advanced) echo "Additional profile settings" ;;
    esac
}

# ------------------------------------------------------------------------------
# deployment_environment_section_description
# ------------------------------------------------------------------------------
# Returns concise semantic context for one canonical section.
#
# Arguments:
#   $1 - Canonical section identifier.
#
# Outputs:
#   One or more description lines.
# ------------------------------------------------------------------------------
deployment_environment_section_description() {
    case "$1" in
        profile)
            echo "Identifies the selected site profile and application runtime."
            ;;
        stack)
            echo "Names the Swarm stack and its primary service responsibility."
            ;;
        routing)
            echo "Defines public or internal endpoints and browser-origin policy."
            ;;
        authentication)
            echo "Defines the authentication realm, clients, audience, and login policy."
            ;;
        database)
            echo "Selects the database engine, deployment mode, and connection identity."
            echo "Database passwords remain Docker secrets and never belong here."
            ;;
        networking)
            echo "Controls reverse-proxy routing, TLS ownership, and overlay networks."
            ;;
        ports)
            echo "Configures optional direct host ports for published services."
            ;;
        backend)
            echo "Selects the backend image and its runtime resource policy."
            ;;
        storage)
            echo "Configures persistent host storage and supporting data services."
            ;;
        database_admin)
            echo "Configures an optional profile-declared database administration UI."
            ;;
        web)
            echo "Selects the optional WebApp image and runtime resource policy."
            ;;
        redirector)
            echo "Configures the target and HTTP behavior of a redirect-only service."
            ;;
        secrets)
            echo "Contains Docker secret names or mounted file paths only."
            echo "Never enter a password, token, private key, or client-secret value here."
            ;;
        advanced)
            echo "Contains additional public settings declared by the selected profile."
            ;;
    esac
}

# ------------------------------------------------------------------------------
# _cleanup_deployment_environment_format_files
# ------------------------------------------------------------------------------
# Removes known sibling working files created by the formatter.
#
# Arguments:
#   $1 - Exact temporary base path returned by mktemp.
#
# Returns:
#   0 after attempting all removals.
# ------------------------------------------------------------------------------
_cleanup_deployment_environment_format_files() {
    local temporary="$1"
    local section=""

    rm -f "$temporary"
    while IFS= read -r section; do
        [ -n "$section" ] || continue
        rm -f "${temporary}.${section}"
    done <<< "$DEPLOYMENT_ENVIRONMENT_SECTION_ORDER"
}

# ------------------------------------------------------------------------------
# _initialize_deployment_environment_section_files
# ------------------------------------------------------------------------------
# Creates empty sibling files for every canonical section.
#
# Arguments:
#   $1 - Exact temporary base path returned by mktemp.
#
# Returns:
#   0 after creating all files; otherwise nonzero.
# ------------------------------------------------------------------------------
_initialize_deployment_environment_section_files() {
    local temporary="$1"
    local section=""

    while IFS= read -r section; do
        [ -n "$section" ] || continue
        : > "${temporary}.${section}" || return 1
    done <<< "$DEPLOYMENT_ENVIRONMENT_SECTION_ORDER"
}

# ------------------------------------------------------------------------------
# _collect_deployment_environment_assignments
# ------------------------------------------------------------------------------
# Validates generated dotenv syntax and routes assignments to section files.
# Existing generated comments are replaced by canonical documentation.
#
# Arguments:
#   $1 - Source environment file.
#   $2 - Temporary base path.
#   $3 - Caller-owned result variable for the generator header.
#   $4 - Caller-owned result variable for the profile header.
#
# Returns:
#   0 after collecting unique assignments; otherwise 1.
# ------------------------------------------------------------------------------
_collect_deployment_environment_assignments() {
    local source_file="$1"
    local temporary="$2"
    local generator_header_target="$3"
    local profile_header_target="$4"
    local line=""
    local key=""
    local section=""
    local collected_generator_header=""
    local collected_profile_header=""
    local -A seen_keys=()

    while IFS= read -r line || [ -n "$line" ]; do
        if [[ "$line" =~ ^([A-Z][A-Z0-9_]*)= ]]; then
            key="${BASH_REMATCH[1]}"
            if [ -n "${seen_keys[$key]+present}" ]; then
                echo "[ERROR] Duplicate public environment key: ${key}" >&2
                return 1
            fi
            seen_keys["$key"]=1
            section="$(deployment_environment_section_id "$key")"
            printf '%s\n' "$line" >> "${temporary}.${section}"
        elif [[ "$line" == "# Generated by "* ]]; then
            collected_generator_header="$line"
        elif [[ "$line" == "# Deployment profile:"* ]]; then
            collected_profile_header="$line"
        elif [ -n "$line" ] && [[ "$line" != \#* ]]; then
            echo "[ERROR] Unsupported generated environment line: ${line}" >&2
            return 1
        fi
    done < "$source_file"
    printf -v "$generator_header_target" '%s' "$collected_generator_header"
    printf -v "$profile_header_target" '%s' "$collected_profile_header"
}

# ------------------------------------------------------------------------------
# _write_deployment_environment_section_help
# ------------------------------------------------------------------------------
# Consolidates shared field guidance into unique accepted-value notes.
#
# Arguments:
#   $1 - Output environment file.
#   $2 - Section assignment file.
#
# Returns:
#   0 after writing all unique notes.
# ------------------------------------------------------------------------------
_write_deployment_environment_section_help() {
    local output_file="$1"
    local section_file="$2"
    local line=""
    local key=""
    local validation_kind=""
    local help_id=""
    local help_text=""
    local help_line=""
    local first_help_line="false"
    local wrote_heading="false"
    local -A seen_help=()

    while IFS= read -r line || [ -n "$line" ]; do
        key="${line%%=*}"
        validation_kind="$(deployment_field_validation_kind "$key")"
        help_id="$(deployment_field_help_id "$key" "$validation_kind")"
        [ -z "${seen_help[$help_id]+present}" ] || continue
        seen_help["$help_id"]=1
        help_text="$(deployment_field_help_text "$key" "$validation_kind")"
        [ -n "$help_text" ] || continue
        if [ "$wrote_heading" = "false" ]; then
            echo "#" >> "$output_file"
            echo "# Accepted values:" >> "$output_file"
            wrote_heading="true"
        fi
        first_help_line="true"
        while IFS= read -r help_line; do
            if [ "$first_help_line" = "true" ]; then
                echo "# - ${help_line}" >> "$output_file"
                first_help_line="false"
            else
                echo "#   ${help_line}" >> "$output_file"
            fi
        done <<< "$help_text"
    done < "$section_file"
}

# ------------------------------------------------------------------------------
# _write_deployment_environment_section
# ------------------------------------------------------------------------------
# Writes one non-empty formatted section and its original assignments.
#
# Arguments:
#   $1 - Output environment file.
#   $2 - Canonical section identifier.
#   $3 - Section assignment file.
#
# Returns:
#   0 after writing or skipping the section.
# ------------------------------------------------------------------------------
_write_deployment_environment_section() {
    local output_file="$1"
    local section="$2"
    local section_file="$3"
    local title=""
    local description_line=""
    local assignment=""

    [ -s "$section_file" ] || return 0
    title="$(deployment_environment_section_title "$section")"
    echo "" >> "$output_file"
    echo "# ==============================================================================" >> "$output_file"
    echo "# ${title}" >> "$output_file"
    echo "# ==============================================================================" >> "$output_file"
    while IFS= read -r description_line; do
        echo "# ${description_line}" >> "$output_file"
    done < <(deployment_environment_section_description "$section")
    _write_deployment_environment_section_help "$output_file" "$section_file"
    echo "#" >> "$output_file"
    while IFS= read -r assignment || [ -n "$assignment" ]; do
        printf '%s\n' "$assignment" >> "$output_file"
    done < "$section_file"
}

# ------------------------------------------------------------------------------
# format_deployment_environment_file
# ------------------------------------------------------------------------------
# Atomically restructures a generated public .env into readable profile-neutral
# sections without evaluating or changing assignment values.
#
# Arguments:
#   $1 - Existing generated public environment file.
#
# Returns:
#   0 after mode-0600 replacement; otherwise 1 with the source file retained.
# ------------------------------------------------------------------------------
format_deployment_environment_file() {
    local environment_file="$1"
    local temporary=""
    local section=""
    local generator_header=""
    local profile_header=""

    [ -f "$environment_file" ] || {
        echo "[ERROR] Public environment is missing: ${environment_file}" >&2
        return 1
    }
    temporary="$(mktemp "${environment_file}.format.XXXXXX")" || return 1
    _initialize_deployment_environment_section_files "$temporary" || {
        _cleanup_deployment_environment_format_files "$temporary"
        return 1
    }
    if ! _collect_deployment_environment_assignments \
        "$environment_file" \
        "$temporary" \
        generator_header \
        profile_header; then
        _cleanup_deployment_environment_format_files "$temporary"
        return 1
    fi
    echo "${generator_header:-# Generated public deployment environment.}" \
        > "$temporary"
    [ -z "$profile_header" ] || echo "$profile_header" >> "$temporary"
    echo "#" >> "$temporary"
    echo "# Public configuration only. Keep passwords, tokens, private keys," \
        >> "$temporary"
    echo "# and client-secret values in Docker secrets, never in this file." \
        >> "$temporary"
    while IFS= read -r section; do
        [ -n "$section" ] || continue
        _write_deployment_environment_section \
            "$temporary" \
            "$section" \
            "${temporary}.${section}" || {
            _cleanup_deployment_environment_format_files "$temporary"
            return 1
        }
    done <<< "$DEPLOYMENT_ENVIRONMENT_SECTION_ORDER"
    chmod 600 "$temporary" || {
        _cleanup_deployment_environment_format_files "$temporary"
        return 1
    }
    while IFS= read -r section; do
        [ -n "$section" ] || continue
        rm -f "${temporary}.${section}"
    done <<< "$DEPLOYMENT_ENVIRONMENT_SECTION_ORDER"
    if ! mv -f "$temporary" "$environment_file"; then
        _cleanup_deployment_environment_format_files "$temporary"
        return 1
    fi
}
