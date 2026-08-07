#!/bin/bash
# ==============================================================================
# semantic-version.sh - Shared stable semantic-version helpers
# ==============================================================================
#
# Validates, compares, and resolves stable MAJOR.MINOR.PATCH versions. Registry
# discovery owns deployment choices; this module never invents an image tag.
# ==============================================================================

# Guard against multiple sourcing.
if [ -n "${_SEMANTIC_VERSION_HELPERS_LOADED:-}" ]; then
    return 0 2>/dev/null || true
fi
_SEMANTIC_VERSION_HELPERS_LOADED=1

# ------------------------------------------------------------------------------
# semantic_version_is_valid
# ------------------------------------------------------------------------------
# Checks one stable semantic version without prefixes, prerelease labels, or
# build metadata.
#
# Arguments:
#   $1 - Candidate version.
#
# Returns:
#   0 for strict MAJOR.MINOR.PATCH syntax; otherwise 1.
# ------------------------------------------------------------------------------
semantic_version_is_valid() {
    local version="$1"

    [[ "$version" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]
}

# ------------------------------------------------------------------------------
# compare_semantic_versions
# ------------------------------------------------------------------------------
# Compares two validated stable semantic versions numerically.
#
# Arguments:
#   $1 - Left version.
#   $2 - Right version.
#
# Output:
#   -1 when left is lower, 0 when equal, and 1 when left is higher.
#
# Returns:
#   0 after comparison; 1 when either input is invalid.
# ------------------------------------------------------------------------------
compare_semantic_versions() {
    local left="$1"
    local right="$2"
    local left_parts=()
    local right_parts=()
    local index=0

    semantic_version_is_valid "$left" || return 1
    semantic_version_is_valid "$right" || return 1
    IFS='.' read -r -a left_parts <<< "$left"
    IFS='.' read -r -a right_parts <<< "$right"
    for index in 0 1 2; do
        if [ "${left_parts[$index]}" -lt "${right_parts[$index]}" ]; then
            printf '%s' '-1'
            return 0
        fi
        if [ "${left_parts[$index]}" -gt "${right_parts[$index]}" ]; then
            printf '%s' '1'
            return 0
        fi
    done
    printf '%s' '0'
}

# ------------------------------------------------------------------------------
# highest_semantic_version
# ------------------------------------------------------------------------------
# Resolves the greatest valid version from a caller-provided list.
#
# Arguments:
#   All arguments are candidate versions.
#
# Output:
#   Greatest valid semantic version.
#
# Returns:
#   0 when at least one valid version exists; otherwise 1.
# ------------------------------------------------------------------------------
highest_semantic_version() {
    local highest=""
    local candidate=""
    local comparison=""

    for candidate in "$@"; do
        semantic_version_is_valid "$candidate" || continue
        if [ -z "$highest" ]; then
            highest="$candidate"
            continue
        fi
        comparison="$(compare_semantic_versions "$candidate" "$highest")" ||
            return 1
        if [ "$comparison" = "1" ]; then
            highest="$candidate"
        fi
    done
    [ -n "$highest" ] || return 1
    printf '%s' "$highest"
}
