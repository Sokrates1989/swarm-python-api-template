#!/bin/bash
# ==============================================================================
# deployment-profile-routing.sh - Shared proxy, TLS, and port collection
# ==============================================================================
#
# Collects routing choices for public profiles and derives fixed no-proxy state
# for internal profiles. Overlay membership and Traefik's provider constraint
# label remain distinct operator values. The module uses shared numbered prompt
# primitives and real Traefik overlay discovery.
#
# Dependencies:
#   - setup/modules/deployment-profile-prompts.sh
#   - setup/modules/user-prompts.sh
#   - _deployment_existing_value from deployment-profile-inputs.sh at runtime
# ==============================================================================

# Guard against multiple sourcing.
if [ -n "${_DEPLOYMENT_PROFILE_ROUTING_LOADED:-}" ]; then
    return 0 2>/dev/null || true
fi
_DEPLOYMENT_PROFILE_ROUTING_LOADED=1

# ------------------------------------------------------------------------------
# _deployment_proxy_choice_pairs
# ------------------------------------------------------------------------------
# Converts profile exposure capabilities into reachable proxy alternatives.
#
# Output:
#   One "value|label" pair for each routing mode the profile can expose.
#
# Returns:
#   0 after printing zero or more choices.
_deployment_proxy_choice_pairs() {
    if [ "${APP_EXPOSURE_TRAEFIK:-true}" = "true" ]; then
        echo "traefik|Traefik (automatic HTTPS)"
    fi
    if [ "${APP_EXPOSURE_PUBLISHED_PORTS:-true}" = "true" ]; then
        echo "none|None (direct port)"
    fi
}

# ------------------------------------------------------------------------------
# prompt_external_overlay_network_name
# ------------------------------------------------------------------------------
# Selects an existing non-ingress Swarm overlay or records a safe name that the
# deploy action may create. This is used by any profile declaring an external
# internal network and contains no application-specific behavior.
#
# Arguments:
#   $1 - Caller-owned target variable.
#   $2 - Profile/existing-environment default network name.
#
# Returns:
#   0 after assigning a selected safe name; 1 when setup is cancelled.
prompt_external_overlay_network_name() {
    local target_name="$1"
    local configured_default="$2"
    local choices=()
    local candidate=""
    local default_value="custom"
    local selected=""
    local default_found=false

    while IFS= read -r candidate; do
        [ -n "$candidate" ] || continue
        if _swarm_overlay_network_is_usable "$candidate"; then
            choices+=("${candidate}|Existing overlay: ${candidate}")
            if [ "$candidate" = "$configured_default" ]; then
                default_value="$candidate"
                default_found=true
            fi
        fi
    done < <(docker network ls \
        --filter driver=overlay \
        --format "{{.Name}}" 2>/dev/null)

    if [ "$default_found" = "false" ] &&
        _deployment_value_is_valid name "$configured_default"; then
        choices+=(
            "${configured_default}|Use ${configured_default} (create during deploy if missing)"
        )
        default_value="$configured_default"
    fi
    choices+=(
        "custom|Enter another overlay network name"
        "cancel|Cancel setup"
    )
    prompt_deployment_choice \
        selected \
        "Required external overlay network" \
        "$default_value" \
        "${choices[@]}"
    if [ "$selected" = "cancel" ]; then
        return 1
    fi
    if [ "$selected" = "custom" ]; then
        prompt_deployment_value \
            selected \
            "External overlay network name" \
            "$configured_default" \
            "name"
    fi
    printf -v "$target_name" '%s' "$selected"
}

# ------------------------------------------------------------------------------
# collect_deployment_proxy_and_ports
# ------------------------------------------------------------------------------
# Collects public proxy, TLS ownership, Traefik network/provider label, and
# direct ports.
#
# Returns:
#   0 after setting proxy and published-port globals.
# ------------------------------------------------------------------------------
collect_deployment_proxy_and_ports() {
    local default_proxy="traefik"
    local default_ssl="${APP_ROUTING_DEFAULT_SSL_MODE:-letsencrypt}"
    local proxy_choices=()
    local proxy_choice=""

    API_PUBLISHED_PORT="$(_deployment_existing_value \
        API_PUBLISHED_PORT \
        "${APP_ROUTING_API_PUBLISHED_PORT:-8083}")"
    WEB_PUBLISHED_PORT="$(_deployment_existing_value \
        WEB_PUBLISHED_PORT \
        "${APP_ROUTING_WEB_PUBLISHED_PORT:-8084}")"
    PGADMIN_PUBLISHED_PORT="$(_deployment_existing_value \
        PGADMIN_PUBLISHED_PORT \
        "${APP_ROUTING_PGADMIN_PUBLISHED_PORT:-5054}")"
    TRAEFIK_CERT_RESOLVER="$(_deployment_existing_value \
        TRAEFIK_CERT_RESOLVER \
        "${APP_ROUTING_TRAEFIK_CERT_RESOLVER:-le}")"
    TRAEFIK_CONSTRAINT_LABEL="$(_deployment_existing_value \
        TRAEFIK_CONSTRAINT_LABEL \
        "${APP_ROUTING_TRAEFIK_CONSTRAINT_LABEL:-traefik-public}")"

    if [ "$APP_IS_INTERNAL" = "true" ]; then
        PROXY_TYPE="none"
        SSL_MODE=""
        TRAEFIK_NETWORK=""
        TRAEFIK_CONSTRAINT_LABEL=""
        API_PUBLISHED_PORT=""
        WEB_PUBLISHED_PORT=""
        echo ""
        echo "Proxy: none (internal-only profile)"
        return 0
    fi

    while IFS= read -r proxy_choice; do
        [ -n "$proxy_choice" ] && proxy_choices+=("$proxy_choice")
    done < <(_deployment_proxy_choice_pairs)
    if [ "${#proxy_choices[@]}" -eq 0 ]; then
        echo "[ERROR] Public profile exposes neither Traefik nor direct ports."
        return 1
    fi
    default_proxy="${proxy_choices[0]%%|*}"
    default_proxy="$(_deployment_existing_value PROXY_TYPE "$default_proxy")"
    if [ "${#proxy_choices[@]}" -eq 1 ]; then
        PROXY_TYPE="${proxy_choices[0]%%|*}"
        echo ""
        echo "Proxy type: ${PROXY_TYPE} (fixed by profile)"
    else
        prompt_deployment_choice \
            PROXY_TYPE \
            "Proxy type" \
            "$default_proxy" \
            "${proxy_choices[@]}"
    fi
    echo "Proxy: ${PROXY_TYPE}"

    if [ "$PROXY_TYPE" = "traefik" ]; then
        default_ssl="$(_deployment_existing_value SSL_MODE "$default_ssl")"
        prompt_deployment_choice \
            SSL_MODE \
            "SSL mode" \
            "$default_ssl" \
            "letsencrypt|letsencrypt (Traefik obtains certificate)" \
            "proxy|proxy (SSL terminated upstream, e.g. Cloudflare)"
        echo "SSL: ${SSL_MODE}"
        TRAEFIK_NETWORK="$(prompt_traefik_network \
            "$(_deployment_existing_value \
                TRAEFIK_NETWORK \
                "${APP_ROUTING_TRAEFIK_NETWORK:-traefik-public}")")" ||
            return 1
        prompt_deployment_value \
            TRAEFIK_CONSTRAINT_LABEL \
            "Traefik provider constraint label" \
            "$TRAEFIK_CONSTRAINT_LABEL" \
            "name"
        if [ "$SSL_MODE" = "letsencrypt" ]; then
            prompt_deployment_value \
                TRAEFIK_CERT_RESOLVER \
                "Traefik certificate resolver" \
                "$TRAEFIK_CERT_RESOLVER" \
                "name"
        fi
        return 0
    fi

    SSL_MODE=""
    TRAEFIK_NETWORK=""
    TRAEFIK_CONSTRAINT_LABEL=""
    if [ "${APP_EXPOSURE_PUBLISHED_PORTS:-true}" = "true" ]; then
        prompt_deployment_value \
            API_PUBLISHED_PORT \
            "Published API port" \
            "$API_PUBLISHED_PORT" \
            "port"
        if [ "${APP_REQUIRES_WEB:-false}" = "true" ]; then
            prompt_deployment_value \
                WEB_PUBLISHED_PORT \
                "Published WebApp port" \
                "$WEB_PUBLISHED_PORT" \
                "port"
        fi
    fi
}
