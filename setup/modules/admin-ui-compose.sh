#!/bin/bash
# ==============================================================================
# admin-ui-compose.sh - Database-management Compose service adapter
# ==============================================================================
#
# Renders and appends the profile-declared pgAdmin or Mongo Express service.
# The shared stack builder delegates here so database-management differences
# remain capability driven without growing its primary assembly responsibility.
#
# Dependencies:
#   - _config_builder_sed_inplace from config-builder.sh at invocation time
#   - setup/compose-modules database-management templates and label snippets
# ==============================================================================

# Guard against multiple sourcing.
if [ -n "${_ADMIN_UI_COMPOSE_LOADED:-}" ]; then
    return 0 2>/dev/null || true
fi
_ADMIN_UI_COMPOSE_LOADED=1

# ------------------------------------------------------------------------------
# _prepare_admin_ui_traefik_labels
# ------------------------------------------------------------------------------
# Renders the shared Traefik label adapter for one database-management service.
#
# Arguments:
#   $1 - project_root: absolute repository root.
#   $2 - admin_ui_type: pgadmin or mongo-express.
#   $3 - ssl_mode: letsencrypt/direct or proxy.
#   $4 - destination: process-specific label snippet path.
#
# Returns:
#   0 after resolving all service-type tokens; otherwise 1.
# ------------------------------------------------------------------------------
_prepare_admin_ui_traefik_labels() {
    local project_root="$1"
    local admin_ui_type="$2"
    local ssl_mode="$3"
    local destination="$4"
    local suffix=""
    local domain_expression=""
    local container_port=""
    local label_mode="direct"
    local source_snippet=""

    case "$admin_ui_type" in
        pgadmin)
            suffix="pgadmin"
            domain_expression='${PGADMIN_URL}'
            container_port="5050"
            ;;
        mongo-express)
            suffix="mongoexpress"
            domain_expression='${MONGO_EXPRESS_URL}'
            container_port="8081"
            ;;
        *) return 1 ;;
    esac
    [ "$ssl_mode" = "proxy" ] && label_mode="proxy"
    source_snippet="${project_root}/setup/compose-modules/snippets/admin-traefik-${label_mode}.labels.yml"
    [ -f "$source_snippet" ] || return 1
    cp "$source_snippet" "$destination"
    _config_builder_sed_inplace \
        "s|XXX_ADMIN_SUFFIX|${suffix}|g" \
        "$destination"
    _config_builder_sed_inplace \
        "s|XXX_ADMIN_DOMAIN_EXPRESSION|${domain_expression}|g" \
        "$destination"
    _config_builder_sed_inplace \
        "s|XXX_ADMIN_PORT|${container_port}|g" \
        "$destination"
}

# ------------------------------------------------------------------------------
# append_admin_ui_service
# ------------------------------------------------------------------------------
# Appends one profile-selected database-management service while retaining only
# the routing section appropriate for the selected proxy mode.
#
# Arguments:
#   $1 - project_root: absolute path to the repository root.
#   $2 - admin_ui_type: pgadmin or mongo-express.
#   $3 - proxy_type: traefik or none.
#   $4 - ssl_mode: letsencrypt/direct or proxy.
#
# Returns:
#   0 after appending the rendered service, 1 for an unsupported or missing
#   admin UI module.
#
# Side effects:
#   Uses and removes one process-specific temporary Compose module.
# ------------------------------------------------------------------------------
append_admin_ui_service() {
    local project_root="$1"
    local admin_ui_type="$2"
    local proxy_type="$3"
    local ssl_mode="${4:-letsencrypt}"
    local source_module=""
    local temporary_module=""
    local labels_module=""

    case "$admin_ui_type" in
        pgadmin|mongo-express)
            source_module="${project_root}/setup/compose-modules/${admin_ui_type}-local.yml"
            ;;
        *)
            echo "Unsupported profile admin UI type: ${admin_ui_type}" >&2
            return 1
            ;;
    esac
    if [ ! -f "$source_module" ]; then
        echo "Profile admin UI compose module is missing: ${source_module}" >&2
        return 1
    fi
    temporary_module="${source_module%.yml}.temp.$$.yml"
    cp "$source_module" "$temporary_module"

    if [ "$proxy_type" = "traefik" ]; then
        labels_module="${temporary_module%.yml}.labels.yml"
        if ! _prepare_admin_ui_traefik_labels \
            "$project_root" \
            "$admin_ui_type" \
            "$ssl_mode" \
            "$labels_module"; then
            rm -f "$temporary_module" "$labels_module"
            echo "Could not render admin UI Traefik labels." >&2
            return 1
        fi
        _config_builder_sed_inplace \
            "/###ADMIN_TRAEFIK_LABELS###/r $labels_module" \
            "$temporary_module"
        rm -f "$labels_module"
        _config_builder_sed_inplace \
            '/###ADMIN_DIRECT_PORTS_START###/,/###ADMIN_DIRECT_PORTS_END###/d' \
            "$temporary_module"
    else
        _config_builder_sed_inplace \
            '/###ADMIN_TRAEFIK_NETWORK_START###/,/###ADMIN_TRAEFIK_NETWORK_END###/d' \
            "$temporary_module"
        _config_builder_sed_inplace \
            '/###ADMIN_TRAEFIK_LABELS_START###/,/###ADMIN_TRAEFIK_LABELS_END###/d' \
            "$temporary_module"
    fi
    _config_builder_sed_inplace '/###ADMIN_.*###/d' "$temporary_module"
    cat "$temporary_module" >> "${project_root}/swarm-stack.yml"
    rm -f "$temporary_module"
}
