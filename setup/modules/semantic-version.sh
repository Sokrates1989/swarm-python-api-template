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
# increment_semantic_version
# ------------------------------------------------------------------------------
# Computes one strict next semantic version for menu presentation only.
# Deployment callers must still prove the resulting tag exists in a registry.
#
# Arguments:
#   $1 - Current stable semantic version.
#   $2 - patch, minor, or major.
#
# Output:
#   Incremented stable semantic version.
#
# Returns:
#   0 after a valid increment; otherwise 1.
# ------------------------------------------------------------------------------
increment_semantic_version() {
    local current="$1"
    local level="$2"
    local parts=()

    semantic_version_is_valid "$current" || return 1
    IFS='.' read -r -a parts <<< "$current"
    case "$level" in
        patch) parts[2]=$((parts[2] + 1)) ;;
        minor) parts[1]=$((parts[1] + 1)); parts[2]=0 ;;
        major) parts[0]=$((parts[0] + 1)); parts[1]=0; parts[2]=0 ;;
        *) return 1 ;;
    esac
    printf '%s.%s.%s' "${parts[0]}" "${parts[1]}" "${parts[2]}"
}

# ------------------------------------------------------------------------------
# semantic_version_is_listed
# ------------------------------------------------------------------------------
# Checks whether one exact semantic version occurs in a provided registry list.
#
# Arguments:
#   $1 - Exact version to find.
#   Remaining arguments - Published semantic versions.
#
# Returns:
#   0 when present; otherwise 1.
# ------------------------------------------------------------------------------
semantic_version_is_listed() {
    local expected="$1"
    local candidate=""
    shift

    for candidate in "$@"; do
        [ "$candidate" = "$expected" ] && return 0
    done
    return 1
}

# ------------------------------------------------------------------------------
# select_published_semver
# ------------------------------------------------------------------------------
# Renders the canonical keep/patch/feature/major/exact menu. Computed choices
# must come from registry discovery. An exact fallback is accepted only after
# immediate registry/platform verification succeeds.
#
# Arguments:
#   $1 - Target variable name.
#   $2 - Human-readable service label.
#   $3 - Docker repository without a tag.
#   $4 - Current stable semantic version.
#   Remaining arguments - Published versions that are safe for this service.
#
# Returns:
#   0 after assigning a published version; 1 after cancellation or bad inputs.
# ------------------------------------------------------------------------------
select_published_semver() {
    local target_name="$1"
    local label="$2"
    local repository="$3"
    local current="$4"
    shift 4
    local published=("$@")
    local patch=""
    local minor=""
    local major=""
    local highest=""
    local choice=""
    local exact=""
    local candidate=""
    local exact_requested=false

    semantic_version_is_valid "$current" || {
        echo "[ERROR] ${label} current version is not semantic: ${current}" >&2
        return 1
    }
    patch="$(increment_semantic_version "$current" patch)" || return 1
    minor="$(increment_semantic_version "$current" minor)" || return 1
    major="$(increment_semantic_version "$current" major)" || return 1
    highest="$(highest_semantic_version "${published[@]}")" || highest="$current"

    while true; do
        exact_requested=false
        echo ""
        echo "${label} published image version options:"
        echo "  1/k) Keep current (${current})"
        if semantic_version_is_listed "$patch" "${published[@]}"; then
            echo "  2/p) Patch (${current} -> ${patch})"
        else
            echo "  2/p) Patch (${patch}) [not published]"
        fi
        if semantic_version_is_listed "$minor" "${published[@]}"; then
            echo "  3/f) Feature / Minor (${current} -> ${minor})"
        else
            echo "  3/f) Feature / Minor (${minor}) [not published]"
        fi
        if semantic_version_is_listed "$major" "${published[@]}"; then
            echo "  4/m) Major (${current} -> ${major})"
        else
            echo "  4/m) Major (${major}) [not published]"
        fi
        echo "  5/e) Enter an exact published semantic version"
        echo "  h) Highest published stable version (${highest})"
        echo "  0/q) Cancel"
        read -r -p "Your choice [1/k]: " choice
        choice="${choice,,}"
        case "${choice:-1}" in
            1|k|keep|current) candidate="$current" ;;
            2|p|patch) candidate="$patch" ;;
            3|f|feature|minor) candidate="$minor" ;;
            4|m|major) candidate="$major" ;;
            5|e|exact|manual)
                read -r -p "Exact published version: " exact
                candidate="$exact"
                exact_requested=true
                ;;
            h|highest) candidate="$highest" ;;
            0|q|quit|cancel) return 1 ;;
            *)
                echo "[WARN] Use 1-5, k/p/f/m/e, h, or 0/q."
                continue
                ;;
        esac
        if semantic_version_is_listed "$candidate" "${published[@]}"; then
            printf -v "$target_name" '%s' "$candidate"
            return 0
        fi
        if [ "$exact_requested" = true ] && semantic_version_is_valid "$candidate" &&
            [ "$(compare_semantic_versions "$candidate" "$current")" != '-1' ] &&
            registry_verify_tag "$repository" "$candidate" >/dev/null; then
            printf -v "$target_name" '%s' "$candidate"
            return 0
        fi
        echo "[WARN] ${candidate} is not a published version for ${label}."
    done
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
