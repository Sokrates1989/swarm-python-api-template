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

_SEMANTIC_VERSION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${_SEMANTIC_VERSION_DIR}/operator-menu-localization.sh"

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

# Validate one Docker image tag without a repository or digest.
image_tag_is_valid() {
    [[ "$1" =~ ^[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,127}$ ]]
}

# Accept explicit Docker tags while excluding mutable aliases reserved by the
# release and test-channel workflows.
image_tag_is_deployable() {
    image_tag_is_valid "$1" || return 1
    case "${1,,}" in
        latest|latest-test) return 1 ;;
        *) return 0 ;;
    esac
}

# Resolve the stable SemVer comparison base of a clean or versioned test tag.
semantic_version_comparison_base() {
    if semantic_version_is_valid "$1"; then
        printf '%s' "$1"
        return 0
    fi
    if [[ "$1" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)-test$ ]]; then
        printf '%s' "${1%-test}"
        return 0
    fi
    return 1
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

# Print one localized semantic-version menu message.
_semantic_version_say() {
    operator_menu_message "$@"
    printf '\n'
}

# Read one semantic-version menu choice through the active prompt adapter.
_semantic_version_prompt() {
    local message_key="$1"
    local target_name="$2"
    local prompt=""

    prompt="$(operator_menu_message "$message_key")" || return 1
    if declare -F read_prompt >/dev/null 2>&1; then
        read_prompt "$prompt" "$target_name"
    else
        read -r -p "$prompt" "$target_name"
    fi
}

# Read one exact registry tag using Docker's tag grammar and immutable-alias
# policy. Registry existence and platform support are verified by the caller.
prompt_exact_image_tag() {
    local target_name="$1"
    local default_value="${2:-}"
    local value=""

    while true; do
        _semantic_version_prompt semver.exact_prompt value
        value="${value:-$default_value}"
        if image_tag_is_deployable "$value"; then
            printf -v "$target_name" '%s' "$value"
            return 0
        fi
        _semantic_version_say semver.invalid_tag
    done
}

source "${_SEMANTIC_VERSION_DIR}/semantic-version-rollback-menu.sh"

# ------------------------------------------------------------------------------
# select_published_semver
# ------------------------------------------------------------------------------
# Renders the canonical upgrade/exact menu with grouped rollback discovery.
# Every displayed version comes from registry discovery. An exact fallback is
# accepted only after immediate registry/platform verification succeeds.
#
# Arguments:
#   $1 - Target variable name.
#   $2 - Human-readable service label.
#   $3 - Docker repository without a tag.
#   $4 - Current image tag; clean SemVer and -test tags are comparable.
#   Remaining arguments - Published stable versions for this service.
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
    local ordered=()
    local upgrades=()
    local rollbacks=()
    local highest_published=""
    local choice=""
    local candidate=""
    local default_choice='1'
    local prompt_key='semver.choice_keep'
    local show_highest=false
    local exact_requested=false
    local comparison_base=""
    local has_comparison_base=false
    local index=0
    local comparison=""

    if comparison_base="$(semantic_version_comparison_base "$current")"; then
        has_comparison_base=true
    else
        _semantic_version_say semver.comparison_unavailable "$label" "$current"
    fi
    mapfile -t ordered < <(sort_semantic_versions_desc "${published[@]}")
    highest_published="$(highest_semantic_version "${ordered[@]}")" ||
        highest_published=""
    if [ "$has_comparison_base" = true ]; then
        for candidate in "${ordered[@]}"; do
            comparison="$(compare_semantic_versions "$candidate" "$comparison_base")"
            case "$comparison" in
                1) upgrades+=("$candidate") ;;
                -1) rollbacks+=("$candidate") ;;
            esac
        done
    fi
    if [ -n "$highest_published" ] &&
        { [ "$has_comparison_base" = false ] ||
            [ "$(compare_semantic_versions "$highest_published" "$comparison_base")" != '-1' ]; }; then
        show_highest=true
        default_choice='h'
        prompt_key='semver.choice_highest'
    fi
    while true; do
        exact_requested=false
        candidate=""
        echo ""
        _semantic_version_say semver.options_header "$label"
        _semantic_version_say semver.keep_current "$current"
        for index in "${!upgrades[@]}"; do
            echo "  $((index + 2))) ${upgrades[$index]}"
        done
        [ "${#rollbacks[@]}" -eq 0 ] ||
            _semantic_version_say semver.show_rollbacks
        _semantic_version_say semver.exact
        [ "$show_highest" = false ] ||
            _semantic_version_say semver.highest "$highest_published"
        _semantic_version_say semver.cancel
        _semantic_version_prompt "$prompt_key" choice
        choice="${choice,,}"
        case "${choice:-$default_choice}" in
            1|k|keep|current) candidate="$current" ;;
            r|x|rollback|rollbacks)
                if [ "${#rollbacks[@]}" -gt 0 ] &&
                    select_published_rollback_semver \
                        candidate "$label" "${rollbacks[@]}"; then
                    printf -v "$target_name" '%s' "$candidate"
                    return 0
                fi
                continue
                ;;
            e|exact|manual)
                prompt_exact_image_tag candidate
                exact_requested=true
                ;;
            h|highest)
                if [ "$show_highest" = true ]; then
                    candidate="$highest_published"
                else
                    _semantic_version_say semver.invalid_main
                    continue
                fi
                ;;
            0|q|quit|cancel) return 1 ;;
            *)
                if [[ "$choice" =~ ^[0-9]+$ ]] &&
                    [ "$choice" -ge 2 ] &&
                    [ "$choice" -le "$((${#upgrades[@]} + 1))" ]; then
                    candidate="${upgrades[$((choice - 2))]}"
                else
                    _semantic_version_say semver.invalid_main
                    continue
                fi
                ;;
        esac
        if [ "$candidate" = "$current" ] ||
            semantic_version_is_listed "$candidate" "${published[@]}"; then
            printf -v "$target_name" '%s' "$candidate"
            return 0
        fi
        if [ "$exact_requested" = true ] && image_tag_is_deployable "$candidate" &&
            registry_verify_tag "$repository" "$candidate" >/dev/null; then
            printf -v "$target_name" '%s' "$candidate"
            return 0
        fi
        _semantic_version_say semver.not_published "$candidate" "$label"
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
