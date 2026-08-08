#!/bin/bash
# ==============================================================================
# menu-image-test-channel.sh - Exact versioned test image selection
# ==============================================================================
#
# Resolves the highest real MAJOR.MINOR.PATCH-test tag for each operator-selected
# application repository. Mutable aliases such as latest-test are excluded by
# registry discovery and never persisted as deployment evidence.
#
# Dependencies:
#   - semantic-version.sh for strict test-tag validation and comparison.
#   - menu-image-audit.sh at execution time for registry_test_tags.
#   - menu-image-actions.sh runtime arrays populated before selection.
# ==============================================================================

# Guard against multiple sourcing.
if [ -n "${_MENU_IMAGE_TEST_CHANNEL_LOADED:-}" ]; then
    return 0 2>/dev/null || true
fi
_MENU_IMAGE_TEST_CHANNEL_LOADED=1

# ------------------------------------------------------------------------------
# _load_published_test_tags
# ------------------------------------------------------------------------------
# Load only exact versioned test tags into a caller-owned array.
#
# Arguments:
#   $1 - Docker repository without tag.
#   $2 - Target array variable name.
#
# Returns:
#   0 when at least one versioned test tag exists; otherwise 1.
# ------------------------------------------------------------------------------
_load_published_test_tags() {
    local repository="$1"
    local target_name="$2"
    local output=""
    local -n target="$target_name"

    output="$(registry_test_tags "$repository")" || {
        echo "[ERROR] Could not enumerate published test tags for ${repository}." >&2
        echo "        Check registry access and publish a MAJOR.MINOR.PATCH-test image first." >&2
        return 1
    }
    target=()
    if [ -n "$output" ]; then
        mapfile -t target <<< "$output"
    fi
    if [ "${#target[@]}" -eq 0 ]; then
        echo "[ERROR] ${repository} has no published MAJOR.MINOR.PATCH-test tags." >&2
        echo "        latest-test is a convenience alias and is never deployed directly." >&2
        return 1
    fi
}

# ------------------------------------------------------------------------------
# _test_tag_is_not_older
# ------------------------------------------------------------------------------
# Prevent an implicit test-channel rollback while allowing an explicit switch
# from a currently configured stable tag to the available test channel.
#
# Arguments:
#   $1 - Candidate MAJOR.MINOR.PATCH-test tag.
#   $2 - Current stable or versioned test tag.
#
# Returns:
#   0 when safe; otherwise 1.
# ------------------------------------------------------------------------------
_test_tag_is_not_older() {
    local candidate="$1"
    local current="$2"
    local candidate_base=""
    local current_base=""
    local comparison=""

    candidate_base="$(versioned_test_tag_base "$candidate")" || return 1
    if ! versioned_test_tag_is_valid "$current"; then
        return 0
    fi
    current_base="$(versioned_test_tag_base "$current")" || return 1
    comparison="$(compare_semantic_versions "$candidate_base" "$current_base")" ||
        return 1
    [ "$comparison" != '-1' ]
}

# ------------------------------------------------------------------------------
# _select_highest_test_image_versions
# ------------------------------------------------------------------------------
# Select the independently highest exact versioned test tag for every selected
# application service. No free-text or mutable alias path exists in this mode.
#
# Returns:
#   0 after populating IMAGE_UPDATE_SELECTED_VERSIONS; otherwise 1.
# ------------------------------------------------------------------------------
_select_highest_test_image_versions() {
    local index=0
    local tags=()
    local highest=""

    IMAGE_UPDATE_SELECTED_VERSIONS=()
    for index in "${!IMAGE_UPDATE_SELECTED_REPOSITORIES[@]}"; do
        _load_published_test_tags \
            "${IMAGE_UPDATE_SELECTED_REPOSITORIES[$index]}" tags || return 1
        highest="$(highest_versioned_test_tag "${tags[@]}")" || return 1
        if ! _test_tag_is_not_older \
            "$highest" "${IMAGE_UPDATE_SELECTED_CURRENTS[$index]}"; then
            echo "[ERROR] Highest published test tag ${highest} is older than" >&2
            echo "        configured ${IMAGE_UPDATE_SELECTED_CURRENTS[$index]}; use rollback explicitly." >&2
            return 1
        fi
        IMAGE_UPDATE_SELECTED_VERSIONS+=("$highest")
        echo "[OK] Selected newest test image for ${IMAGE_UPDATE_SELECTED_LABELS[$index]}: ${highest}"
    done
}
