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
    [ "$1" = "example/api" ] && [ "$2" = "1.4.0" ]
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
        "1.2.3" "1.2.4" "1.3.0" "2.0.0" <<< "$input" >/dev/null
    if [ "$selected" != "$expected" ]; then
        printf 'Expected %s, received %s.\n' "$expected" "$selected" >&2
        exit 1
    fi
}

assert_published_selection "" "1.2.3"
assert_published_selection "p" "1.2.4"
assert_published_selection "f" "1.3.0"
assert_published_selection "m" "2.0.0"
assert_published_selection $'e\n1.2.4' "1.2.4"

fallback=""
select_published_semver fallback "API" "example/api" "1.2.3" "1.2.3" \
    <<< $'e\n1.4.0' >/dev/null
if [ "$fallback" != "1.4.0" ]; then
    printf '%s\n' "Registry-proven exact fallback was not accepted." >&2
    exit 1
fi

if select_published_semver rejected "API" "example/api" "1.2.3" "1.2.3" \
    <<< $'p\nq' >/dev/null; then
    printf '%s\n' "Unpublished patch version was accepted." >&2
    exit 1
fi

printf '%s\n' "Registry-backed semantic-version menu passed."
