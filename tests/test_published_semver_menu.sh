#!/usr/bin/env bash
# =============================================================================
# Module: test_published_semver_menu.sh
#
# Description:
#     Verifies canonical aliases without allowing unpublished Swarm image tags.
# =============================================================================

set -euo pipefail

TEST_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${TEST_ROOT}/setup/modules/semantic-version.sh"

# Simulate the exact-tag registry/platform proof used when enumeration misses.
#
# Args:
#   $1: Repository name.
#   $2: Candidate tag.
#
# Returns:
#   0 only for the test's known remote fallback tag.
registry_verify_tag() {
    [ "$1" = "example/api" ] &&
        { [ "$2" = "1.4.0" ] || [ "$2" = "1.1.0" ] ||
            [ "$2" = "feature-login_2" ]; }
}

# Assert one registry-backed selection.
#
# Args:
#   $1: Simulated operator input.
#   $2: Expected selected version.
#
# Returns:
#   0 on equality; exits the test when selection drifts.
assert_published_selection() {
    local input="$1"
    local expected="$2"
    local selected=""

    select_published_semver selected "API" "example/api" "1.2.3" \
        "1.2.3" "1.2.4" "1.3.0" "2.0.0" "1.1.0" <<< "$input" >/dev/null
    if [ "$selected" != "$expected" ]; then
        printf 'Expected %s, received %s.\n' "$expected" "$selected" >&2
        exit 1
    fi
}

assert_published_selection "" "2.0.0"
assert_published_selection "2" "2.0.0"
assert_published_selection "3" "1.3.0"
assert_published_selection "4" "1.2.4"
assert_published_selection $'e\n1.2.4' "1.2.4"

highest=""
select_published_semver highest "API" "example/api" "1.2.3" \
    1.2.3 1.2.4 <<< '' >/dev/null
if [ "$highest" != "1.2.4" ]; then
    printf '%s\n' "A caller variable named highest was not assigned." >&2
    exit 1
fi

fallback=""
select_published_semver fallback "API" "example/api" "1.2.3" "1.2.3" \
    <<< $'e\n1.4.0' >/dev/null
if [ "$fallback" != "1.4.0" ]; then
    printf '%s\n' "Registry-proven exact fallback was not accepted." >&2
    exit 1
fi

test_current=""
select_published_semver test_current "API" "example/api" "1.2.3-test" \
    1.1.0 1.2.3 1.2.4 <<< '' >/dev/null
if [ "$test_current" != "1.2.4" ]; then
    printf '%s\n' "A -test current tag did not use its stable SemVer base." >&2
    exit 1
fi

custom=""
select_published_semver custom "API" "example/api" "nightly-2026_08" \
    1.2.4 <<< $'e\nfeature-login_2' >/dev/null
if [ "$custom" != "feature-login_2" ]; then
    printf '%s\n' "A registry-proven custom Docker tag was not accepted." >&2
    exit 1
fi
if image_tag_is_deployable latest || image_tag_is_deployable latest-test; then
    printf '%s\n' "A mutable latest alias was accepted as an exact tag." >&2
    exit 1
fi

custom_current_output="$(
    select_published_semver ignored "API" "example/api" "nightly-2026_08" \
        1.2.4 <<< 'q' 2>&1 || true
)"
if [[ "$custom_current_output" != *'has no SemVer comparison base'* ]] ||
    [[ "$custom_current_output" != *'h) Highest published stable version (1.2.4)'* ]]; then
    printf '%s\n' "A custom current tag did not retain safe image-change options." >&2
    exit 1
fi

rollback=""
select_published_semver rollback "API" "example/api" "1.2.3" \
    "1.2.3" "1.1.0" <<< $'r\n1\n1' >/dev/null
if [ "$rollback" != "1.1.0" ]; then
    printf '%s\n' "Grouped published rollback was not accepted." >&2
    exit 1
fi

exact_rollback=""
select_published_semver exact_rollback "API" "example/api" "1.2.3" "1.2.3" \
    <<< $'e\n1.1.0' >/dev/null
if [ "$exact_rollback" != "1.1.0" ]; then
    printf '%s\n' "Registry-proven exact rollback was not accepted." >&2
    exit 1
fi

if select_published_semver rejected "API" "example/api" "1.2.3" "1.2.3" \
    <<< $'e\n9.9.9\nq' >/dev/null; then
    printf '%s\n' "Unpublished exact version was accepted." >&2
    exit 1
fi

menu_output="$(
    select_published_semver ignored "API" "example/api" "1.2.3" \
        "1.2.3" "1.2.4" "1.1.0" <<< 'q' 2>&1 || true
)"
if [[ "$menu_output" == *'[not published]'* ]]; then
    printf '%s\n' "Synthetic unpublished options were displayed." >&2
    exit 1
fi
if [[ "$menu_output" != *'r/x) Show rollback options'* ]]; then
    printf '%s\n' "Compact rollback entry was not displayed." >&2
    exit 1
fi
if [[ "$menu_output" == *'1.1.0 [rollback]'* ]]; then
    printf '%s\n' "Rollback versions leaked into the main menu." >&2
    exit 1
fi
rollback_versions=(
    1.1.1 0.11.1 0.11.0 0.10.24 0.10.23 0.10.22 0.10.21
    0.10.20 0.10.19 0.10.18 0.10.17 0.10.16 0.10.15 0.10.14
    0.10.13 0.10.12 0.10.11 0.10.10 0.10.9 0.10.8 0.10.7
    0.10.6 0.10.5
)
paginated=""
select_published_semver paginated "API" "example/api" "1.1.1" \
    "${rollback_versions[@]}" <<< $'r\n2\n9' >/dev/null
if [ "$paginated" != "0.10.16" ]; then
    printf 'Expected grouped rollback 0.10.16, received %s.\n' "$paginated" >&2
    exit 1
fi

pagination_output="$(
    select_published_semver ignored "API" "example/api" "1.1.1" \
        "${rollback_versions[@]}" <<< $'r\n2\nm\nq\nq\nq' || true
)"
if [[ "$pagination_output" != *'  9) 0.10.16 [rollback]'* ]] ||
    [[ "$pagination_output" != *'  19) 0.10.6 [rollback]'* ]]; then
    printf '%s\n' "Rollback version expansion did not retain and extend options." >&2
    exit 1
fi

series_output="$(
    select_published_semver ignored "API" "example/api" "3.0.0" \
        3.0.0 2.9.0 2.8.0 2.7.0 2.6.0 2.5.0 2.4.0 2.3.0 2.2.0 \
        2.1.0 2.0.0 <<< $'r\nm\nq\nq' || true
)"
if [[ "$series_output" != *'  9) Show 2.1.X versions'* ]] ||
    [[ "$series_output" != *'  10) Show 2.0.X versions'* ]]; then
    printf '%s\n' "Rollback release-series expansion is not newest-first." >&2
    exit 1
fi

printf '%s\n' "Registry-backed semantic-version menu passed."
