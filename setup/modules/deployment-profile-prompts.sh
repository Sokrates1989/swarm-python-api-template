#!/bin/bash
# ==============================================================================
# deployment-profile-prompts.sh - Shared numbered deployment prompt primitives
# ==============================================================================
#
# Provides the only choice and value prompt implementation used by the setup
# wizard. Renderer adapters consume normalized answers and must not read from
# the terminal themselves.
#
# Dependencies:
#   - Bash 4.3 or newer for caller-owned variable assignment.
#   - setup/modules/deployment-memory-policy.sh.
# ==============================================================================

# Guard against multiple sourcing.
if [ -n "${_DEPLOYMENT_PROFILE_PROMPTS_LOADED:-}" ]; then
    return 0 2>/dev/null || true
fi
_DEPLOYMENT_PROFILE_PROMPTS_LOADED=1

# Shared optional memory-limit normalization and operator guidance.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/deployment-memory-policy.sh"
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/deployment-field-help.sh"

# ------------------------------------------------------------------------------
# _deployment_public_domain_prompt_label
# ------------------------------------------------------------------------------
# Adds the shared subdomain-creation guide to a public-domain prompt label.
# Labels ending in parentheses receive the hint inside that existing group;
# plain labels receive a new parenthesized hint. An already decorated label is
# returned unchanged so callers may safely reuse this helper.
#
# Arguments:
#   $1 - Operator-facing prompt label.
#
# Output:
#   The label containing exactly one subdomain-creation guide URL.
#
# Returns:
#   0 after printing the decorated label.
# ------------------------------------------------------------------------------
_deployment_public_domain_prompt_label() {
    local label="$1"

    if [[ "$label" == *"$PUBLIC_DOMAIN_CREATE_INFO_URL"* ]]; then
        printf '%s' "$label"
    elif [[ "$label" == *")" ]]; then
        printf '%s, create-info: %s)' \
            "${label%)}" \
            "$PUBLIC_DOMAIN_CREATE_INFO_URL"
    else
        printf '%s (create-info: %s)' \
            "$label" \
            "$PUBLIC_DOMAIN_CREATE_INFO_URL"
    fi
}

# ------------------------------------------------------------------------------
# _deployment_value_is_valid
# ------------------------------------------------------------------------------
# Validates a normalized free-text deployment answer.
#
# Arguments:
#   $1 - Validation kind: nonempty, name, domain, host, identifier, tag,
#        semver, url, integer, positive, port, image, memory, path, email,
#        or any.
#   $2 - Candidate value.
#
# Returns:
#   0 when valid; otherwise 1.
# ------------------------------------------------------------------------------
_deployment_value_is_valid() {
    local validation_kind="$1"
    local value="$2"

    # Generated dotenv files are parsed as data, never shell, but rejecting
    # shell metacharacters also prevents ambiguous Compose interpolation and
    # protects older operator tooling that may still inspect them from Bash.
    case "$value" in
        *'$'*|*'`'*|*';'*|*'|'*|*'&'*|*'<'*|*'>'*|*'\'*|*'"'*|*"'"*)
            return 1
            ;;
    esac
    if [[ "$value" == *$'\n'* ]] || [[ "$value" == *$'\r'* ]]; then
        return 1
    fi

    case "$validation_kind" in
        any)
            return 0
            ;;
        nonempty)
            [ -n "$value" ]
            ;;
        name)
            [[ "$value" =~ ^[a-z0-9][a-z0-9._-]*$ ]]
            ;;
        domain)
            [[ "$value" =~ ^[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?$ ]] &&
                [[ "$value" =~ \. ]] &&
                [[ "$value" != *".."* ]]
            ;;
        host)
            [[ "$value" =~ ^[a-zA-Z0-9][a-zA-Z0-9._:-]*$ ]] &&
                [[ "$value" != *".."* ]]
            ;;
        identifier)
            [[ "$value" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]]
            ;;
        tag)
            [[ "$value" =~ ^[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,127}$ ]]
            ;;
        semver)
            [[ "$value" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]
            ;;
        url)
            [[ "$value" =~ ^https?://[a-zA-Z0-9][a-zA-Z0-9._:/%+-]*$ ]]
            ;;
        integer)
            [[ "$value" =~ ^[0-9]+$ ]]
            ;;
        positive)
            [[ "$value" =~ ^[1-9][0-9]*$ ]]
            ;;
        port)
            [[ "$value" =~ ^[0-9]+$ ]] &&
                [ "$value" -ge 1 ] 2>/dev/null &&
                [ "$value" -le 65535 ] 2>/dev/null
            ;;
        image)
            [ -n "$value" ] &&
                [[ "$value" =~ ^[a-z0-9][a-z0-9._/-]*$ ]]
            ;;
        memory)
            deployment_memory_limit_is_valid "$value"
            ;;
        path)
            [[ "$value" =~ ^/[a-zA-Z0-9._/-]+$ ]] &&
                [ "$value" != "/" ] &&
                [[ "$value" != *"//"* ]] &&
                [[ "$value" != *"/../"* ]] &&
                [[ "$value" != */.. ]]
            ;;
        email)
            [[ "$value" =~ ^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,63}$ ]]
            ;;
        *)
            echo "[ERROR] Unknown deployment validation kind: ${validation_kind}" >&2
            return 1
            ;;
    esac
}

# ------------------------------------------------------------------------------
# prompt_deployment_value
# ------------------------------------------------------------------------------
# Prompts for one free-text value, applies its default on Enter, validates the
# result, and assigns it to a caller-owned variable.
#
# Arguments:
#   $1 - Target variable name.
#   $2 - Prompt label.
#   $3 - Default value.
#   $4 - Validation kind accepted by _deployment_value_is_valid.
#        Domain validation automatically adds the public subdomain guide to
#        the displayed label. Memory validation prints byte-unit help and
#        normalizes Enter, `0`, or `unlimited` to the unconstrained sentinel.
#
# Returns:
#   0 after a valid value is assigned.
# ------------------------------------------------------------------------------
prompt_deployment_value() {
    local target_name="$1"
    local label="$2"
    local default_value="$3"
    local validation_kind="$4"
    local selected=""

    if [ "$validation_kind" = "domain" ]; then
        label="$(_deployment_public_domain_prompt_label "$label")"
    elif [ "$validation_kind" = "memory" ]; then
        default_value="$(normalize_deployment_memory_limit "$default_value")"
    fi
    print_deployment_field_help "$target_name" "$validation_kind" prompt

    while true; do
        read -r -p "${label} [${default_value}]: " selected
        selected="${selected:-$default_value}"
        if [ "$validation_kind" = "memory" ]; then
            selected="$(normalize_deployment_memory_limit "$selected")"
        fi
        if _deployment_value_is_valid "$validation_kind" "$selected"; then
            printf -v "$target_name" '%s' "$selected"
            return 0
        fi
        echo "Invalid ${label,,}. Please enter a valid value."
    done
}

# ------------------------------------------------------------------------------
# prompt_deployment_choice
# ------------------------------------------------------------------------------
# Renders a numbered choice menu and assigns the selected stable value. A
# one-character stable value is also rendered and accepted as a named shortcut.
# Choice labels are presentation only; renderer adapters receive stable values.
#
# Arguments:
#   $1 - Target variable name.
#   $2 - Section label.
#   $3 - Default stable value.
#   Remaining arguments - "stable-value|Operator-facing label" pairs.
#
# Returns:
#   0 after a valid numbered or named answer is assigned.
# ------------------------------------------------------------------------------
prompt_deployment_choice() {
    local target_name="$1"
    local label="$2"
    local default_value="$3"
    shift 3
    local choices=("$@")
    local default_number=1
    local index=0
    local pair=""
    local value=""
    local display=""
    local answer=""
    local rendered_key=""

    if [ "${#choices[@]}" -eq 0 ]; then
        echo "[ERROR] ${label} has no allowed choices." >&2
        return 1
    fi

    print_deployment_field_help "$target_name" choice prompt
    echo ""
    echo "${label}:"
    for index in "${!choices[@]}"; do
        pair="${choices[$index]}"
        value="${pair%%|*}"
        display="${pair#*|}"
        if [ "$value" = "$default_value" ]; then
            default_number=$((index + 1))
        fi
        rendered_key="$((index + 1))"
        [ "${#value}" -ne 1 ] || rendered_key+="/${value}"
        echo "  ${rendered_key}) ${display}"
    done
    echo ""

    while true; do
        read -r -p "Your choice (1-${#choices[@]}) [${default_number}]: " answer
        answer="${answer:-$default_number}"
        if [[ "$answer" =~ ^[0-9]+$ ]] &&
            [ "$answer" -ge 1 ] 2>/dev/null &&
            [ "$answer" -le "${#choices[@]}" ] 2>/dev/null; then
            pair="${choices[$((answer - 1))]}"
            printf -v "$target_name" '%s' "${pair%%|*}"
            return 0
        fi
        for pair in "${choices[@]}"; do
            value="${pair%%|*}"
            if [ "${answer,,}" = "${value,,}" ]; then
                printf -v "$target_name" '%s' "$value"
                return 0
            fi
        done
        echo "Invalid choice: '${answer}'. Use a listed number or named key."
    done
}

# ------------------------------------------------------------------------------
# prompt_deployment_toggle
# ------------------------------------------------------------------------------
# Renders a consistent numbered disabled/enabled menu for an optional service.
#
# Arguments:
#   $1 - Target variable name.
#   $2 - Section label.
#   $3 - Default boolean ("true" or "false").
#   $4 - Enabled choice label.
#
# Returns:
#   0 after assigning "true" or "false".
# ------------------------------------------------------------------------------
prompt_deployment_toggle() {
    local target_name="$1"
    local label="$2"
    local default_value="$3"
    local enabled_label="$4"

    prompt_deployment_choice \
        "$target_name" \
        "$label" \
        "$default_value" \
        "false|Disabled" \
        "true|${enabled_label}"
}
