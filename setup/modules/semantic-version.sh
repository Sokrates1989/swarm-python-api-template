#!/bin/bash
# ==============================================================================
# semantic-version.sh - Shared stable semantic-version helpers
# ==============================================================================
#
# Validates, compares, and resolves stable MAJOR.MINOR.PATCH versions and exact
# MAJOR.MINOR.PATCH-test deployment tags. Registry discovery owns deployment
# choices; this module never invents an unpublished image tag.
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

# ------------------------------------------------------------------------------
# versioned_test_tag_is_valid
# ------------------------------------------------------------------------------
# Checks an exact test-channel image tag. The mutable latest-test alias is
# deliberately not a deployable version.
#
# Arguments:
#   $1 - Candidate image tag.
#
# Returns:
#   0 for strict MAJOR.MINOR.PATCH-test syntax; otherwise 1.
# ------------------------------------------------------------------------------
versioned_test_tag_is_valid() {
    local tag="$1"

    [[ "$tag" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)-test$ ]]
}

# ------------------------------------------------------------------------------
# versioned_test_tag_base
# ------------------------------------------------------------------------------
# Removes the fixed test suffix after validating the exact tag.
#
# Arguments:
#   $1 - Candidate MAJOR.MINOR.PATCH-test tag.
#
# Output:
#   Stable semantic base version.
#
# Returns:
#   0 when valid; otherwise 1.
# ------------------------------------------------------------------------------
versioned_test_tag_base() {
    local tag="$1"

    versioned_test_tag_is_valid "$tag" || return 1
    printf '%s' "${tag%-test}"
}

# ------------------------------------------------------------------------------
# highest_versioned_test_tag
# ------------------------------------------------------------------------------
# Resolves the greatest exact versioned test tag by comparing its numeric base.
#
# Arguments:
#   All arguments are candidate registry tags.
#
# Output:
#   Greatest MAJOR.MINOR.PATCH-test tag.
#
# Returns:
#   0 when at least one valid tag exists; otherwise 1.
# ------------------------------------------------------------------------------
highest_versioned_test_tag() {
    local highest_tag=""
    local highest_base=""
    local candidate=""
    local candidate_base=""
    local comparison=""

    for candidate in "$@"; do
        candidate_base="$(versioned_test_tag_base "$candidate")" || continue
        if [ -z "$highest_tag" ]; then
            highest_tag="$candidate"
            highest_base="$candidate_base"
            continue
        fi
        comparison="$(compare_semantic_versions "$candidate_base" "$highest_base")" ||
            return 1
        if [ "$comparison" = "1" ]; then
            highest_tag="$candidate"
            highest_base="$candidate_base"
        fi
    done
    [ -n "$highest_tag" ] || return 1
    printf '%s' "$highest_tag"
}
