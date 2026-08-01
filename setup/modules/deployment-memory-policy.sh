#!/bin/bash
# ==============================================================================
# deployment-memory-policy.sh - Shared optional Docker memory-limit policy
# ==============================================================================
#
# Normalizes operator memory-limit answers, validates Docker byte quantities,
# explains supported units, and removes optional Compose limit blocks when the
# operator selects an unconstrained service. The canonical unconstrained value
# stored in generated environments is `unlimited`.
#
# Dependencies:
#   - Bash 4 or newer.
#   - sed for template marker processing.
# ==============================================================================

# Guard against multiple sourcing.
if [ -n "${_DEPLOYMENT_MEMORY_POLICY_LOADED:-}" ]; then
    return 0 2>/dev/null || true
fi
_DEPLOYMENT_MEMORY_POLICY_LOADED=1

# ------------------------------------------------------------------------------
# normalize_deployment_memory_limit
# ------------------------------------------------------------------------------
# Converts empty, zero, or case-insensitive `unlimited` input to the canonical
# unconstrained sentinel. Explicit Docker byte quantities are preserved.
#
# Arguments:
#   $1 - Raw memory-limit value.
#
# Output:
#   `unlimited` or the unchanged explicit byte quantity.
# ------------------------------------------------------------------------------
normalize_deployment_memory_limit() {
    local value="${1:-}"

    case "${value,,}" in
        ""|0|unlimited) printf '%s' "unlimited" ;;
        *) printf '%s' "$value" ;;
    esac
}

# ------------------------------------------------------------------------------
# deployment_memory_limit_is_unlimited
# ------------------------------------------------------------------------------
# Recognizes every supported operator spelling for an omitted Docker limit.
#
# Arguments:
#   $1 - Raw or normalized memory-limit value.
#
# Returns:
#   0 when unconstrained; otherwise 1.
# ------------------------------------------------------------------------------
deployment_memory_limit_is_unlimited() {
    [ "$(normalize_deployment_memory_limit "${1:-}")" = "unlimited" ]
}

# ------------------------------------------------------------------------------
# deployment_memory_limit_is_valid
# ------------------------------------------------------------------------------
# Accepts an unconstrained sentinel or a positive whole-number Docker byte
# quantity. Units are case-insensitive B, K/KB/KiB, M/MB/MiB, G/GB/GiB,
# T/TB/TiB, and their supported P equivalents.
#
# Arguments:
#   $1 - Candidate memory-limit value.
#
# Returns:
#   0 when accepted; otherwise 1.
# ------------------------------------------------------------------------------
deployment_memory_limit_is_valid() {
    local value=""

    value="$(normalize_deployment_memory_limit "${1:-}")"
    if [ "$value" = "unlimited" ]; then
        return 0
    fi
    value="${value^^}"
    [[ "$value" =~ ^[1-9][0-9]*(B|[KMGTP](B|IB)?)$ ]]
}

# ------------------------------------------------------------------------------
# print_deployment_memory_limit_help
# ------------------------------------------------------------------------------
# Prints the shared concise explanation shown immediately before every memory
# prompt.
#
# Returns:
#   0 after printing byte units and the unconstrained reset choices.
# ------------------------------------------------------------------------------
print_deployment_memory_limit_help() {
    echo "Memory values are bytes, not bits. Use K/M/G/T (1024-based),"
    echo "for example 512M or 2G; KB/MB/GB/TB and KiB/MiB/GiB/TiB also work."
    echo "Press Enter on [unlimited], or enter unlimited/0, to omit the limit."
}

# ------------------------------------------------------------------------------
# _deployment_memory_sed_inplace
# ------------------------------------------------------------------------------
# Applies one sed expression in place on GNU or BSD hosts.
#
# Arguments:
#   $1 - sed expression.
#   $2 - Target file.
#
# Returns:
#   sed exit status.
# ------------------------------------------------------------------------------
_deployment_memory_sed_inplace() {
    local expression="$1"
    local target="$2"

    if [[ "${OSTYPE:-}" == "darwin"* ]]; then
        sed -i '' "$expression" "$target"
    else
        sed -i "$expression" "$target"
    fi
}

# ------------------------------------------------------------------------------
# apply_deployment_memory_limit_template
# ------------------------------------------------------------------------------
# Resolves one optional Compose memory-limit marker block. Unconstrained values
# remove the entire block; explicit values retain the block and remove markers.
# Files without markers are left unchanged.
#
# Arguments:
#   $1 - Compose template or rendered stack path.
#   $2 - Raw or normalized memory-limit value.
#
# Returns:
#   0 after applying a balanced marker pair; otherwise 1.
# ------------------------------------------------------------------------------
apply_deployment_memory_limit_template() {
    local target="$1"
    local value="${2:-unlimited}"
    local start_marker='###MEMORY_LIMIT_START###'
    local end_marker='###MEMORY_LIMIT_END###'

    if ! grep -q "$start_marker" "$target" &&
        ! grep -q "$end_marker" "$target"; then
        return 0
    fi
    if ! grep -q "$start_marker" "$target" ||
        ! grep -q "$end_marker" "$target"; then
        echo "[ERROR] Unbalanced memory-limit markers in ${target}." >&2
        return 1
    fi
    if deployment_memory_limit_is_unlimited "$value"; then
        _deployment_memory_sed_inplace \
            "/${start_marker}/,/${end_marker}/d" \
            "$target"
        return $?
    fi
    _deployment_memory_sed_inplace "/${start_marker}/d" "$target" &&
        _deployment_memory_sed_inplace "/${end_marker}/d" "$target"
}
