#!/bin/bash
# ==============================================================================
# semantic-version.sh - Shared stable semantic-version helpers
# ==============================================================================
#
# Validates, compares, increments, and interactively selects stable
# MAJOR.MINOR.PATCH versions. The module is application-neutral and is shared
# by deployment-management actions that need a monotonic release baseline.
#
# Dependencies:
#   - deployment-profile-prompts.sh for numbered and validated input.
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
# bump_semantic_version
# ------------------------------------------------------------------------------
# Increments one component of a stable semantic version.
#
# Arguments:
#   $1 - Current semantic version.
#   $2 - Increment kind: patch, minor, or major.
#
# Output:
#   Incremented version.
#
# Returns:
#   0 after a valid increment; otherwise 1.
# ------------------------------------------------------------------------------
bump_semantic_version() {
    local current="$1"
    local increment="$2"
    local major=""
    local minor=""
    local patch=""

    semantic_version_is_valid "$current" || return 1
    IFS='.' read -r major minor patch <<< "$current"
    case "$increment" in
        patch) patch=$((patch + 1)) ;;
        minor) minor=$((minor + 1)); patch=0 ;;
        major) major=$((major + 1)); minor=0; patch=0 ;;
        *) return 1 ;;
    esac
    printf '%s.%s.%s' "$major" "$minor" "$patch"
}

# ------------------------------------------------------------------------------
# semantic_version_is_at_least
# ------------------------------------------------------------------------------
# Checks that a candidate does not move below a coordinated version floor.
#
# Arguments:
#   $1 - Candidate semantic version.
#   $2 - Minimum semantic version.
#
# Returns:
#   0 when candidate is equal to or higher than the floor; otherwise 1.
# ------------------------------------------------------------------------------
semantic_version_is_at_least() {
    local comparison=""

    comparison="$(compare_semantic_versions "$1" "$2")" || return 1
    [ "$comparison" != "-1" ]
}

# ------------------------------------------------------------------------------
# select_semantic_version
# ------------------------------------------------------------------------------
# Offers patch, minor, major, exact, floor, and cancel choices from one shared
# monotonic baseline. Exact versions below the baseline are rejected.
#
# Arguments:
#   $1 - Current stack-wide semantic-version floor.
#   $2 - Optional operator-facing section label.
#   $3 - Optional default action: patch (default) or floor.
#
# Returns:
#   0 after setting SELECTED_SEMANTIC_VERSION; 1 on cancellation or invalid
#   baseline.
#
# Side effects:
#   Reads numbered terminal input and sets SELECTED_SEMANTIC_VERSION.
# ------------------------------------------------------------------------------
select_semantic_version() {
    local floor="$1"
    local label="${2:-Release version}"
    local default_action="${3:-patch}"
    local patch_version=""
    local minor_version=""
    local major_version=""
    local action=""
    local exact_version=""
    local choices=()

    semantic_version_is_valid "$floor" || return 1
    case "$default_action" in
        patch|floor) ;;
        *) return 1 ;;
    esac
    patch_version="$(bump_semantic_version "$floor" patch)" || return 1
    minor_version="$(bump_semantic_version "$floor" minor)" || return 1
    major_version="$(bump_semantic_version "$floor" major)" || return 1
    if [ "$default_action" = 'floor' ]; then
        choices+=("floor|Use the current stack floor (${floor})")
    fi
    choices+=(
        "patch|Patch (${floor} -> ${patch_version})"
        "minor|Minor (${floor} -> ${minor_version})"
        "major|Major (${floor} -> ${major_version})"
        "exact|Enter an exact semantic version"
    )
    if [ "$default_action" != 'floor' ]; then
        choices+=("floor|Use the current stack floor (${floor})")
    fi
    choices+=("cancel|Cancel")
    prompt_deployment_choice \
        action \
        "$label (current stack floor: ${floor})" \
        "$default_action" \
        "${choices[@]}"
    case "$action" in
        patch) SELECTED_SEMANTIC_VERSION="$patch_version" ;;
        minor) SELECTED_SEMANTIC_VERSION="$minor_version" ;;
        major) SELECTED_SEMANTIC_VERSION="$major_version" ;;
        floor) SELECTED_SEMANTIC_VERSION="$floor" ;;
        cancel) return 1 ;;
        exact)
            while true; do
                prompt_deployment_value \
                    exact_version \
                    "Exact semantic version" \
                    "$floor" \
                    "semver"
                if semantic_version_is_at_least "$exact_version" "$floor"; then
                    SELECTED_SEMANTIC_VERSION="$exact_version"
                    break
                fi
                echo "Version ${exact_version} is below the stack floor ${floor}."
            done
            ;;
        *) return 1 ;;
    esac
}
